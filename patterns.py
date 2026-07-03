import pandas as pd
import numpy as np
from config import (
    PIP_SIZES, STOP_HUNT_MIN_PIPS, STOP_HUNT_MAX_PIPS, STOP_HUNT_PUSHES,
    ACCUM_GAP_MIN_CANDLES, ACCUM_GAP_MAX_CANDLES,
)


# ─────────────────────────────────────────────────────────────────────────────
# ASIAN RANGE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_asian_range(df):
    """
    Detects Asian Range (Tokyo Channel) based on ET time.
    Returns (high, low) of the session, or (None, None) if no data found.
    Expects df to have an 'et_time' column (timezone-aware).
    """
    asian_session = df[
        (df['et_time'].dt.time >= pd.to_datetime('20:30').time()) |
        (df['et_time'].dt.time <  pd.to_datetime('03:00').time())
    ]
    if asian_session.empty:
        return None, None

    return asian_session['high'].max(), asian_session['low'].min()


# ─────────────────────────────────────────────────────────────────────────────
# 3-PUSH VECTOR COUNT
# ─────────────────────────────────────────────────────────────────────────────

def count_stop_hunt_pushes(df_outside, direction):
    """
    Count the number of distinct directional 'pushes' (vector swipes) in the
    candles that extended beyond the Asian Range boundary.

    A new push is counted when price makes a new extreme in the hunt direction
    after retracing at least 30% of the prior swing from the boundary.

    Parameters
    ----------
    df_outside : DataFrame
        Subset of candles whose low (for DOWN hunt) or high (for UP hunt) are
        outside the Asian Range boundary.
    direction : str
        'DOWN' for a W-pattern stop hunt below Asian Low.
        'UP'   for an M-pattern stop hunt above Asian High.

    Returns
    -------
    int  – number of distinct pushes detected.
    """
    if df_outside.empty:
        return 0

    pushes = 0
    if direction == 'DOWN':
        prices = df_outside['low'].values
        # Track the running low and the highest retrace seen since last push
        current_extreme = prices[0]
        last_retrace_high = df_outside['high'].values[0]
        pushes = 1  # First candle outside range = first push

        for i in range(1, len(prices)):
            high_i = df_outside['high'].values[i]
            low_i  = prices[i]

            # Update retrace high
            if high_i > last_retrace_high:
                last_retrace_high = high_i

            if low_i < current_extreme:
                # Price is making a new low — still part of same push
                current_extreme = low_i
            else:
                # Check if retrace was ≥30% of the prior swing before this low
                prior_swing = abs(last_retrace_high - current_extreme)
                retrace_pct = (high_i - current_extreme) / prior_swing if prior_swing else 0
                if retrace_pct >= 0.30 and low_i < current_extreme + prior_swing * 0.70:
                    # New push (bounced ≥30% then made another lower low)
                    pushes += 1
                    current_extreme = low_i
                    last_retrace_high = high_i

    else:  # UP
        prices = df_outside['high'].values
        current_extreme = prices[0]
        last_retrace_low = df_outside['low'].values[0]
        pushes = 1

        for i in range(1, len(prices)):
            low_i  = df_outside['low'].values[i]
            high_i = prices[i]

            if low_i < last_retrace_low:
                last_retrace_low = low_i

            if high_i > current_extreme:
                current_extreme = high_i
            else:
                prior_swing = abs(current_extreme - last_retrace_low)
                retrace_pct = (current_extreme - low_i) / prior_swing if prior_swing else 0
                if retrace_pct >= 0.30 and high_i > current_extreme - prior_swing * 0.70:
                    pushes += 1
                    current_extreme = high_i
                    last_retrace_low = low_i

    return pushes


# ─────────────────────────────────────────────────────────────────────────────
# CANDLESTICK PATTERN DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_candlestick_patterns(df):
    """
    Detect nameable reversal patterns on the most recent candles.
    Returns a list of detected pattern names.

    Patterns checked:
      Hammer, Inverted Hammer, RRT (Railroad Tracks),
      Morning Star, Evening Star, COW (Cord of Wood).
    """
    if len(df) < 3:
        return []

    last  = df.iloc[-1]
    prev  = df.iloc[-2]
    prev2 = df.iloc[-3]

    patterns = []

    # ── Candle metrics ────────────────────────────────────────────────────────
    body        = abs(last['close'] - last['open'])
    upper_wick  = last['high'] - max(last['open'], last['close'])
    lower_wick  = min(last['open'], last['close']) - last['low']
    total_range = last['high'] - last['low']

    prev_body   = abs(prev['close'] - prev['open'])
    prev2_body  = abs(prev2['close'] - prev2['open'])

    # ── Hammer / Inverted Hammer ──────────────────────────────────────────────
    if body > 0:
        if lower_wick > body * 2 and upper_wick < body * 0.5:
            patterns.append('Hammer')
        if upper_wick > body * 2 and lower_wick < body * 0.5:
            patterns.append('Inverted Hammer')

    # ── Railroad Tracks (RRT) — "15 min up, 15 min away" ─────────────────────
    # Two opposite-colour candles of similar size.
    if prev_body > 0 and body > 0:
        size_similar = abs(prev_body - body) / prev_body < 0.25
        opposite_col = (
            (prev['close'] > prev['open'] and last['close'] < last['open']) or
            (prev['close'] < prev['open'] and last['close'] > last['open'])
        )
        if size_similar and opposite_col:
            patterns.append('RRT')

    # ── Morning Star (3-candle bullish reversal) ──────────────────────────────
    # Large bearish candle → small body/doji → large bullish candle closing into prev2
    is_morning_star = (
        prev2['close'] < prev2['open'] and           # candle 1: bearish
        prev2_body > total_range * 0.5 and           # candle 1: large
        prev_body < prev2_body * 0.35 and            # candle 2: small (star)
        last['close'] > last['open'] and             # candle 3: bullish
        last['close'] > (prev2['open'] + prev2['close']) / 2  # closes into candle 1
    )
    if is_morning_star:
        patterns.append('Morning Star')

    # ── Evening Star (3-candle bearish reversal) ──────────────────────────────
    is_evening_star = (
        prev2['close'] > prev2['open'] and           # candle 1: bullish
        prev2_body > total_range * 0.5 and           # candle 1: large
        prev_body < prev2_body * 0.35 and            # candle 2: small (star)
        last['close'] < last['open'] and             # candle 3: bearish
        last['close'] < (prev2['open'] + prev2['close']) / 2  # closes into candle 1
    )
    if is_evening_star:
        patterns.append('Evening Star')

    # ── Cord of Wood (COW) — small candles resting ON a level without breaking ─
    # Look at the last 3 candles: all small-bodied relative to the 10-bar ATR,
    # and none closed decisively through the reference level (asian_high/low).
    atr_proxy = df['high'].iloc[-10:].max() - df['low'].iloc[-10:].min()
    cow_candles = df.iloc[-3:]
    all_small = all(
        abs(r['close'] - r['open']) < atr_proxy * 0.15
        for _, r in cow_candles.iterrows()
    )
    if all_small and len(cow_candles) >= 3:
        patterns.append('COW')

    return patterns


def check_nameable_pattern_entry(patterns):
    """
    Returns True if any detected pattern qualifies for early entry
    (open of the next candle, without waiting for a 13 EMA close).

    Qualifying patterns: RRT, Hammer, Inverted Hammer, Morning Star,
    Evening Star, COW.
    """
    nameable = {'RRT', 'Hammer', 'Inverted Hammer', 'Morning Star', 'Evening Star', 'COW'}
    return bool(nameable.intersection(set(patterns)))


# ─────────────────────────────────────────────────────────────────────────────
# M/W PATTERN DETECTION  (full BTMM rule set)
# ─────────────────────────────────────────────────────────────────────────────

def detect_mw_pattern(df, asian_high, asian_low, pdh, pdl, emas, symbol):
    """
    Detect a valid BTMM M-Top or W-Bottom formation.

    BTMM minimum conditions enforced here (conditions 2-4 of the confluence gate):
      2. Stop hunt extends 25–50 pips outside the Asian Range.
      3. Stop hunt has 3 distinct vector pushes.
      4. Second leg M or W forms with valid accumulation gap (30–90 min).
         The 2nd leg must show a Near Miss (fails to break 1st leg extreme)
         OR a spike-through-and-reject.

    Standard entry trigger:
      The trigger candle must CLOSE on the correct side of the 13 EMA.
      If a nameable pattern is detected, early entry at the next candle open
      is permitted (handled by the caller).

    Returns
    -------
    dict or None
      {
        'signal':         'W_BOTTOM' | 'M_TOP',
        'entry_type':     'LIMIT_ZRT' | 'MARKET_OPEN',
        'leg1_extreme':   float,   # extreme of 1st leg (for SL and ZRT price)
        'accum_candles':  int,     # number of accumulation candles
        'push_count':     int,     # validated vector push count
        'patterns':       list,    # any nameable patterns detected
      }
    """
    if asian_high is None or asian_low is None:
        return None

    pip_size = PIP_SIZES.get(symbol, 0.0001)
    e13 = emas['ketchup'].iloc[-1]

    # We scan the last 60 candles so we capture the full stop-hunt + formation
    scan_df = df.iloc[-60:].reset_index(drop=True)

    # ── W-Bottom (bullish) ───────────────────────────────────────────────────
    result = _check_w_bottom(scan_df, asian_low, pdl, e13, pip_size)
    if result:
        return result

    # ── M-Top (bearish) ──────────────────────────────────────────────────────
    result = _check_m_top(scan_df, asian_high, pdh, e13, pip_size)
    if result:
        return result

    return None


def _find_first_leg(scan_df, boundary, direction, pip_size):
    """
    Locate the index of the 1st leg extreme (deepest candle below/above boundary).
    Returns (leg1_idx, leg1_extreme) or (None, None).
    """
    if direction == 'DOWN':
        # Candles that poked below the boundary
        candidates = scan_df[scan_df['low'] < boundary]
        if candidates.empty:
            return None, None
        leg1_idx     = candidates['low'].idxmin()
        leg1_extreme = candidates['low'].min()
    else:
        candidates = scan_df[scan_df['high'] > boundary]
        if candidates.empty:
            return None, None
        leg1_idx     = candidates['high'].idxmax()
        leg1_extreme = candidates['high'].max()

    return leg1_idx, leg1_extreme


def _check_w_bottom(scan_df, asian_low, pdl, e13, pip_size):
    """Internal helper — returns signal dict or None."""
    boundary = min(asian_low, pdl if pdl else asian_low)

    # 1. Find 1st leg (deepest candle below boundary)
    leg1_idx, leg1_extreme = _find_first_leg(scan_df, boundary, 'DOWN', pip_size)
    if leg1_idx is None:
        return None

    # 2. Inducement check: 25–50 pips below boundary
    inducement = (boundary - leg1_extreme) / pip_size
    if not (STOP_HUNT_MIN_PIPS <= inducement <= STOP_HUNT_MAX_PIPS):
        return None

    # 3. Count vector pushes in the stop-hunt zone
    outside_df = scan_df[scan_df['low'] < boundary]
    push_count = count_stop_hunt_pushes(outside_df, 'DOWN')
    if push_count < STOP_HUNT_PUSHES:
        return None

    # 4. Accumulation gap: candles between leg1 and now
    total_candles = len(scan_df)
    gap_candles   = total_candles - 1 - leg1_idx
    if not (ACCUM_GAP_MIN_CANDLES <= gap_candles <= ACCUM_GAP_MAX_CANDLES):
        return None

    # 5. Near Miss on 2nd leg — must NOT break leg1 extreme convincingly
    trigger = scan_df.iloc[-1]
    near_miss = trigger['low'] > leg1_extreme   # stays above leg1 low

    # Spike-through-and-reject: briefly went lower but body closed above
    spike_reject = (
        trigger['low'] <= leg1_extreme and
        trigger['close'] > leg1_extreme  # full-body rejection
    )

    if not (near_miss or spike_reject):
        return None

    # 6. Standard entry: trigger candle must close above 13 EMA
    ema_close_confirm = trigger['close'] > e13

    # 7. Check for nameable patterns (enables early entry at next open)
    patterns = detect_candlestick_patterns(scan_df.iloc[-10:].reset_index(drop=True))
    has_nameable = check_nameable_pattern_entry(patterns)

    if not (ema_close_confirm or has_nameable):
        return None

    entry_type = 'MARKET_OPEN' if has_nameable else 'LIMIT_ZRT'

    return {
        'signal':        'W_BOTTOM',
        'entry_type':    entry_type,
        'leg1_extreme':  leg1_extreme,
        'accum_candles': gap_candles,
        'push_count':    push_count,
        'patterns':      patterns,
    }


def _check_m_top(scan_df, asian_high, pdh, e13, pip_size):
    """Internal helper — returns signal dict or None."""
    boundary = max(asian_high, pdh if pdh else asian_high)

    leg1_idx, leg1_extreme = _find_first_leg(scan_df, boundary, 'UP', pip_size)
    if leg1_idx is None:
        return None

    inducement = (leg1_extreme - boundary) / pip_size
    if not (STOP_HUNT_MIN_PIPS <= inducement <= STOP_HUNT_MAX_PIPS):
        return None

    outside_df = scan_df[scan_df['high'] > boundary]
    push_count = count_stop_hunt_pushes(outside_df, 'UP')
    if push_count < STOP_HUNT_PUSHES:
        return None

    total_candles = len(scan_df)
    gap_candles   = total_candles - 1 - leg1_idx
    if not (ACCUM_GAP_MIN_CANDLES <= gap_candles <= ACCUM_GAP_MAX_CANDLES):
        return None

    trigger   = scan_df.iloc[-1]
    near_miss = trigger['high'] < leg1_extreme
    spike_reject = (
        trigger['high'] >= leg1_extreme and
        trigger['close'] < leg1_extreme
    )

    if not (near_miss or spike_reject):
        return None

    ema_close_confirm = trigger['close'] < e13

    patterns    = detect_candlestick_patterns(scan_df.iloc[-10:].reset_index(drop=True))
    has_nameable = check_nameable_pattern_entry(patterns)

    if not (ema_close_confirm or has_nameable):
        return None

    entry_type = 'MARKET_OPEN' if has_nameable else 'LIMIT_ZRT'

    return {
        'signal':        'M_TOP',
        'entry_type':    entry_type,
        'leg1_extreme':  leg1_extreme,
        'accum_candles': gap_candles,
        'push_count':    push_count,
        'patterns':      patterns,
    }
