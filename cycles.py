"""
cycles.py — BTMM Cycle Level Identification v4

Level Transitions on H1 chart:
  Level 1: 13/50 EMA crossover  (MM-driven, fast)
  Level 2: 50/200 EMA crossover (market-driven, slower)
  Level 3: Full EMA fanning + TDI outside bands + ADR 3x exhaustion
  Reset:   Price smacks Water (50 EMA) and resumes = trend continuation

33 Trade: Day 3 of L3 — 3 intraday pushes + hammer/RRT + RSI extreme
"""
import pandas as pd


def calculate_levels(adr, current_cycle_high=None, current_cycle_low=None):
    """ADR/3 gives the expected pip distance per level."""
    return adr / 3 if adr else 0


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CYCLE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_cycle_level(candles_daily, candles_htf):
    """
    Full cycle detection using H1 EMAs as primary trigger.
    Returns a rich dict with level, direction, trade_bias, and auxiliary flags.
    """
    try:
        if candles_htf is None or len(candles_htf) < 50:
            return _default_cycle()

        from indicators import calculate_tdi, calculate_all_emas, calculate_atr

        closes = candles_htf['close']
        highs  = candles_htf['high']
        lows   = candles_htf['low']

        tdi  = calculate_tdi(closes)
        emas = calculate_all_emas(closes)
        atr  = calculate_atr(highs, lows, closes).iloc[-1]

        cur_rsi   = float(tdi['rsi'].iloc[-1])
        cur_upper = float(tdi['upper'].iloc[-1])
        cur_lower = float(tdi['lower'].iloc[-1])

        mustard   = float(emas['mustard'].iloc[-1])
        ketchup   = float(emas['ketchup'].iloc[-1])
        water     = float(emas['water'].iloc[-1])
        mayo      = float(emas['mayo'].iloc[-1])
        blueberry = float(emas['blueberry'].iloc[-1])
        price     = float(closes.iloc[-1])

        direction = 'bullish' if price > float(closes.iloc[-4]) else 'bearish'

        # ── Level 1: 13/50 EMA crossover ─────────────────────────────────────
        k_prev  = float(emas['ketchup'].iloc[-2])
        w_prev  = float(emas['water'].iloc[-2])
        l1_bull = k_prev < w_prev and ketchup > water
        l1_bear = k_prev > w_prev and ketchup < water
        l1_bull_active = ketchup > water and price > water
        l1_bear_active = ketchup < water and price < water

        # ── Level 2: 50/200 EMA crossover ────────────────────────────────────
        w_prev2 = float(emas['water'].iloc[-2])
        m_prev2 = float(emas['mayo'].iloc[-2])
        l2_bull = w_prev2 < m_prev2 and water > mayo
        l2_bear = w_prev2 > m_prev2 and water < mayo
        l2_bull_active = water > mayo and ketchup > water
        l2_bear_active = water < mayo and ketchup < water

        # ── EMA Fanning (Level 3) ─────────────────────────────────────────────
        fanning_bull = mustard > ketchup > water > mayo
        fanning_bear = mustard < ketchup < water < mayo

        # ── Reset: price smacks Water and resumes ─────────────────────────────
        price_near_water = abs(price - water) < atr * 0.5
        water_touched    = any(
            float(lows.iloc[-5:].iloc[i]) <= water <= float(highs.iloc[-5:].iloc[i])
            for i in range(min(5, len(highs)))
        )
        is_reset = water_touched and (
            (direction == 'bullish' and price > water) or
            (direction == 'bearish' and price < water)
        )

        # ── RSI Divergence ────────────────────────────────────────────────────
        p_h1 = float(closes.iloc[-6:-3].max()); p_h2 = float(closes.iloc[-3:].max())
        r_h1 = float(tdi['rsi'].iloc[-6:-3].max()); r_h2 = float(tdi['rsi'].iloc[-3:].max())
        p_l1 = float(closes.iloc[-6:-3].min()); p_l2 = float(closes.iloc[-3:].min())
        r_l1 = float(tdi['rsi'].iloc[-6:-3].min()); r_l2 = float(tdi['rsi'].iloc[-3:].min())
        bearish_div = p_h2 > p_h1 and r_h2 < r_h1
        bullish_div = p_l2 < p_l1 and r_l2 > r_l1

        # ── ADR 3x exhaustion ─────────────────────────────────────────────────
        daily_range = float(highs.max()) - float(lows.min())
        at_3x_adr   = daily_range >= atr * 3

        # ── 33 Trade ──────────────────────────────────────────────────────────
        is_33_trade = _detect_33_trade(candles_htf, emas, tdi)

        # ── Level assignment ──────────────────────────────────────────────────
        level = 0; description = ''; trade_bias = 'NEUTRAL'

        if is_reset:
            level       = 1
            description = 'RESET — Price smacked Water (50 EMA), trend extending'
            trade_bias  = direction.upper()[:4]

        elif (cur_rsi > cur_upper or cur_rsi < cur_lower or
              fanning_bull or fanning_bear or at_3x_adr or
              bearish_div or bullish_div):
            level       = 3
            description = ('LEVEL 3 — EMAs fanned, TDI extreme. Reversal imminent' +
                           (' | 33 TRADE!' if is_33_trade else ''))
            trade_bias  = 'SELL' if direction == 'bullish' else 'BUY'

        elif l2_bull_active or l2_bear_active:
            level       = 2
            description = 'LEVEL 2 — 50/200 EMA crossed. Market-driven push.'
            trade_bias  = 'BUY' if direction == 'bullish' else 'SELL'

        elif l1_bull_active or l1_bear_active:
            level       = 1
            description = 'LEVEL 1 — 13/50 EMA crossed. MM-driven fast move.'
            trade_bias  = 'BUY' if direction == 'bullish' else 'SELL'

        # Volatility annotation
        recent_atr = float(calculate_atr(
            highs.iloc[-5:], lows.iloc[-5:], closes.iloc[-5:]).iloc[-1])
        vol_note = ''
        if recent_atr > float(atr) * 1.5: vol_note = 'High volatility'
        elif recent_atr < float(atr) * 0.7: vol_note = 'Low volatility — accumulation'

        return {
            'level':       level,
            'direction':   direction,
            'trade_bias':  trade_bias,
            'description': description,
            'next_expect': '',
            'vol_note':    vol_note,
            'rsi':         round(cur_rsi, 1),
            'fanning':     fanning_bull or fanning_bear,
            'divergence':  bearish_div or bullish_div,
            'is_reset':    is_reset,
            'is_33_trade': is_33_trade,
            'at_3x_adr':   at_3x_adr,
            'l1_cross':    l1_bull or l1_bear,
            'l2_cross':    l2_bull or l2_bear,
        }

    except Exception as e:
        print(f"   Cycle error: {e}")
        return _default_cycle()


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY determine_bias (kept for backward compat with old callers)
# ─────────────────────────────────────────────────────────────────────────────

def determine_bias(ema_stack, adr, tdi):
    """
    Simplified bias determination from EMA stack + TDI.
    Returns (bias_label, level) tuple.
    Prefer detect_cycle_level() for full analysis.
    """
    e5   = ema_stack['mustard'].iloc[-1]
    e13  = ema_stack['ketchup'].iloc[-1]
    e50  = ema_stack['water'].iloc[-1]
    e200 = ema_stack['mayo'].iloc[-1]
    e800 = ema_stack.get('blueberry', ema_stack.get('blue', ema_stack['mayo'])).iloc[-1]

    fanning_bull = e5 > e13 > e50 > e200 > e800
    fanning_bear = e5 < e13 < e50 < e200 < e800
    shark_fin    = (tdi['rsi'].iloc[-1] > tdi['upper'].iloc[-1] or
                   tdi['rsi'].iloc[-1] < tdi['lower'].iloc[-1])

    if (fanning_bull or fanning_bear) and shark_fin:
        return 'REVERSAL_SCAN', 3

    e50_prev  = ema_stack['water'].iloc[-6]
    e200_prev = ema_stack['mayo'].iloc[-6]
    if (e50_prev < e200_prev and e50 > e200) or (e50_prev > e200_prev and e50 < e200):
        return 'TRENDING', 2

    e13_prev = ema_stack['ketchup'].iloc[-6]
    e50_prev_l1 = ema_stack['water'].iloc[-6]
    if ((e13_prev < e50_prev_l1 and e13 > e50) or
            (e13_prev > e50_prev_l1 and e13 < e50)):
        spread_now  = max(e5, e13, e50) - min(e5, e13, e50)
        spread_prev = (max(ema_stack['mustard'].iloc[-6],
                           ema_stack['ketchup'].iloc[-6],
                           ema_stack['water'].iloc[-6]) -
                       min(ema_stack['mustard'].iloc[-6],
                           ema_stack['ketchup'].iloc[-6],
                           ema_stack['water'].iloc[-6]))
        if spread_now < spread_prev:
            return 'ACCUMULATION', 1

    return 'NEUTRAL', 0


def get_entry_bias_for_level(level, ema_stack):
    """Returns 'BUY', 'SELL', or 'NEUTRAL' for the given cycle level."""
    e13  = ema_stack['ketchup'].iloc[-1]
    e50  = ema_stack['water'].iloc[-1]
    e200 = ema_stack['mayo'].iloc[-1]

    if level == 1:
        return 'BUY' if e13 > e50 else 'SELL'
    elif level == 2:
        return 'BUY' if e50 > e200 else 'SELL'
    elif level == 3:
        e5   = ema_stack['mustard'].iloc[-1]
        e800 = ema_stack.get('blueberry', ema_stack.get('blue', ema_stack['mayo'])).iloc[-1]
        return 'SELL' if e5 > e13 > e50 > e200 > e800 else 'BUY'
    return 'NEUTRAL'


# ─────────────────────────────────────────────────────────────────────────────
# 33 TRADE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def _detect_33_trade(candles, emas, tdi):
    """33 Trade = 3 intraday pushes + hammer/RRT + RSI extreme."""
    try:
        highs = candles['high']; lows = candles['low']
        push_up = push_dn = 0
        ph = float(highs.iloc[0]); pl = float(lows.iloc[0])
        for i in range(1, min(len(candles), 20)):
            h = float(highs.iloc[i]); l = float(lows.iloc[i])
            if h > ph: push_up += 1
            if l < pl: push_dn += 1
            ph = max(ph, h); pl = min(pl, l)
        three_pushes = push_up >= 3 or push_dn >= 3

        last = candles.iloc[-1]
        body = abs(float(last['close']) - float(last['open'])) or 0.0001
        wick_dn = min(float(last['open']), float(last['close'])) - float(last['low'])
        wick_up = float(last['high']) - max(float(last['open']), float(last['close']))
        has_hammer  = wick_dn > body * 2 or wick_up > body * 2
        rsi_extreme = float(tdi['rsi'].iloc[-1]) > 68 or float(tdi['rsi'].iloc[-1]) < 32

        return three_pushes and has_hammer and rsi_extreme
    except:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _default_cycle():
    return {
        'level': 0, 'direction': 'neutral', 'trade_bias': 'NEUTRAL',
        'description': 'Cycle unknown', 'next_expect': 'Wait for signal',
        'vol_note': '', 'rsi': 50.0, 'fanning': False, 'divergence': False,
        'is_reset': False, 'is_33_trade': False, 'at_3x_adr': False,
        'l1_cross': False, 'l2_cross': False,
    }


def get_cycle_emoji(level):
    return {0: '⚪', 1: '🟡', 2: '🟠', 3: '🔴'}.get(level, '⚪')


def get_day_of_week_note():
    from patterns import get_ny_time
    ny  = get_ny_time()
    day = ny.weekday()
    notes = {
        0: ('Monday',    '⚠️ Fake move risk. Watch, confirm cycle first.'),
        1: ('Tuesday',   '✅ High probability. L1 or L2 setups.'),
        2: ('Wednesday', '✅ Highest probability. Midweek reversal common.'),
        3: ('Thursday',  '✅ Good probability. Exploitation phase.'),
        4: ('Friday',    '🚫 Exit only. No new trades after 16:00 ET.'),
    }
    name, note = notes.get(day, ('Unknown', ''))
    return name, note, day
