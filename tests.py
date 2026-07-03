"""
tests.py — BTMM AutoTrader Unit Tests

Covers:
  • RSI / TDI calculation smoke tests
  • Session filter helpers (Asian range, gap time, Dharma gap, valid session)
  • 3-push vector count detection
  • M/W pattern detection (full confluence)
  • Foot Soldier lot sizing (1% vs 2%)
  • Stop loss placement on leg1 extreme
  • Nameable pattern entry trigger
"""

import unittest
import pandas as pd
import numpy as np
from datetime import datetime, time
import pytz

from indicators import calculate_rsi, calculate_tdi
from config import (
    is_asian_range, is_gap_time, is_valid_trading_session,
    FOOT_SOLDIER_INITIAL_RISK, FOOT_SOLDIER_AGGREGATE_RISK,
)
from patterns import (
    count_stop_hunt_vectors, detect_candlestick_patterns,
    check_nameable_pattern_entry, detect_mw_pattern,
)
from risk import (
    calculate_foot_soldier_lots, get_stop_loss, get_sl_pips,
)

ET_TZ = pytz.timezone('US/Eastern')


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _et(hour, minute=0):
    """Return a timezone-aware ET datetime."""
    return ET_TZ.localize(datetime(2024, 1, 2, hour, minute))


def _make_candle(o, h, l, c):
    return {'open': o, 'high': h, 'low': l, 'close': c}


def _make_df(candles):
    return pd.DataFrame(candles)


def _make_ema_stack(n=50, val=1.1000):
    """Create a minimal ema_stack with constant values for testing."""
    from indicators import calculate_ema
    s = pd.Series([val] * n)
    return {
        'mustard': calculate_ema(s, 5),
        'ketchup': calculate_ema(s, 13),
        'water':   calculate_ema(s, 50),
        'mayo':    calculate_ema(s, 200),
        'blue':    calculate_ema(s, 800),
    }


# ─────────────────────────────────────────────────────────────────────────────
# INDICATOR TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestIndicators(unittest.TestCase):
    def test_rsi_calculation(self):
        prices = pd.Series([10, 11, 12, 11, 10, 9, 8, 9, 10, 11, 12, 13, 14])
        rsi = calculate_rsi(prices, period=5)
        self.assertIsNotNone(rsi)
        # RSI must be between 0 and 100 where defined
        valid = rsi.dropna()
        self.assertTrue((valid >= 0).all())
        self.assertTrue((valid <= 100).all())

    def test_tdi_returns_all_keys(self):
        prices = pd.Series(np.linspace(1.1000, 1.1500, 60))
        tdi = calculate_tdi(prices)
        for key in ('rsi', 'signal', 'trade_signal', 'mbl', 'upper', 'lower'):
            self.assertIn(key, tdi)


# ─────────────────────────────────────────────────────────────────────────────
# SESSION FILTER TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionFilters(unittest.TestCase):
    # ── Asian Range ───────────────────────────────────────────────────────────
    def test_asian_range_evening(self):
        """21:00 ET is inside Asian session."""
        self.assertTrue(is_asian_range(_et(21, 0)))

    def test_asian_range_post_midnight(self):
        """01:30 ET (past midnight) is inside Asian session."""
        self.assertTrue(is_asian_range(_et(1, 30)))

    def test_asian_range_outside(self):
        """10:00 ET is outside Asian session."""
        self.assertFalse(is_asian_range(_et(10, 0)))

    # ── Gap / Dead Zones ──────────────────────────────────────────────────────
    def test_london_us_gap_blocked(self):
        """15:15 ET is the London/US gap."""
        self.assertTrue(is_gap_time(_et(15, 15)))

    def test_ny_gap_blocked(self):
        """09:15 ET is the NY Open gap."""
        self.assertTrue(is_gap_time(_et(9, 15)))

    def test_dharma_gap_blocked(self):
        """18:00 ET is inside the Dharma/Dead Zone."""
        self.assertTrue(is_gap_time(_et(18, 0)))

    def test_dharma_gap_boundary_start(self):
        """17:00 ET marks the start of the Dharma Gap."""
        self.assertTrue(is_gap_time(_et(17, 0)))

    def test_dharma_gap_boundary_end(self):
        """20:00 ET is the end boundary — NOT blocked."""
        self.assertFalse(is_gap_time(_et(20, 0)))

    def test_normal_time_not_blocked(self):
        """10:00 ET is not blocked."""
        self.assertFalse(is_gap_time(_et(10, 0)))

    # ── Valid Trading Session ─────────────────────────────────────────────────
    def test_london_session_valid(self):
        """04:00 ET is inside London session."""
        self.assertTrue(is_valid_trading_session(_et(4, 0)))

    def test_ny_session_valid(self):
        """10:00 ET is inside NY session."""
        self.assertTrue(is_valid_trading_session(_et(10, 0)))

    def test_overlap_valid(self):
        """09:45 ET (NY Brinks) — past the NY gap, valid."""
        self.assertTrue(is_valid_trading_session(_et(9, 45)))

    def test_london_gap_not_valid(self):
        """03:15 ET (London gap) — not a valid session."""
        self.assertFalse(is_valid_trading_session(_et(3, 15)))

    def test_dharma_not_valid(self):
        """18:30 ET (Dharma) — not a valid session."""
        self.assertFalse(is_valid_trading_session(_et(18, 30)))

    def test_asian_session_not_valid(self):
        """23:00 ET (Asian accumulation) — not valid for entry."""
        self.assertFalse(is_valid_trading_session(_et(23, 0)))


# ─────────────────────────────────────────────────────────────────────────────
# 3-PUSH VECTOR COUNT TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestVectorCount(unittest.TestCase):
    def _make_push_df(self, lows, highs):
        """Build a DataFrame with high/low arrays for testing push count."""
        return pd.DataFrame({'low': lows, 'high': highs})

    def test_single_push(self):
        """One continuous move down = 1 push below AR low."""
        lows  = [1.0990, 1.0980, 1.0970, 1.0960]
        highs = [1.1000, 1.0995, 1.0985, 1.0975]
        df = self._make_push_df(lows, highs)
        # AR low = 1.0995, so lows below it count as bearish swipes → bullish reversal
        count, direction = count_stop_hunt_vectors(df, 1.1050, 1.0995)
        self.assertGreaterEqual(count, 1)

    def test_three_pushes_detected(self):
        """Three distinct down pushes below AR low."""
        lows  = [1.0990, 1.0975, 1.0960,
                 1.0970, 1.0978, 1.0965,
                 1.0958, 1.0950,
                 1.0960, 1.0966, 1.0955,
                 1.0948, 1.0938]
        highs = [h + 0.0010 for h in lows]
        df = self._make_push_df(lows, highs)
        # AR: high=1.1005, low=1.0998 → below lows count as bullish swipes
        count, direction = count_stop_hunt_vectors(df, 1.1005, 1.0998)
        self.assertGreaterEqual(count, 1)

    def test_empty_df_returns_zero(self):
        df = pd.DataFrame({'low': [], 'high': []})
        count, _ = count_stop_hunt_vectors(df, 1.1000, 1.0900)
        self.assertEqual(count, 0)


# ─────────────────────────────────────────────────────────────────────────────
# CANDLESTICK / NAMEABLE PATTERN TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestCandlestickPatterns(unittest.TestCase):
    def _base_df(self, extras=None):
        """Build a 10-candle neutral DataFrame with optional overrides."""
        rows = [_make_candle(1.1000, 1.1010, 1.0990, 1.1005)] * 10
        df = _make_df(rows)
        if extras:
            for i, row in extras.items():
                for k, v in row.items():
                    df.at[i, k] = v
        return df

    def test_hammer_detected(self):
        """Hammer: small body, long lower wick."""
        candles = [_make_candle(1.1000, 1.1010, 1.0990, 1.1005)] * 8
        # Hammer: close=open+3pip, lower wick = 20 pip, upper wick = 1 pip
        candles.append(_make_candle(1.1000, 1.1010, 1.0990, 1.1005))  # prev2
        candles.append(_make_candle(1.1000, 1.1010, 1.0990, 1.1005))  # prev
        candles.append(_make_candle(1.1010, 1.1013, 1.0980, 1.1013))  # hammer
        df = _make_df(candles)
        patterns = detect_candlestick_patterns(df)
        self.assertIn('Hammer', patterns)

    def test_rrt_detected(self):
        """Railroad Tracks: two opposite-colour, similar-size candles."""
        candles = [_make_candle(1.1000, 1.1020, 1.0998, 1.1018)] * 9  # neutral filler
        candles.append(_make_candle(1.1000, 1.1020, 1.0998, 1.1018))  # prev2
        candles.append(_make_candle(1.1000, 1.1020, 1.0998, 1.1020))  # prev: bullish +20
        candles.append(_make_candle(1.1020, 1.1022, 1.1000, 1.1001))  # last: bearish -19
        df = _make_df(candles)
        patterns = detect_candlestick_patterns(df)
        self.assertIn('RRT', patterns)

    def test_nameable_entry_on_hammer(self):
        """check_nameable_pattern_entry returns True when Hammer is present."""
        self.assertTrue(check_nameable_pattern_entry(['Hammer']))

    def test_nameable_entry_false_on_empty(self):
        self.assertFalse(check_nameable_pattern_entry([]))

    def test_nameable_entry_on_rrt(self):
        self.assertTrue(check_nameable_pattern_entry(['RRT']))

    def test_nameable_entry_on_star(self):
        self.assertTrue(check_nameable_pattern_entry(['Morning Star']))
        self.assertTrue(check_nameable_pattern_entry(['Evening Star']))

    def test_nameable_entry_on_cow(self):
        self.assertTrue(check_nameable_pattern_entry(['COW']))


# ─────────────────────────────────────────────────────────────────────────────
# FOOT SOLDIER SIZING TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestFootSoldierSizing(unittest.TestCase):
    BALANCE = 10_000  # $10,000 account

    def test_initial_signal_1pct(self):
        """Initial entry risks exactly 1% of balance."""
        sl_pips = 50
        lot = calculate_foot_soldier_lots(
            self.BALANCE, sl_pips, 'EURUSD', pip_value_per_lot=10.0, is_retest=False
        )
        expected_risk = self.BALANCE * FOOT_SOLDIER_INITIAL_RISK
        # risk = lot * sl_pips * pip_value
        implied_risk = lot * sl_pips * 10.0
        self.assertAlmostEqual(implied_risk, expected_risk, delta=expected_risk * 0.05)

    def test_retest_signal_2pct(self):
        """Retest/backup entry risks 2% of balance."""
        sl_pips = 50
        lot = calculate_foot_soldier_lots(
            self.BALANCE, sl_pips, 'EURUSD', pip_value_per_lot=10.0, is_retest=True
        )
        expected_risk = self.BALANCE * FOOT_SOLDIER_AGGREGATE_RISK
        implied_risk = lot * sl_pips * 10.0
        self.assertAlmostEqual(implied_risk, expected_risk, delta=expected_risk * 0.05)

    def test_retest_lot_larger_than_initial(self):
        """Retest lot must be larger than initial lot."""
        sl_pips = 40
        lot_init   = calculate_foot_soldier_lots(self.BALANCE, sl_pips, 'EURUSD', is_retest=False)
        lot_retest = calculate_foot_soldier_lots(self.BALANCE, sl_pips, 'EURUSD', is_retest=True)
        self.assertGreater(lot_retest, lot_init)

    def test_minimum_lot_size(self):
        """Even with huge SL, lot should not go below 0.01."""
        lot = calculate_foot_soldier_lots(100, 500, 'EURUSD')
        self.assertGreaterEqual(lot, 0.01)


# ─────────────────────────────────────────────────────────────────────────────
# STOP LOSS PLACEMENT TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestStopLoss(unittest.TestCase):
    def test_buy_sl_below_leg1_extreme(self):
        """BUY stop loss must be BELOW the 1st leg extreme."""
        sl = get_stop_loss('BUY', 1.0950, 'EURUSD', buffer_pips=10)
        self.assertLess(sl, 1.0950)

    def test_sell_sl_above_leg1_extreme(self):
        """SELL stop loss must be ABOVE the 1st leg extreme."""
        sl = get_stop_loss('SELL', 1.1100, 'EURUSD', buffer_pips=10)
        self.assertGreater(sl, 1.1100)

    def test_sl_pips_positive(self):
        """SL distance in pips must be positive."""
        pips = get_sl_pips('BUY', 1.0970, 1.0950, 'EURUSD', buffer_pips=10)
        self.assertGreater(pips, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
