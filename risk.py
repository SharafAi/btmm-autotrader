"""
risk.py — BTMM Risk Management

SL:  7-15 pips outside today's absolute High or Low (per blueprint)
TP1: Water (50 EMA) — intraday balance
TP2: Mayonnaise (200 EMA) — home base / institutional target
RR:  Minimum 2:1, target 3:1
BE:  After 1st impulse completes (Foot Soldier rule)

Foot Soldier: 1% equity on initial signal, 2% aggregate on confirmed retest.
"""
import math
from datetime import datetime, timedelta
import pytz

from config import (
    PIP_SIZES, FOOT_SOLDIER_INITIAL_RISK, FOOT_SOLDIER_AGGREGATE_RISK,
    MAX_RISK_PER_TRADE, MIN_RISK_PER_TRADE, TWO_HOUR_RULE_MINS,
)

NY_TZ = pytz.timezone('America/New_York')


# ─────────────────────────────────────────────────────────────────────────────
# PIP SIZE
# ─────────────────────────────────────────────────────────────────────────────

def _pip(symbol):
    clean = symbol.rstrip('c') if symbol.endswith('c') and len(symbol) > 6 else symbol
    return PIP_SIZES.get(clean, PIP_SIZES.get(symbol, 0.0001))


# ─────────────────────────────────────────────────────────────────────────────
# FOOT SOLDIER POSITION SIZING
# ─────────────────────────────────────────────────────────────────────────────

def calculate_foot_soldier_lots(balance, sl_pips, symbol,
                                 pip_value_per_lot=10.0, is_retest=False):
    """
    Foot Soldier: 1% on initial entry, 2% on confirmed retest.
    Same size must be used for every signature setup.
    """
    if sl_pips <= 0:
        return 0.01
    risk_pct    = FOOT_SOLDIER_AGGREGATE_RISK if is_retest else FOOT_SOLDIER_INITIAL_RISK
    risk_amount = balance * risk_pct
    lot = risk_amount / (sl_pips * pip_value_per_lot)
    return round(max(0.01, lot), 2)


def calculate_lot_size(balance, sl_pips, symbol, pip_value_per_lot=10.0):
    """Legacy wrapper — uses MAX_RISK_PER_TRADE."""
    if sl_pips <= 0:
        return 0.01
    lot = (balance * MAX_RISK_PER_TRADE) / (sl_pips * pip_value_per_lot)
    return round(max(0.01, lot), 2)


def _calculate_lot_pct(balance, risk_pct, sl_pips, symbol):
    """Dynamic lot based on % of equity (used by execution engine)."""
    try:
        pip_value = 10.0
        if 'JPY' in symbol: pip_value = 9.0
        if 'XAU' in symbol: pip_value = 10.0
        if 'BTC' in symbol: pip_value = 1.0
        risk_amount = balance * (risk_pct / 100)
        lot = risk_amount / (sl_pips * pip_value)
        return round(max(0.01, lot), 2)
    except:
        return 0.01


# ─────────────────────────────────────────────────────────────────────────────
# STOP LOSS PLACEMENT
# ─────────────────────────────────────────────────────────────────────────────

def get_day_high_low(candles):
    """Today's absolute High and Low for SL placement."""
    try:
        import pandas as pd
        df    = candles.copy()
        times = pd.to_datetime(df['time'])
        if times.dt.tz is None: times = times.dt.tz_localize('UTC')
        df['ny_date'] = times.dt.tz_convert(NY_TZ).dt.date
        today         = datetime.now(NY_TZ).date()
        today_c       = df[df['ny_date'] == today]
        if today_c.empty: today_c = df.tail(20)
        return float(today_c['high'].max()), float(today_c['low'].min())
    except:
        return float(candles['high'].tail(20).max()), float(candles['low'].tail(20).min())


def get_stop_loss(signal_type, leg1_extreme, symbol, buffer_pips=10):
    """
    Hard SL placed beyond the 1st leg wick extreme (7-10 pip buffer).
    BUY: SL below the deepest low of the stop hunt.
    SELL: SL above the highest high of the stop hunt.
    """
    offset = buffer_pips * _pip(symbol)
    if signal_type == 'BUY':
        return round(leg1_extreme - offset, 5)
    else:
        return round(leg1_extreme + offset, 5)


def get_sl_pips(signal_type, entry_price, leg1_extreme, symbol, buffer_pips=10):
    sl = get_stop_loss(signal_type, leg1_extreme, symbol, buffer_pips)
    return abs(entry_price - sl) / _pip(symbol)


# ─────────────────────────────────────────────────────────────────────────────
# FULL SL/TP CALCULATION (Water/Mayo priority)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_sl_tp(signal_type, entry_price, atr, candles,
                    rr=2.0, mode='btmm', symbol='EURUSD',
                    emas=None, session_high=None, session_low=None):
    """
    Blueprint SL/TP:
      SL:  Day High/Low + 7-15 pip buffer
      TP1: Water (50 EMA) — if gives ≥1.5:1 RR
      TP2: Mayo (200 EMA) — second target
      Fallback: session level → round number → RR multiple
    """
    pip_size  = _pip(symbol)
    is_gold   = 'XAU' in symbol
    is_crypto = 'BTC' in symbol or 'ETH' in symbol

    if is_gold:     sl_buf = 150 * pip_size; max_buf = 300 * pip_size
    elif is_crypto: sl_buf = 50  * pip_size; max_buf = 200 * pip_size
    else:           sl_buf = 10  * pip_size; max_buf = 15  * pip_size

    day_high, day_low = get_day_high_low(candles)

    if signal_type == 'BUY':
        sl   = round(day_low - sl_buf, 5)
        if sl >= entry_price:
            sl = round(float(candles['low'].iloc[-8:].min()) - sl_buf, 5)
        if sl >= entry_price:
            sl = round(entry_price - 10 * pip_size, 5)
        if (entry_price - sl) > max_buf:
            sl = round(entry_price - max_buf, 5)
        risk = max(entry_price - sl, 10 * pip_size)
        sl   = round(entry_price - risk, 5)
    elif signal_type == 'SELL':
        sl   = round(day_high + sl_buf, 5)
        if sl <= entry_price:
            sl = round(float(candles['high'].iloc[-8:].max()) + sl_buf, 5)
        if sl <= entry_price:
            sl = round(entry_price + 10 * pip_size, 5)
        if (sl - entry_price) > max_buf:
            sl = round(entry_price + max_buf, 5)
        risk = max(sl - entry_price, 10 * pip_size)
        sl   = round(entry_price + risk, 5)
    else:
        return None, None

    # ── TAKE PROFIT ──────────────────────────────────────────────────────────
    tp = None
    if emas is not None:
        water = float(emas['water'].iloc[-1])
        mayo  = float(emas['mayo'].iloc[-1])
        min_p = 10 * pip_size

        if signal_type == 'BUY':
            wdist = water - entry_price
            if water > entry_price and wdist > min_p and wdist >= risk * 1.5:
                tp = round(water, 5)
            if tp is None:
                mdist = mayo - entry_price
                if mayo > entry_price and mdist > min_p and mdist >= risk * 1.8:
                    tp = round(mayo, 5)
            if tp is None and session_high and (session_high - entry_price) >= risk * 1.8:
                tp = round(session_high, 5)
        else:
            wdist = entry_price - water
            if water < entry_price and wdist > min_p and wdist >= risk * 1.5:
                tp = round(water, 5)
            if tp is None:
                mdist = entry_price - mayo
                if mayo < entry_price and mdist > min_p and mdist >= risk * 1.8:
                    tp = round(mayo, 5)
            if tp is None and session_low and (entry_price - session_low) >= risk * 1.8:
                tp = round(session_low, 5)

    if tp is None:
        tp = round(entry_price + risk * rr if signal_type == 'BUY'
                   else entry_price - risk * rr, 5)

    actual_rr = abs(tp - entry_price) / risk if risk > 0 else 0
    if actual_rr < 1.5:
        return None, None

    return round(sl, 5), round(tp, 5)


# ─────────────────────────────────────────────────────────────────────────────
# WAYPOINT TP FINDER
# ─────────────────────────────────────────────────────────────────────────────

def get_waypoint_tp(entry_price, signal_type, pip_size, risk):
    """Find nearest 00/50 waypoint giving ≥2:1 RR."""
    from patterns import get_nearest_waypoints
    above, below = get_nearest_waypoints(entry_price, pip_size, count=5)
    if signal_type == 'BUY':
        for wp in above:
            if (wp - entry_price) >= risk * 2.0:
                return round(wp, 5)
    else:
        for wp in reversed(below):
            if (entry_price - wp) >= risk * 2.0:
                return round(wp, 5)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# TRADE MONITORING UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def profit_pips(signal_type, entry, current, symbol):
    p = _pip(symbol)
    return (current - entry) / p if signal_type == 'BUY' else (entry - current) / p


def check_two_hour_rule(position_open_time, current_profit):
    """Returns True if position should be scratched (2-Hour Rule)."""
    elapsed = datetime.now() - position_open_time
    return elapsed > timedelta(minutes=TWO_HOUR_RULE_MINS) and current_profit <= 0


def should_trail_stop(signal_type, tdi_rsi, tdi_signal, tdi_mbl):
    """True if TDI confirms a trend reversal — exit signal."""
    try:
        rsi = float(tdi_rsi.iloc[-1])
        sig = float(tdi_signal.iloc[-1])
        mbl = float(tdi_mbl.iloc[-1])
        if signal_type == 'BUY'  and rsi < sig and rsi < mbl: return True
        if signal_type == 'SELL' and rsi > sig and rsi > mbl: return True
        return False
    except:
        return False


def calculate_limit_price(leg1_extreme, yesterday_level, symbol, signal_type='BUY'):
    """ZRT limit order price — prefer Blue Tracer if closer."""
    if yesterday_level is None:
        return leg1_extreme
    return (max(leg1_extreme, yesterday_level) if signal_type == 'BUY'
            else min(leg1_extreme, yesterday_level))


def calculate_sl_pips(entry_price, sl_price, symbol):
    return max(round(abs(entry_price - sl_price) / _pip(symbol), 1), 1.0)
