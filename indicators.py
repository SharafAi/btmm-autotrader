import pandas as pd
import numpy as np

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calculate_rsi(series, period=13):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_tdi(series):
    rsi = calculate_rsi(series, 13)
    # Market Baseline (Yellow) - usually 34 period SMA of RSI
    mbl = rsi.rolling(window=34).mean()
    # Volatility Bands (Blue) - usually 34 period StdDev around MBL
    std = rsi.rolling(window=34).std()
    upper = mbl + (std * 1.618)
    lower = mbl - (std * 1.618)
    # RSI Signal (Green) - 2 period SMA of RSI
    signal = rsi.rolling(window=2).mean()
    # Trade Signal (Red) - 7 period SMA of RSI
    trade_signal = rsi.rolling(window=7).mean()
    
    return {
        'rsi': rsi,
        'signal': signal,
        'trade_signal': trade_signal,
        'mbl': mbl,
        'upper': upper,
        'lower': lower
    }

def calculate_adr(high, low, period=15):
    daily_range = high - low
    return daily_range.rolling(window=period).mean()

def get_ema_stack(closes):
    from config import EMA_STACK
    return {k: calculate_ema(closes, v) for k, v in EMA_STACK.items()}
