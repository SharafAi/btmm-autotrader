"""
cycles.py — BTMM Cycle Level Identification & Bias Engine

Level Definitions (H1 chart):
  L1  — Accumulation:  EMAs flattening/tightening + 13/50 EMA crossover.
         Trade the breakout in the direction of the cross.
  L2  — Trending:      50/200 EMA crossover. Market-driven, may lack 3-swipe
         signature. Trade the continuation.
  L3  — Reversal:      Full EMA fanning (perfect order) + TDI RSI Shark Fin
         (RSI line outside Volatility Bands). Counter-trend reversal back
         toward 50 or 200 EMA.

All EMA comparisons must use H1 data passed in from the caller.
"""


def calculate_levels(adr, current_cycle_high, current_cycle_low):
    """
    Compute the ADR-derived level size (ADR / 3).
    Used to estimate the expected pip distance per cycle level.
    """
    return adr / 3


# ─────────────────────────────────────────────────────────────────────────────
# LEVEL IDENTIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def determine_bias(ema_stack, adr, tdi):
    """
    Identify the current market cycle level and directional bias.

    Parameters
    ----------
    ema_stack : dict of pd.Series
        Keys: 'mustard' (5), 'ketchup' (13), 'water' (50),
              'mayo' (200), 'blue' (800).
        Must be sourced from H1 candles for correct level identification.
    adr : float
        Average Daily Range in price units (not pips).
    tdi : dict of pd.Series
        Keys: 'rsi', 'signal', 'trade_signal', 'mbl', 'upper', 'lower'.

    Returns
    -------
    (bias_label : str, level : int)
      bias_label ∈ {'ACCUMULATION', 'TRENDING', 'REVERSAL_SCAN', 'NEUTRAL'}
      level      ∈ {0, 1, 2, 3}
    """
    e5   = ema_stack['mustard'].iloc[-1]
    e13  = ema_stack['ketchup'].iloc[-1]
    e50  = ema_stack['water'].iloc[-1]
    e200 = ema_stack['mayo'].iloc[-1]
    e800 = ema_stack['blue'].iloc[-1]

    # ── Level 3 — Full EMA fanning + TDI Shark Fin ───────────────────────────
    # "Perfect order" means all five EMAs are stacked cleanly in sequence.
    is_fanning_bull = e5 > e13 > e50 > e200 > e800
    is_fanning_bear = e5 < e13 < e50 < e200 < e800

    # TDI Shark Fin: RSI line pokes OUTSIDE the Volatility Bands
    shark_fin = (
        tdi['rsi'].iloc[-1] > tdi['upper'].iloc[-1] or
        tdi['rsi'].iloc[-1] < tdi['lower'].iloc[-1]
    )

    if (is_fanning_bull or is_fanning_bear) and shark_fin:
        return 'REVERSAL_SCAN', 3

    # ── Level 2 — 50/200 EMA Crossover ───────────────────────────────────────
    # Detect a recent crossover by comparing current vs. 5 candles ago.
    # A crossover means the 50 EMA has crossed through the 200 EMA.
    e50_prev  = ema_stack['water'].iloc[-6]
    e200_prev = ema_stack['mayo'].iloc[-6]
    is_lv2_bull = (e50_prev < e200_prev) and (e50 > e200)   # golden cross
    is_lv2_bear = (e50_prev > e200_prev) and (e50 < e200)   # death cross

    if is_lv2_bull or is_lv2_bear:
        return 'TRENDING', 2

    # ── Level 1 — 13/50 EMA Crossover + Tightening ───────────────────────────
    # The 13 EMA crosses through the 50 EMA (tightening/flattening phase ends).
    e13_prev = ema_stack['ketchup'].iloc[-6]
    e50_prev_l1 = ema_stack['water'].iloc[-6]
    is_lv1_bull = (e13_prev < e50_prev_l1) and (e13 > e50)
    is_lv1_bear = (e13_prev > e50_prev_l1) and (e13 < e50)

    # Also confirm EMAs are physically tightening (spread shrinking)
    ema_spread_now  = max(e5, e13, e50) - min(e5, e13, e50)
    ema_spread_prev = (
        max(ema_stack['mustard'].iloc[-6],
            ema_stack['ketchup'].iloc[-6],
            ema_stack['water'].iloc[-6]) -
        min(ema_stack['mustard'].iloc[-6],
            ema_stack['ketchup'].iloc[-6],
            ema_stack['water'].iloc[-6])
    )
    is_tightening = ema_spread_now < ema_spread_prev

    if (is_lv1_bull or is_lv1_bear) and is_tightening:
        return 'ACCUMULATION', 1

    return 'NEUTRAL', 0


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY BIAS PER LEVEL
# ─────────────────────────────────────────────────────────────────────────────

def get_entry_bias_for_level(level, ema_stack):
    """
    Translate cycle level into a directional trading bias.

    L1 — Trade breakout in the direction of the 13/50 EMA cross.
    L2 — Trade continuation in the direction of the 50/200 EMA cross.
    L3 — Counter-trend reversal back toward 50 or 200 EMA.

    Returns
    -------
    str: 'BUY', 'SELL', or 'NEUTRAL'
    """
    e13  = ema_stack['ketchup'].iloc[-1]
    e50  = ema_stack['water'].iloc[-1]
    e200 = ema_stack['mayo'].iloc[-1]

    if level == 1:
        # L1 breakout — direction of the 13/50 cross
        return 'BUY' if e13 > e50 else 'SELL'

    elif level == 2:
        # L2 continuation — direction of the 50/200 cross
        return 'BUY' if e50 > e200 else 'SELL'

    elif level == 3:
        # L3 counter-trend — buy if EMAs are in bearish perfect order
        # (price has overextended downward, reversal back UP expected),
        # sell if in bullish perfect order.
        e5 = ema_stack['mustard'].iloc[-1]
        e800 = ema_stack['blue'].iloc[-1]
        is_fanning_bull = e5 > e13 > e50 > e200 > e800
        # Counter-trend: if fanning bullish → sell the exhaustion
        return 'SELL' if is_fanning_bull else 'BUY'

    return 'NEUTRAL'
