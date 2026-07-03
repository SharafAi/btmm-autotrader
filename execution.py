"""
execution.py — BTMM AutoTrader Main Loop

Entry logic follows a strict BINARY confluence gate. All 5 conditions must
pass or the setup is a hard PASS (no partial qualification):

  1. Asian Range ≤ 50 pips.
  2. Stop hunt extends 25–50 pips outside the Asian Range.
  3. Stop hunt shows 3 distinct vector pushes.
  4. Second leg M or W pattern with valid accumulation gap (30–90 min).
  5. Current time is within London or NY trading session.

Entry type:
  • Nameable pattern (RRT/Hammer/Star/COW) detected → MARKET order at next candle open.
  • No nameable pattern → LIMIT (ZRT) order at 1st leg extreme.

H1 candles are fetched separately for cycle level identification.
"""

import asyncio
import pandas as pd
from datetime import datetime

from config import (
    TOKEN, ACCOUNT_ID, SYMBOLS, ET_TZ, PIP_SIZES,
    ASIAN_MAX_PIPS,
    is_gap_time, is_valid_trading_session, is_friday_exit,
)
from metaapi_cloud_sdk import MetaApi
from indicators import calculate_tdi, get_ema_stack, calculate_adr
from patterns import detect_asian_range, detect_mw_pattern
from cycles import determine_bias, get_entry_bias_for_level
from risk import (
    calculate_foot_soldier_lots, get_stop_loss, get_sl_pips, calculate_limit_price,
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _build_df(candles, tz):
    """Convert raw MetaAPI candle list to a clean DataFrame with ET timestamps."""
    df = pd.DataFrame(candles)
    df['time']    = pd.to_datetime(df['time'])
    df['et_time'] = df['time'].dt.tz_localize('UTC').dt.tz_convert(tz)
    return df


def _get_yesterday_levels(df_d1):
    """
    Return (yesterday_high, yesterday_low) from a D1 DataFrame.
    These are the Blue Tracer levels used for ZRT limit entries.
    """
    if df_d1 is None or len(df_d1) < 2:
        return None, None
    yesterday = df_d1.iloc[-2]
    return yesterday['high'], yesterday['low']


def _log_pass(symbol, reason):
    print(f"  ⏭  PASS — {symbol}: {reason}")


def _log_signal(symbol, signal_info):
    sig = signal_info
    print(
        f"  🎯 SIGNAL — {symbol} | {sig['signal']} | "
        f"Entry: {sig['entry_type']} | Leg1: {sig['leg1_extreme']:.5f} | "
        f"Pushes: {sig['push_count']} | Gap: {sig['accum_candles']}c | "
        f"Patterns: {sig['patterns']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# CONFLUENCE GATE
# ─────────────────────────────────────────────────────────────────────────────

def check_confluence(symbol, df_15m, asian_high, asian_low, current_et,
                     emas_15m, tdi_15m, adr_15m, emas_h1, tdi_h1, adr_h1,
                     pdh, pdl):
    """
    Run the full 5-condition BTMM binary confluence gate.

    Returns (signal_dict, bias, level) or (None, None, None) on PASS.
    All conditions are binary — any failure is an immediate PASS.
    """
    pip_size = PIP_SIZES.get(symbol, 0.0001)

    # ── Condition 5: Session timing ───────────────────────────────────────────
    if not is_valid_trading_session(current_et):
        _log_pass(symbol, f"Outside valid session ({current_et.strftime('%H:%M')} ET)")
        return None, None, None

    # ── Condition 1: Asian Range ≤ 50 pips ───────────────────────────────────
    if asian_high is None or asian_low is None:
        _log_pass(symbol, "No Asian Range data")
        return None, None, None

    asian_pips = (asian_high - asian_low) / pip_size
    if asian_pips > ASIAN_MAX_PIPS:
        _log_pass(symbol, f"Asian Range too wide ({asian_pips:.1f} pips > 50)")
        return None, None, None

    # ── Conditions 2, 3, 4: M/W pattern with 3-push stop hunt + gap ──────────
    # detect_mw_pattern() enforces conditions 2–4 internally.
    pattern = detect_mw_pattern(df_15m, asian_high, asian_low, pdh, pdl,
                                emas_15m, symbol)
    if pattern is None:
        _log_pass(symbol, "No valid M/W pattern (conditions 2–4 not met)")
        return None, None, None

    # ── Cycle level & bias check (H1 data) ────────────────────────────────────
    bias, level = determine_bias(emas_h1, adr_h1, tdi_h1)
    direction   = get_entry_bias_for_level(level, emas_h1)

    # Align pattern direction with cycle bias
    expected_signal = 'W_BOTTOM' if direction == 'BUY' else 'M_TOP'
    if level > 0 and pattern['signal'] != expected_signal:
        _log_pass(symbol,
                  f"Pattern {pattern['signal']} conflicts with cycle bias "
                  f"(L{level} expects {expected_signal})")
        return None, None, None

    _log_signal(symbol, pattern)
    return pattern, bias, level


# ─────────────────────────────────────────────────────────────────────────────
# ORDER PLACEMENT
# ─────────────────────────────────────────────────────────────────────────────

async def _place_order(connection, symbol, pattern, balance,
                       pdh, pdl, is_retest=False):
    """
    Place either a market or limit order depending on entry type.

    • MARKET_OPEN  — nameable pattern → market order at current ask/bid.
    • LIMIT_ZRT    — no nameable pattern → limit order at leg1 extreme
                     (or Blue Tracer level if available).
    """
    sig         = pattern['signal']
    entry_type  = pattern['entry_type']
    leg1        = pattern['leg1_extreme']
    is_buy      = sig == 'W_BOTTOM'
    order_side  = 'BUY' if is_buy else 'SELL'

    # Stop loss beyond the 1st leg wick extreme
    sl_price    = get_stop_loss(order_side, leg1, symbol, buffer_pips=10)

    # For SL pip distance we need an approximate entry
    # — for market orders use leg1 as a proxy; for limits it IS the entry
    sl_pips     = get_sl_pips(order_side, leg1, leg1, symbol, buffer_pips=10)

    # Foot Soldier sizing
    lot = calculate_foot_soldier_lots(
        balance, sl_pips, symbol, is_retest=is_retest
    )

    if entry_type == 'MARKET_OPEN':
        print(f"  📤 MARKET {order_side} {symbol} | Lot: {lot} | SL: {sl_price:.5f}")
        # await connection.create_market_buy_order(symbol, lot, sl_price, None, {...})

    else:  # LIMIT_ZRT
        yesterday_h = pdh
        yesterday_l = pdl
        limit_price = calculate_limit_price(
            leg1,
            yesterday_l if is_buy else yesterday_h,
            symbol,
            order_side,
        )
        print(
            f"  📤 LIMIT {order_side} {symbol} @ {limit_price:.5f} | "
            f"Lot: {lot} | SL: {sl_price:.5f}"
        )
        # await connection.create_limit_buy_order(symbol, lot, limit_price, sl_price, None, {...})


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SCAN LOOP
# ─────────────────────────────────────────────────────────────────────────────

async def process_trades(connection, account):
    current_et = datetime.now(ET_TZ)

    print(f"\n{'='*60}")
    print(f"[{current_et.strftime('%Y-%m-%d %H:%M')} ET] Starting scan cycle")
    print(f"{'='*60}")

    # Hard gate: gap / dead-zone / Friday
    if is_gap_time(current_et):
        print(f"[GATE] Blocked — Gap or Dead Zone at {current_et.strftime('%H:%M')} ET")
        return
    if is_friday_exit(current_et):
        print("[GATE] Friday Exit — flattening all positions")
        # TODO: iterate open positions and close them
        return

    # Fetch account equity for position sizing
    account_info = await connection.get_account_information()
    balance = account_info.get('equity', 10000)

    for symbol in SYMBOLS:
        try:
            print(f"\n--- {symbol} ---")

            # ── Fetch 15m candles (entry TF) ─────────────────────────────────
            candles_15m = await account.get_historical_candles(
                symbol, '15m', datetime.now(), 200
            )
            df_15m = _build_df(candles_15m, ET_TZ)

            # ── Fetch H1 candles (cycle level TF) ────────────────────────────
            candles_h1 = await account.get_historical_candles(
                symbol, '1h', datetime.now(), 100
            )
            df_h1 = _build_df(candles_h1, ET_TZ)

            # ── Fetch D1 candles for yesterday's H/L (Blue Tracer) ───────────
            candles_d1 = await account.get_historical_candles(
                symbol, '1d', datetime.now(), 5
            )
            df_d1 = _build_df(candles_d1, ET_TZ)
            pdh, pdl = _get_yesterday_levels(df_d1)

            # ── Indicators on 15m ────────────────────────────────────────────
            emas_15m = get_ema_stack(df_15m['close'])
            tdi_15m  = calculate_tdi(df_15m['close'])
            adr_15m  = calculate_adr(df_15m['high'], df_15m['low']).iloc[-1]

            # ── Indicators on H1 ─────────────────────────────────────────────
            emas_h1  = get_ema_stack(df_h1['close'])
            tdi_h1   = calculate_tdi(df_h1['close'])
            adr_h1   = calculate_adr(df_h1['high'], df_h1['low']).iloc[-1]

            # ── Asian Range ───────────────────────────────────────────────────
            asian_high, asian_low = detect_asian_range(df_15m)

            # ── Confluence Gate (all 5 conditions) ───────────────────────────
            pattern, bias, level = check_confluence(
                symbol, df_15m, asian_high, asian_low, current_et,
                emas_15m, tdi_15m, adr_15m,
                emas_h1,  tdi_h1,  adr_h1,
                pdh, pdl,
            )

            if pattern is None:
                continue

            # ── Place order ───────────────────────────────────────────────────
            await _place_order(
                connection, symbol, pattern, balance, pdh, pdl, is_retest=False
            )

        except Exception as e:
            print(f"  ❌ Error processing {symbol}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    api     = MetaApi(TOKEN)
    account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
    await account.wait_connected()
    connection = account.get_rpc_connection()
    await connection.connect()
    await connection.wait_synchronized()

    while True:
        await process_trades(connection, account)
        await asyncio.sleep(60)   # Scan every minute


if __name__ == '__main__':
    asyncio.run(main())
