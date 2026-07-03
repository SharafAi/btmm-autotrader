"""
indicators.py — BTMM Indicators
Exact settings per Steve Mauro Blueprint:
  RSI:    period 13 (Wilder smoothing), applied to close
  Signal: SMA(7) of RSI — Red line (entry lock, mirrors 13 EMA on price)
  MBL:    SMA(34) of RSI — Yellow Market Baseline
  Bands:  BB(34, 1.618) — Volatility bands (Shark Fin zone)
  Levels: OVS=32, Mid=50, OVB=68

EMA Names (Steve Mauro):
  Mustard   =   5 EMA  (momentum — fastest)
  Ketchup   =  13 EMA  (signal/bellwether)
  Water     =  50 EMA  (intraday balance, TP1)
  Mayonnaise= 200 EMA  (home base, TP2)
  Blueberry = 800 EMA  (weekly anchor)
"""
import pandas as pd
import numpy as np

# ── TDI CONSTANTS ─────────────────────────────────────────────────────────────
RSI_PERIOD = 13    # Green line — RSI Price Line
BB_PERIOD  = 34    # Bollinger Bands period
BB_DEV     = 1.618 # Volatility band multiplier
SIGNAL_PER = 7     # Red Signal Line — SMA(7) of RSI (entry lock)
MBL_PERIOD = 34    # Yellow Market Baseline — SMA(34) of RSI
TDI_OVS    = 32
TDI_MID    = 50
TDI_OVB    = 68


# ─────────────────────────────────────────────────────────────────────────────
# RSI  (Wilder smoothing — same as MetaTrader default)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_rsi(closes, period=13):
    """RSI with proper Wilder exponential smoothing (not simple rolling mean)."""
    delta    = closes.diff()
    gain     = delta.where(delta > 0, 0.0).fillna(0)
    loss     = (-delta.where(delta < 0, 0.0)).fillna(0)

    # Seed with simple average for first window
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    # Apply Wilder smoothing from the first valid value onward
    for i in range(period, len(closes)):
        avg_gain.iat[i] = (avg_gain.iat[i-1] * (period - 1) + gain.iat[i]) / period
        avg_loss.iat[i] = (avg_loss.iat[i-1] * (period - 1) + loss.iat[i]) / period

    rs  = avg_gain / avg_loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return rsi


# ─────────────────────────────────────────────────────────────────────────────
# TDI  (full 3-line + band system)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_tdi(closes):
    """
    Full TDI per Steve Mauro blueprint — 3 lines + volatility bands:
      Green  = RSI(13)        — Price line (main signal)
      Red    = SMA(7) of RSI  — Signal line / entry lock (mirrors 13 EMA)
      Yellow = SMA(34) of RSI — Market Baseline (slow trend)
      Blue   = BB(34, 1.618)  — Volatility bands (Shark Fin zone)

    Extra signals computed:
      Shark Fin:    RSI was OUTSIDE band → snapped BACK INSIDE (2-leg signal)
      Blood in Water: RSI(green) crosses RED signal line
      MBL Cross:    RSI(green) crosses YELLOW market baseline
      Double Cross: RSI crosses BOTH red AND yellow simultaneously
    """
    rsi    = calculate_rsi(closes, RSI_PERIOD)
    mid    = rsi.rolling(BB_PERIOD).mean()
    std    = rsi.rolling(BB_PERIOD).std()
    upper  = mid + (BB_DEV * std)
    lower  = mid - (BB_DEV * std)
    signal = rsi.rolling(SIGNAL_PER).mean()   # Red Signal Line SMA(7)
    mbl    = rsi.rolling(MBL_PERIOD).mean()   # Yellow Market Baseline SMA(34)

    # ── SHARK FIN ─────────────────────────────────────────────────────────────
    # 1st leg: RSI breaks OUTSIDE the band (stop hunt)
    # 2nd leg: RSI snaps BACK INSIDE the band (entry trigger)
    # The snap-back IS the signal — not the breakout.
    shark_fin_buy = shark_fin_sell = False
    try:
        cur_rsi   = float(rsi.iloc[-1])
        cur_upper = float(upper.iloc[-1])
        cur_lower = float(lower.iloc[-1])
        cur_inside = cur_lower < cur_rsi < cur_upper

        if cur_inside:  # Currently back inside — check if recently outside
            lookback = rsi.iloc[-10:-1]
            up_band  = upper.iloc[-10:-1]
            low_band = lower.iloc[-10:-1]
            was_above = any(float(lookback.iat[i]) > float(up_band.iat[i])
                            for i in range(len(lookback)))
            was_below = any(float(lookback.iat[i]) < float(low_band.iat[i])
                            for i in range(len(lookback)))
            if was_below: shark_fin_buy  = True  # Was below → snapped back → BUY
            if was_above: shark_fin_sell = True   # Was above → snapped back → SELL
    except:
        pass

    # ── BLOOD IN WATER  (RSI green crosses RED signal line) ───────────────────
    try:
        blood_buy  = (float(rsi.iloc[-2]) < float(signal.iloc[-2]) and
                      float(rsi.iloc[-1]) > float(signal.iloc[-1]))
        blood_sell = (float(rsi.iloc[-2]) > float(signal.iloc[-2]) and
                      float(rsi.iloc[-1]) < float(signal.iloc[-1]))
    except:
        blood_buy = blood_sell = False

    # ── MBL CROSS  (RSI crosses YELLOW Market Baseline) ──────────────────────
    try:
        mbl_cross_up   = (float(rsi.iloc[-2]) < float(mbl.iloc[-2]) and
                          float(rsi.iloc[-1]) > float(mbl.iloc[-1]))
        mbl_cross_down = (float(rsi.iloc[-2]) > float(mbl.iloc[-2]) and
                          float(rsi.iloc[-1]) < float(mbl.iloc[-1]))
    except:
        mbl_cross_up = mbl_cross_down = False

    # RSI cross aliases (same as blood)
    rsi_cross_up   = blood_buy
    rsi_cross_down = blood_sell

    # ── DOUBLE CROSS  (RSI crosses BOTH Red + Yellow simultaneously) ──────────
    # Highest conviction signal per blueprint
    double_cross_up   = blood_buy  and mbl_cross_up
    double_cross_down = blood_sell and mbl_cross_down

    return {
        'rsi': rsi, 'signal': signal, 'trade_signal': signal, 'mbl': mbl,
        'upper': upper, 'lower': lower, 'mid': mid,
        # Shark Fin (snap-back confirmation)
        'shark_fin_buy':     shark_fin_buy,
        'shark_fin_sell':    shark_fin_sell,
        # Blood in Water (RSI × Red signal)
        'blood_buy':         blood_buy,
        'blood_sell':        blood_sell,
        # MBL cross (RSI × Yellow baseline)
        'mbl_cross_up':      mbl_cross_up,
        'mbl_cross_down':    mbl_cross_down,
        # Aliases
        'rsi_cross_up':      rsi_cross_up,
        'rsi_cross_down':    rsi_cross_down,
        # Double Cross (highest conviction)
        'double_cross_up':   double_cross_up,
        'double_cross_down': double_cross_down,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ATR  (True Range — proper OHLC-based)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_atr(highs, lows, closes, period=14):
    """True Average True Range using high/low/close."""
    tr1 = highs - lows
    tr2 = abs(highs - closes.shift())
    tr3 = abs(lows  - closes.shift())
    tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ─────────────────────────────────────────────────────────────────────────────
# EMA  (single + full stack)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calculate_all_emas(closes):
    """
    Steve Mauro EMA stack — full names + numeric aliases + legacy keys.
    All keys return the same underlying EMA series.
    """
    e5   = calculate_ema(closes, 5)
    e13  = calculate_ema(closes, 13)
    e50  = calculate_ema(closes, 50)
    e200 = calculate_ema(closes, 200)
    e800 = calculate_ema(closes, 800)
    return {
        # Named (BTMM canonical)
        'mustard':   e5,
        'ketchup':   e13,
        'water':     e50,
        'mayo':      e200,
        'blueberry': e800,
        # Numeric aliases
        'ema5':   e5,
        'ema13':  e13,
        'ema50':  e50,
        'ema200': e200,
        'ema800': e800,
        # Legacy (used in config.py EMA_STACK)
        'blue':   e800,
    }


def get_ema_stack(closes):
    """Alias for calculate_all_emas — keeps backward compatibility."""
    return calculate_all_emas(closes)


# ─────────────────────────────────────────────────────────────────────────────
# ADR  (Average Daily Range — 15-day rolling on daily candles)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_adr(high, low, period=15):
    """
    Average Daily Range over `period` days.
    Pass DAILY high/low series for accurate calculation.
    For intraday candles, this returns an intraday approximation.
    """
    daily_range = high - low
    return daily_range.rolling(window=period).mean()


# ─────────────────────────────────────────────────────────────────────────────
# VOLUME TREND
# ─────────────────────────────────────────────────────────────────────────────

def calculate_volume_trend(volumes, period=10):
    """Returns 'high', 'low', or 'normal' relative to recent average."""
    try:
        if volumes is None or len(volumes) < period:
            return 'unknown'
        avg  = volumes.iloc[-period:].mean()
        last = volumes.iloc[-1]
        if last > avg * 1.5: return 'high'
        if last < avg * 0.5: return 'low'
        return 'normal'
    except:
        return 'unknown'
