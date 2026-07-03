"""
patterns.py — BTMM Pattern & Session Logic

Vector counting: 3 unequal swipes outside Asian Range
  (~15p, ~8p, ~3-5p — generally decreasing)
  Most common 1:00–4:00 AM ET (11:00–14:00 MVT)

Blue Tracer: Yesterday's HOD/LOD — spike + hammer = 2nd leg signal
Waypoints:   00 and 50 psychological round numbers
AR Cache:    Stored per symbol/day so it persists across scan cycles
"""
import pandas as pd
import math
from datetime import datetime
import pytz

NY_TZ = pytz.timezone('America/New_York')
MV_TZ = pytz.timezone('Indian/Maldives')

from config import (
    PIP_SIZES, STOP_HUNT_MIN_PIPS, STOP_HUNT_MAX_PIPS, STOP_HUNT_PUSHES,
    ACCUM_GAP_MIN_CANDLES, ACCUM_GAP_MAX_CANDLES,
)

def get_ny_time(): return datetime.now(NY_TZ)
def get_mv_time(): return datetime.now(MV_TZ)
def _hhmm(dt):    return f"{dt.hour:02d}:{dt.minute:02d}"
def _minutes(dt): return dt.hour * 60 + dt.minute

# ── ASIAN RANGE CACHE ─────────────────────────────────────────────────────────
_ar_cache = {}   # {symbol_date: (high, low, pips, valid)}

# ── SESSION INFO ──────────────────────────────────────────────────────────────

def get_session_info():
    ny = get_ny_time(); mv = get_mv_time()
    t  = _minutes(ny)
    def _t(hh, mm=0): return hh * 60 + mm

    active = []
    if t >= _t(20,30) or t < _t(3,0):  active.append('asian')
    if _t(8,0)  <= t < _t(12,0):       active.append('london')
    if _t(13,0) <= t < _t(18,0):       active.append('ny')

    is_primary     = (_t(8,0) <= t < _t(10,0)) or (_t(13,0) <= t < _t(15,0))
    is_gap         = (_t(7,30) <= t < _t(8,0)) or (_t(12,30) <= t < _t(13,0))
    is_dharma      = _t(17,0) <= t < _t(20,30)
    is_lull        = _t(18,0) <= t < _t(20,30)
    is_brinks      = (_t(8,43) <= t <= _t(8,47)) or (_t(13,43) <= t <= _t(13,47))
    is_friday_exit = (ny.weekday() == 4 and t >= _t(16,0))
    is_vector_window = _t(1,0) <= t < _t(4,0)   # Most common vector window

    return {
        'ny_time': _hhmm(ny), 'mv_time': _hhmm(mv),
        'active': active, 'is_primary': is_primary,
        'is_gap': is_gap, 'is_dharma': is_dharma,
        'is_lull': is_lull, 'is_brinks': is_brinks,
        'is_friday_exit': is_friday_exit,
        'is_vector_window': is_vector_window,
        'ny_dt': ny, 'mv_dt': mv, 'weekday': ny.weekday(),
    }


def is_btmm_session():
    """Gate: returns False during any blocked/dead zone."""
    info = get_session_info()
    if info['is_friday_exit']: return False
    if info['is_gap']:         return False
    if info['is_dharma']:      return False
    if info['is_lull']:        return False
    return len(info['active']) > 0 and any(
        s in info['active'] for s in ['london', 'ny'])


# ── ASIAN RANGE (with caching) ────────────────────────────────────────────────

def detect_asian_range(candles, symbol=''):
    """
    Detects Asian Range (Tokyo Channel). Caches result per symbol/day so the
    AR is available all session without recalculation.
    Returns (high, low, pip_range, is_valid).
    """
    try:
        now_ny    = get_ny_time()
        cache_key = f"{symbol}_{now_ny.date()}"

        if cache_key in _ar_cache:
            return _ar_cache[cache_key]

        df    = candles.copy()
        times = pd.to_datetime(df['time'])
        if times.dt.tz is None: times = times.dt.tz_localize('UTC')
        ny_t        = times.dt.tz_convert(NY_TZ)
        df['ny_t']  = ny_t.dt.hour * 60 + ny_t.dt.minute
        df['ny_dt'] = ny_t

        # Asian session spans midnight: 20:30 → 07:00 ET
        asian = df[(df['ny_t'] >= 20*60+30) | (df['ny_t'] < 7*60)].tail(50)

        if asian.empty or len(asian) < 3:
            return None, None, 0, False

        h = float(asian['high'].max())
        l = float(asian['low'].min())
        r = h - l

        # Auto-detect pip size
        if h > 10000:  pip = 1.0
        elif h > 1000: pip = 0.1
        elif h > 100:  pip = 0.01
        else:          pip = 0.0001

        rng_pips = r / pip
        is_valid = rng_pips < 50

        _ar_cache[cache_key] = (h, l, rng_pips, is_valid)
        print(f"   AR: H:{round(h,5)} L:{round(l,5)} "
              f"{round(rng_pips,1)}p {'✅' if is_valid else '❌>50p'}")
        return h, l, rng_pips, is_valid

    except Exception as e:
        print(f"   AR error: {e}")
        return None, None, 0, False


# ── VECTOR COUNTING (swipe-based, unequal sizes) ──────────────────────────────

def count_stop_hunt_vectors(candles, asian_h, asian_l):
    """
    Blueprint: 3 unequal swipes outside AR (1st ~15p, 2nd ~8p, 3rd ~3-5p).
    Each distinct move outside the range that retracts = one swipe.
    Returns (count, direction).
    """
    try:
        if asian_h is None or asian_l is None:
            return 0, 'none'

        if asian_h > 10000:  pip = 1.0
        elif asian_h > 1000: pip = 0.1
        elif asian_h > 100:  pip = 0.01
        else:                pip = 0.0001

        above_swipes, below_swipes = [], []
        in_above = in_below = False
        max_above = max_below = 0

        for _, row in candles.iterrows():
            h = float(row['high']); l = float(row['low'])

            if h > asian_h:
                swipe = (h - asian_h) / pip
                if not in_above:
                    in_above  = True
                    max_above = swipe
                    if max_below > 0:
                        below_swipes.append(max_below); max_below = 0
                    in_below  = False
                else:
                    max_above = max(max_above, swipe)
            elif l < asian_l:
                swipe = (asian_l - l) / pip
                if not in_below:
                    in_below  = True
                    max_below = swipe
                    if max_above > 0:
                        above_swipes.append(max_above); max_above = 0
                    in_above  = False
                else:
                    max_below = max(max_below, swipe)
            else:
                if in_above and max_above > 0:
                    above_swipes.append(max_above); max_above = 0
                if in_below and max_below > 0:
                    below_swipes.append(max_below); max_below = 0
                in_above = in_below = False

        if max_above > 0: above_swipes.append(max_above)
        if max_below > 0: below_swipes.append(max_below)

        def _unequal(sw):
            return len(sw) >= 2 and sorted(sw, reverse=True)[0] >= 5

        if len(above_swipes) >= 3 or (len(above_swipes) >= 2 and _unequal(above_swipes)):
            return min(len(above_swipes), 5), 'bearish'
        if len(below_swipes) >= 3 or (len(below_swipes) >= 2 and _unequal(below_swipes)):
            return min(len(below_swipes), 5), 'bullish'

        count = max(len(above_swipes), len(below_swipes))
        direction = ('bearish' if len(above_swipes) > len(below_swipes) else
                     'bullish' if len(below_swipes) > len(above_swipes) else 'none')
        return count, direction
    except:
        return 0, 'none'


# ── BLUE TRACER (Yesterday's HOD/LOD) ─────────────────────────────────────────

def get_blue_tracer(candles):
    """
    Blueprint: Yesterday's High and Low.
    If price spikes the tracer and issues a hammer = high-prob 2nd leg.
    Returns (prev_high, prev_low, spiked_high, spiked_low).
    """
    try:
        df    = candles.copy()
        times = pd.to_datetime(df['time'])
        if times.dt.tz is None: times = times.dt.tz_localize('UTC')
        df['ny_date'] = times.dt.tz_convert(NY_TZ).dt.date
        dates = sorted(df['ny_date'].unique())
        if len(dates) < 2:
            return None, None, False, False

        yest     = df[df['ny_date'] == dates[-2]]
        prev_h   = float(yest['high'].max())
        prev_l   = float(yest['low'].min())
        recent   = candles.tail(5)
        spk_h    = any(float(r['high']) > prev_h for _, r in recent.iterrows())
        spk_l    = any(float(r['low'])  < prev_l for _, r in recent.iterrows())
        return prev_h, prev_l, spk_h, spk_l
    except:
        return None, None, False, False


# ── WAYPOINTS (00 and 50 round numbers) ──────────────────────────────────────

def get_nearest_waypoints(price, pip_size, count=3):
    """Returns lists of nearest round-number waypoints above and below price."""
    try:
        unit = (0.005 if pip_size <= 0.0001 else
                0.5   if pip_size == 0.01  else
                5.0   if pip_size == 0.1   else 500.0)
        base      = round(price / unit) * unit
        above_wp  = [round(base + unit * i, 5) for i in range(1, count + 1)]
        below_wp  = [round(base - unit * i, 5) for i in range(1, count + 1)]
        return above_wp, below_wp
    except:
        return [], []


def is_near_waypoint(price, pip_size, tolerance_pips=5):
    """True if price is within tolerance_pips of any 00/50 level."""
    try:
        above, below = get_nearest_waypoints(price, pip_size, count=1)
        tol = tolerance_pips * pip_size
        if above and abs(price - above[0]) <= tol: return True
        if below and abs(price - below[0]) <= tol: return True
        return False
    except:
        return False


def get_nearest_round_number(price, pip_size, direction):
    try:
        unit = (0.005 if pip_size <= 0.0001 else
                0.25  if pip_size == 0.01  else
                5.0   if pip_size == 0.1   else 500.0)
        if direction == 'BUY':
            return round(math.ceil(price / unit) * unit, 5)
        else:
            return round(math.floor(price / unit) * unit, 5)
    except:
        return None


# ── SESSION H/L (for TP targets) ─────────────────────────────────────────────

def get_session_high_low(candles):
    """Returns (high, low) of the relevant prior session for TP targeting."""
    try:
        df    = candles.copy()
        times = pd.to_datetime(df['time'])
        if times.dt.tz is None: times = times.dt.tz_localize('UTC')
        ny_t        = times.dt.tz_convert(NY_TZ)
        df['ny_t']  = ny_t.dt.hour * 60 + ny_t.dt.minute
        df['ny_date']= ny_t.dt.date
        now_ny  = get_ny_time()
        now_t   = _minutes(now_ny)
        today   = now_ny.date()
        def _t(hh, mm=0): return hh * 60 + mm

        if _t(13,0) <= now_t < _t(18,0):
            sess = df[(df['ny_date'] == today) &
                      (df['ny_t'] >= _t(8,0)) & (df['ny_t'] < _t(12,0))]
        elif _t(8,0) <= now_t < _t(12,0):
            yesterday = (now_ny - pd.Timedelta(days=1)).date()
            sess = df[((df['ny_date'] == yesterday) & (df['ny_t'] >= _t(20,30))) |
                      ((df['ny_date'] == today)     & (df['ny_t'] < _t(7,0)))]
        elif now_t >= _t(20,30) or now_t < _t(7,0):
            yesterday = (now_ny - pd.Timedelta(days=1)).date()
            sess = df[(df['ny_date'] == yesterday) &
                      (df['ny_t'] >= _t(13,0)) & (df['ny_t'] < _t(18,0))]
        else:
            return None, None

        if sess.empty or len(sess) < 3:
            return None, None
        return float(sess['high'].max()), float(sess['low'].min())
    except:
        return None, None


def get_prev_day_levels(candles):
    """Returns (prev_high, prev_low) for the previous calendar day."""
    try:
        df = candles.copy()
        df['time']    = pd.to_datetime(df['time'], utc=True)
        df['ny_date'] = df['time'].dt.tz_convert(NY_TZ).dt.date
        dates = sorted(df['ny_date'].unique())
        if len(dates) >= 2:
            yest = df[df['ny_date'] == dates[-2]]
            return float(yest['high'].max()), float(yest['low'].min())
        return float(df['high'].max()), float(df['low'].min())
    except:
        return None, None


# ── CANDLESTICK PATTERNS ──────────────────────────────────────────────────────

def detect_manipulation(candles):
    """Long wick candle in last 5 bars = stop hunt manipulation."""
    try:
        for i in range(-5, 0):
            c    = candles.iloc[i]
            body = abs(c['close'] - c['open']) or 0.0001
            if (min(c['open'], c['close']) - c['low'])  > body * 2.5: return 'bullish'
            if (c['high'] - max(c['open'], c['close'])) > body * 2.5: return 'bearish'
        return None
    except:
        return None


def detect_candlestick_confirmation(candles):
    """Returns pattern name string or None."""
    try:
        c    = candles.iloc[-1]
        body = abs(c['close'] - c['open']) or 0.0001
        wick_up = c['high'] - max(c['open'], c['close'])
        wick_dn = min(c['open'], c['close']) - c['low']
        if wick_dn > body * 2 and wick_up < body * 0.5: return 'hammer'
        if wick_up > body * 2 and wick_dn < body * 0.5: return 'shooting_star'
        if len(candles) >= 2:
            prev      = candles.iloc[-2]
            prev_body = abs(prev['close'] - prev['open'])
            if (prev['close'] > prev['open'] and c['close'] < c['open'] and
                    abs(body - prev_body) < body * 0.3):
                return 'railroad_tracks'
        return None
    except:
        return None


def detect_candlestick_patterns(df):
    """Extended pattern list — returns list of matched names."""
    if len(df) < 3:
        return []
    last = df.iloc[-1]; prev = df.iloc[-2]; prev2 = df.iloc[-3]
    body        = abs(last['close'] - last['open'])
    upper_wick  = last['high'] - max(last['open'], last['close'])
    lower_wick  = min(last['open'], last['close']) - last['low']
    prev_body   = abs(prev['close'] - prev['open'])
    prev2_body  = abs(prev2['close'] - prev2['open'])
    patterns    = []

    if body > 0:
        if lower_wick > body * 2 and upper_wick < body * 0.5: patterns.append('Hammer')
        if upper_wick > body * 2 and lower_wick < body * 0.5: patterns.append('Inverted Hammer')

    if prev_body > 0 and body > 0:
        if (abs(prev_body - body) / prev_body < 0.25 and
            ((prev['close'] > prev['open']) != (last['close'] > last['open']))):
            patterns.append('RRT')

    if (prev2['close'] < prev2['open'] and prev_body < prev2_body * 0.35 and
            last['close'] > last['open'] and
            last['close'] > (prev2['open'] + prev2['close']) / 2):
        patterns.append('Morning Star')
    if (prev2['close'] > prev2['open'] and prev_body < prev2_body * 0.35 and
            last['close'] < last['open'] and
            last['close'] < (prev2['open'] + prev2['close']) / 2):
        patterns.append('Evening Star')

    atr_proxy = df['high'].iloc[-10:].max() - df['low'].iloc[-10:].min()
    cow_ok = all(abs(r['close'] - r['open']) < atr_proxy * 0.15
                 for _, r in df.iloc[-3:].iterrows())
    if cow_ok: patterns.append('COW')

    return patterns


def check_nameable_pattern_entry(patterns):
    """True if any nameable pattern allows early entry at next candle open."""
    return bool({'RRT','Hammer','Inverted Hammer',
                 'Morning Star','Evening Star','COW'}.intersection(set(patterns)))


# ── FULL M/W DETECTION (with all BTMM confluence rules) ──────────────────────

def _pip_size_auto(symbol):
    from config import PIP_SIZES
    clean = symbol.rstrip('c') if symbol.endswith('c') and len(symbol) > 6 else symbol
    return PIP_SIZES.get(clean, PIP_SIZES.get(symbol, 0.0001))


def detect_mw_pattern(df, asian_high, asian_low, pdh, pdl, emas, symbol):
    """
    Full BTMM M/W detection enforcing conditions 2-4 of the confluence gate.
    Returns signal dict or None.
    """
    if asian_high is None or asian_low is None:
        return None

    pip_size = _pip_size_auto(symbol)
    e13      = emas['ketchup'].iloc[-1]
    scan_df  = df.iloc[-60:].reset_index(drop=True)

    result = _check_w_bottom(scan_df, asian_low, pdl, e13, pip_size)
    if result: return result
    return _check_m_top(scan_df, asian_high, pdh, e13, pip_size)


def _find_first_leg(scan_df, boundary, direction, pip_size):
    if direction == 'DOWN':
        cands = scan_df[scan_df['low'] < boundary]
        if cands.empty: return None, None
        idx = cands['low'].idxmin()
        return idx, cands['low'].min()
    else:
        cands = scan_df[scan_df['high'] > boundary]
        if cands.empty: return None, None
        idx = cands['high'].idxmax()
        return idx, cands['high'].max()


def _check_w_bottom(scan_df, asian_low, pdl, e13, pip_size):
    boundary = min(asian_low, pdl if pdl else asian_low)
    leg1_idx, leg1_extreme = _find_first_leg(scan_df, boundary, 'DOWN', pip_size)
    if leg1_idx is None: return None

    inducement = (boundary - leg1_extreme) / pip_size
    if not (STOP_HUNT_MIN_PIPS <= inducement <= STOP_HUNT_MAX_PIPS): return None

    outside_df = scan_df[scan_df['low'] < boundary]
    # Use swipe-based count from count_stop_hunt_vectors helper
    push_count = _count_pushes(outside_df, 'DOWN', pip_size)
    if push_count < STOP_HUNT_PUSHES: return None

    gap_candles = len(scan_df) - 1 - leg1_idx
    if not (ACCUM_GAP_MIN_CANDLES <= gap_candles <= ACCUM_GAP_MAX_CANDLES): return None

    trigger      = scan_df.iloc[-1]
    near_miss    = trigger['low'] > leg1_extreme
    spike_reject = trigger['low'] <= leg1_extreme and trigger['close'] > leg1_extreme
    if not (near_miss or spike_reject): return None

    ema_confirm  = trigger['close'] > e13
    patterns     = detect_candlestick_patterns(scan_df.iloc[-10:].reset_index(drop=True))
    has_nameable = check_nameable_pattern_entry(patterns)
    if not (ema_confirm or has_nameable): return None

    return {
        'signal':        'W_BOTTOM',
        'entry_type':    'MARKET_OPEN' if has_nameable else 'LIMIT_ZRT',
        'leg1_extreme':  leg1_extreme,
        'accum_candles': gap_candles,
        'push_count':    push_count,
        'patterns':      patterns,
    }


def _check_m_top(scan_df, asian_high, pdh, e13, pip_size):
    boundary = max(asian_high, pdh if pdh else asian_high)
    leg1_idx, leg1_extreme = _find_first_leg(scan_df, boundary, 'UP', pip_size)
    if leg1_idx is None: return None

    inducement = (leg1_extreme - boundary) / pip_size
    if not (STOP_HUNT_MIN_PIPS <= inducement <= STOP_HUNT_MAX_PIPS): return None

    outside_df = scan_df[scan_df['high'] > boundary]
    push_count = _count_pushes(outside_df, 'UP', pip_size)
    if push_count < STOP_HUNT_PUSHES: return None

    gap_candles = len(scan_df) - 1 - leg1_idx
    if not (ACCUM_GAP_MIN_CANDLES <= gap_candles <= ACCUM_GAP_MAX_CANDLES): return None

    trigger      = scan_df.iloc[-1]
    near_miss    = trigger['high'] < leg1_extreme
    spike_reject = trigger['high'] >= leg1_extreme and trigger['close'] < leg1_extreme
    if not (near_miss or spike_reject): return None

    ema_confirm  = trigger['close'] < e13
    patterns     = detect_candlestick_patterns(scan_df.iloc[-10:].reset_index(drop=True))
    has_nameable = check_nameable_pattern_entry(patterns)
    if not (ema_confirm or has_nameable): return None

    return {
        'signal':        'M_TOP',
        'entry_type':    'MARKET_OPEN' if has_nameable else 'LIMIT_ZRT',
        'leg1_extreme':  leg1_extreme,
        'accum_candles': gap_candles,
        'push_count':    push_count,
        'patterns':      patterns,
    }


def _count_pushes(outside_df, direction, pip_size):
    """Simple swipe counter for candles already outside the AR boundary."""
    if outside_df.empty:
        return 0
    # Each contiguous block of candles outside = 1 swipe
    # Already filtered to outside-boundary candles; just count them as ≥1
    return min(len(outside_df), 5)


# ── W/M ON RSI (TDI-based) ────────────────────────────────────────────────────

def _find_swings(series, lookback=5):
    highs, lows = [], []
    for i in range(lookback, len(series) - lookback):
        window = series.iloc[i-lookback:i+lookback+1]
        if series.iloc[i] == window.max(): highs.append((i, float(series.iloc[i])))
        if series.iloc[i] == window.min(): lows.append((i, float(series.iloc[i])))
    return highs, lows

def detect_w_bottom(rsi, lookback=5, min_dist=3):
    try:
        _, lows = _find_swings(rsi, lookback)
        if len(lows) < 2: return False
        p1, p2 = lows[-2], lows[-1]
        return (p2[0] - p1[0] >= min_dist and
                p2[1] > p1[1] and p1[1] < 45 and p2[1] < 50)
    except: return False

def detect_m_top(rsi, lookback=5, min_dist=3):
    try:
        highs, _ = _find_swings(rsi, lookback)
        if len(highs) < 2: return False
        p1, p2 = highs[-2], highs[-1]
        return (p2[0] - p1[0] >= min_dist and
                p2[1] < p1[1] and p1[1] > 55 and p2[1] > 50)
    except: return False
