from datetime import datetime, time
import pytz

# --- API CREDENTIALS ---
TOKEN = 'eyJhbGciOiJSUzUxMiIsInR5cCI6IkpXVCJ9.eyJfaWQiOiJjNGZkOGJkMjIxNGVjNTg0NTYyNzU0YmE4ZGJlZjBiMCIsImFjY2Vzc1J1bGVzIjpbeyJpZCI6InRyYWRpbmctYWNjb3VudC1tYW5hZ2VtZW50LWFwaSIsIm1ldGhvZHMiOlsidHJhZGluZy1hY2NvdW50LW1hbmFnZW1lbnQtYXBpOnJlc3Q6cHVibGljOio6KiJdLCJyb2xlcyI6WyJyZWFkZXIiLCJ3cml0ZXIiXSwicmVzb3VyY2VzIjpbIio6JFVTRVJfSUQkOioiXX0seyJpZCI6Im1ldGFhcGktcmVzdC1hcGkiLCJtZXRob2RzIjpbIm1ldGFhcGktYXBpOnJlc3Q6cHVibGljOio6KiJdLCJyb2xlcyI6WyJyZWFkZXIiLCJ3cml0ZXIiXSwicmVzb3VyY2VzIjpbIio6JFVTRVJfSUQkOioiXX0seyJpZCI6Im1ldGFhcGktcnBjLWFwaSIsIm1ldGhvZHMiOlsibWV0YWFwaS1hcGk6d3M6cHVibGljOio6KiJdLCJyb2xlcyI6WyJyZWFkZXIiLCJ3cml0ZXIiXSwicmVzb3VyY2VzIjpbIio6JFVTRVJfSUQkOioiXX0seyJpZCI6Im1ldGFhcGktcmVhbC10aW1lLXN0cmVhbWluZy1hcGkiLCJtZXRob2RzIjpbIm1ldGFhcGktYXBpOndzOnB1YmxpYzoqOioiXSwicm9sZXMiOlsicmVhZGVyIiwid3JpdGVyIl0sInJlc291cmNlcyI6WyIqOiRVU0VSX0lEJDoqIl19LHsiaWQiOiJtZXRhc3RhdHMtYXBpIiwibWV0aG9kcyI6WyJtZXRhc3RhdHMtYXBpOnJlc3Q6cHVibGljOio6KiJdLCJyb2xlcyI6WyJyZWFkZXIiLCJ3cml0ZXIiXSwicmVzb3VyY2VzIjpbIio6JFVTRVJfSUQkOioiXX0seyJpZCI6InJpc2stbWFuYWdlbWVudC1hcGkiLCJtZXRob2RzIjpbInJpc2stbWFuYWdlbWVudC1hcGk6cmVzdDpwdWJsaWM6KjoqIl0sInJvbGVzIjpbInJlYWRlciIsIndyaXRlciJdLCJyZXNvdXJjZXMiOlsiKjokVVNFUl9JRCQ6KiJdfSx7ImlkIjoiY29weWZhY3RvcnktYXBpIiwibWV0aG9kcyI6WyJjb3B5ZmFjdG9yeS1hcGk6cmVzdDpwdWJsaWM6KjoqIl0sInJvbGVzIjpbInJlYWRlciIsIndyaXRlciJdLCJyZXNvdXJjZXMiOlsiKjokVVNFUl9JRCQ6KiJdfSx7ImlkIjoibXQtbWFuYWdlbWVudC1hcGkiLCJtZXRob2RzIjpbIm10LW1hbmFnZXItYXBpOnJlc3Q6ZGVhbGluZzoqOioiLCJtdC1tYW5hZ2VyLWFwaTpyZXN0OnB1YmxpYzoqOioiXSwicm9sZXMiOlsicmVhZGVyIiwid3JpdGVyIl0sInJlc291cmNlcyI6WyIqOiRVU0VSX0lEJDoqIl19LHsiaWQiOiJiaWxsaW5nLWFwaSIsIm1ldGhvZHMiOlsiYmlsbGluZy1hcGk6cmVzdDpwdWJsaWM6KjoqIl0sInJvbGVzIjpbInJlYWRlciJdLCJyZXNvdXJjZXMiOlsiKjokVVNFUl9JRCQ6KiJdfV0sImlnbm9yZVJhdGVMaW1pdHMiOmZhbHNlLCJ0b2tlbklkIjoiMjAyMTAyMTMiLCJpbXBlcnNvbmF0ZWQiOmZhbHNlLCJyZWFsVXNlcklkIjoiYzRmZDhiZDIyMTRlYzU4NDU2Mjc1NGJhOGRiZWYwYjAiLCJpYXQiOjE3Nzg5NTE5NTl9.W-4Wq0Md2nHOMPBL4wyYlb_e9q9dmE72EFK8G82EbkY-U8vOcpE-lNDJmot37VqNsjBbzIu6lEnSA9mFKYoVk1g2XV51z-wdoV48e2uoBPjC2Tr30d_Hd8m-uzZhtY7pCr38khi6iH5ih1n192SQHGn6PH9CywhRx3JuvyPrdx_PZ7aZBVFe8xpO0RQF3yKrkjIH6V0of3CmDzu-AREMBbpePEikP_8A9sljHOOC32ELOTDZfzFkkyobC-PNagY2rTML8j6jlNkVkuqJHn3rbwK9Xr2ebCAqIJMRxRGazGVoiPBBPI9Qkjh1tifoNFhowDNmI6K7WPIOHikBBL0mm3h7-N-FZOcqeyF6SJiDfyzYOT9R2UwE9pkXmtpjwvb-2S8ioSD8GL5u9olkxR0tWVFXtRY-V0cNbXM1AUfnrqRSra9en5A8zvICKpJoMDQQp6CIpsFBkeDXdWtrHkJPNESqMEkVsoiQ4b_FGCKlx8gidGiMT2Quw5eg4O2wolwgJJC4LJeYM8xqHL8kq8tBXs4u9K_sAv6WJF1CA9yEyn7_oLkJUEsl1YHyoEJyoC0KzZXHepD9yluOn43raGfS2KD3Bsu5wDtMWvBXgaQ3h298OzS5pYvolJeMyt830Dc45vf_FAcFd2nHvvMu7qziCMB9KZT7R8lXnKbfqPM0G_M'
ACCOUNT_ID = '2bc74aed-3fa5-4b4b-a9b6-18b526cac7b1'

# --- TIME & SESSION MANAGEMENT ---
ET_TZ = pytz.timezone('US/Eastern')

# ── Tokyo Channel (Asian Range) ──────────────────────────────────────────────
ASIAN_START    = time(20, 30)
ASIAN_END      = time(3, 0)
ASIAN_MAX_PIPS = 50           # Range must be ≤ 50 pips or PASS

# ── Stop Hunt Parameters ─────────────────────────────────────────────────────
STOP_HUNT_MIN_PIPS = 25       # Min extension outside Asian Range
STOP_HUNT_MAX_PIPS = 50       # Max extension outside Asian Range
STOP_HUNT_PUSHES   = 3        # Required distinct vector pushes (swipes)

# ── M/W Accumulation Gap (candles between 1st and 2nd leg on 15m TF) ─────────
ACCUM_GAP_MIN_CANDLES = 2     # 30 min minimum
ACCUM_GAP_MAX_CANDLES = 8     # 2-hour extended max (ideal ≤ 6)

# ── Blocked / Dead Zones — no new entries ────────────────────────────────────
LONDON_GAP_START = time(3, 0)
LONDON_GAP_END   = time(3, 30)
NY_GAP_START     = time(9, 0)
NY_GAP_END       = time(9, 30)
DHARMA_GAP_START = time(17, 0)   # Dharma / Dead Zone start
DHARMA_GAP_END   = time(20, 0)   # Dharma / Dead Zone end

# ── Brinks Trigger Windows (favoured entry times) ────────────────────────────
LONDON_BRINKS = time(3, 45)
NY_BRINKS     = time(9, 45)

# ── Valid Trading Sessions ────────────────────────────────────────────────────
LONDON_SESSION_START = time(3, 30)
LONDON_SESSION_END   = time(12, 0)
NY_SESSION_START     = time(8, 0)
NY_SESSION_END       = time(17, 0)

# ── Daily Reset ──────────────────────────────────────────────────────────────
DAILY_RESET_TIME = time(17, 0)

# --- TECHNICAL GRID (EMAs) ---
EMA_STACK = {
    'mustard': 5,
    'ketchup': 13,
    'water':   50,
    'mayo':    200,
    'blue':    800,
}

# --- RISK MANAGEMENT (Foot Soldier strategy) ---------------------------------
# Initial signal: 1% risk. Backed up 2% aggregate on confirmed retest.
FOOT_SOLDIER_INITIAL_RISK   = 0.01
FOOT_SOLDIER_AGGREGATE_RISK = 0.02
MAX_RISK_PER_TRADE          = 0.02   # Hard ceiling per order
MIN_RISK_PER_TRADE          = 0.01   # Hard floor per order
TWO_HOUR_RULE_MINS          = 120

# --- SYMBOLS ---
SYMBOLS = [
    'EURUSD', 'GBPUSD', 'XAUUSD',
    'USDJPY', 'AUDUSD', 'USDCAD',
    'EURJPY', 'GBPJPY',
]

# --- PIP CONFIGURATION ---
PIP_SIZES = {
    'EURUSD': 0.0001,
    'GBPUSD': 0.0001,
    'USDJPY': 0.01,
    'EURJPY': 0.01,
    'GBPJPY': 0.01,
    'AUDUSD': 0.0001,
    'USDCAD': 0.0001,
    'XAUUSD': 0.1,
}

# ─────────────────────────────────────────────────────────────────────────────
# SESSION / TIME HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_current_et():
    """Return the current wall-clock time in US/Eastern timezone."""
    return datetime.now(ET_TZ)


def is_asian_range(dt):
    """True if dt falls inside the Asian (Tokyo Channel) accumulation window.
    The window crosses midnight: 20:30 ET → 03:00 ET next day."""
    t = dt.time()
    return t >= ASIAN_START or t < ASIAN_END


def is_gap_time(dt):
    """
    True if dt falls inside ANY blocked dead-zone window:
      • London Open Gap  03:00 – 03:30 ET
      • NY Open Gap      09:00 – 09:30 ET
      • Dharma/Dead Zone 17:00 – 20:00 ET
    No new entries may be placed during these windows.
    """
    t = dt.time()
    if LONDON_GAP_START <= t < LONDON_GAP_END:
        return True
    if NY_GAP_START <= t < NY_GAP_END:
        return True
    if DHARMA_GAP_START <= t < DHARMA_GAP_END:
        return True
    return False


def is_valid_trading_session(dt):
    """
    True only if dt is inside London (03:30–12:00 ET) or NY (08:00–17:00 ET)
    AND is not inside a gap/dead zone.
    This is condition #5 of the BTMM binary confluence gate.
    """
    if is_gap_time(dt):
        return False
    t = dt.time()
    in_london = LONDON_SESSION_START <= t < LONDON_SESSION_END
    in_ny     = NY_SESSION_START <= t < NY_SESSION_END
    return in_london or in_ny


def is_friday_exit(dt):
    """True on Fridays after 16:00 ET — flatten all positions before weekend."""
    return dt.weekday() == 4 and dt.hour >= 16
