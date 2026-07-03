"""
risk.py — BTMM Risk & Position Sizing

Implements:
  • Foot Soldier strategy: 1% on initial signal, backed up with 2% aggregate
    on a confirmed retest/pullback.
  • Stop Loss placed beyond the wick of the 1st leg extreme (7–10 pip buffer).
  • Two-Hour Rule: scratch position if not in substantial profit within 120 min.
  • Limit/ZRT entry price calculation.
"""

from config import (
    PIP_SIZES,
    FOOT_SOLDIER_INITIAL_RISK,
    FOOT_SOLDIER_AGGREGATE_RISK,
    MAX_RISK_PER_TRADE,
    TWO_HOUR_RULE_MINS,
)
from datetime import datetime, timedelta


# ─────────────────────────────────────────────────────────────────────────────
# FOOT SOLDIER POSITION SIZING
# ─────────────────────────────────────────────────────────────────────────────

def calculate_foot_soldier_lots(balance, sl_pips, symbol, pip_value_per_lot=10.0,
                                 is_retest=False):
    """
    Foot Soldier sizing:
      Initial entry  → 1% of equity at risk.
      Retest entry   → 2% aggregate (backs up the initial position to improve
                        the weighted average entry).

    The same position size must be used on every signature setup — never
    increase risk because a setup "looks nicer".

    Parameters
    ----------
    balance          : float  – account equity in account currency.
    sl_pips          : float  – distance from entry to stop loss in pips.
    symbol           : str    – e.g. 'EURUSD'.
    pip_value_per_lot: float  – pip value per standard lot in account currency.
                                Default 10.0 USD for USD-denominated pairs.
    is_retest        : bool   – True when backing up an initial entry on retest.

    Returns
    -------
    float – lot size (rounded to 2 decimal places, minimum 0.01).
    """
    if sl_pips <= 0:
        return 0.01

    risk_pct    = FOOT_SOLDIER_AGGREGATE_RISK if is_retest else FOOT_SOLDIER_INITIAL_RISK
    risk_amount = balance * risk_pct
    lot = risk_amount / (sl_pips * pip_value_per_lot)
    return round(max(0.01, lot), 2)


def calculate_lot_size(balance, sl_pips, symbol, pip_value_per_lot=10.0):
    """
    Legacy wrapper — uses MAX_RISK_PER_TRADE.
    Prefer calculate_foot_soldier_lots() for new signals.
    """
    if sl_pips <= 0:
        return 0.01
    risk_amount = balance * MAX_RISK_PER_TRADE
    lot = risk_amount / (sl_pips * pip_value_per_lot)
    return round(max(0.01, lot), 2)


# ─────────────────────────────────────────────────────────────────────────────
# STOP LOSS PLACEMENT
# ─────────────────────────────────────────────────────────────────────────────

def get_stop_loss(signal_type, leg1_extreme, symbol, buffer_pips=10):
    """
    Hard stop loss placed 7–10 pips beyond the wick of the 1st leg extreme,
    NOT at the daily high/low.

    For a W-Bottom (BUY):
        SL = leg1_extreme (lowest wick of stop hunt) − buffer
    For an M-Top (SELL):
        SL = leg1_extreme (highest wick of stop hunt) + buffer

    Parameters
    ----------
    signal_type  : str   – 'BUY' or 'SELL'.
    leg1_extreme : float – the 1st leg's most extreme price (wick tip).
    symbol       : str   – e.g. 'EURUSD'.
    buffer_pips  : int   – additional pip buffer beyond the wick (default 10).

    Returns
    -------
    float – stop loss price.
    """
    pip_size = PIP_SIZES.get(symbol, 0.0001)
    offset   = buffer_pips * pip_size

    if signal_type == 'BUY':
        return leg1_extreme - offset    # Below the lowest wick of the W hunt
    else:
        return leg1_extreme + offset    # Above the highest wick of the M hunt


def get_sl_pips(signal_type, entry_price, leg1_extreme, symbol, buffer_pips=10):
    """
    Returns the stop distance in pips between entry and SL.
    Used to feed into lot size calculation.
    """
    pip_size = PIP_SIZES.get(symbol, 0.0001)
    sl_price = get_stop_loss(signal_type, leg1_extreme, symbol, buffer_pips)
    return abs(entry_price - sl_price) / pip_size


# ─────────────────────────────────────────────────────────────────────────────
# TWO-HOUR RULE
# ─────────────────────────────────────────────────────────────────────────────

def check_two_hour_rule(position_open_time, current_profit):
    """
    Scratch (close at break-even or small loss) if the position has not moved
    into substantial profit within 120 minutes of entry.

    Returns True if the position should be closed.
    """
    elapsed = datetime.now() - position_open_time
    if elapsed > timedelta(minutes=TWO_HOUR_RULE_MINS):
        if current_profit <= 0:
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# ZRT / LIMIT ENTRY PRICE
# ─────────────────────────────────────────────────────────────────────────────

def calculate_limit_price(leg1_extreme, yesterday_level, symbol, signal_type='BUY'):
    """
    Zero Risk Trade (ZRT) limit order price.

    For professional ZRT entries, place the limit at the peak/trough of the
    1st leg (the stop-hunt extreme). If a Blue Tracer (yesterday's H/L) is
    available and is closer to current price, prefer it instead.

    Parameters
    ----------
    leg1_extreme     : float        – extreme of the 1st leg wick.
    yesterday_level  : float | None – yesterday's High (for SELL) or
                                      yesterday's Low (for BUY). May be None.
    symbol           : str
    signal_type      : str          – 'BUY' or 'SELL'.

    Returns
    -------
    float – limit order price.
    """
    if yesterday_level is None:
        return leg1_extreme

    # Use whichever level is MORE extreme relative to current price direction
    if signal_type == 'BUY':
        # For a BUY limit, we want the higher of the two (closer to current price)
        return max(leg1_extreme, yesterday_level)
    else:
        # For a SELL limit, we want the lower of the two
        return min(leg1_extreme, yesterday_level)
