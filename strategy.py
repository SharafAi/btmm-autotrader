"""
strategy.py — BTMM Signal Engine
Type 1 vs Type 2 W/M, Near Miss, Shift Candle, Straightaway, Hold Mayo,
Shadow Box, ADR exhaustion, Blue Tracer scoring, per-symbol tracking.
"""
import pandas as pd
import time as _time
from indicators import calculate_tdi, calculate_atr, calculate_all_emas
from patterns import (detect_m_top, detect_w_bottom, detect_manipulation,
                      detect_candlestick_confirmation, get_session_info,
                      is_btmm_session, detect_asian_range, count_stop_hunt_vectors,
                      get_prev_day_levels, get_session_high_low,
                      get_blue_tracer, is_near_waypoint, get_ny_time,
                      detect_mw_pattern)
from cycles import detect_cycle_level, get_cycle_emoji, get_day_of_week_note

_symbol_traded_today = {}
_first_leg_tracker   = {}   # {symbol: {time, direction, price, candle_idx}}

def _pip_size(symbol):
    s = symbol.rstrip('c') if symbol.endswith('c') and len(symbol) > 6 else symbol
    if 'JPY' in s: return 0.01
    if 'XAU' in s: return 0.1
    if 'BTC' in s or 'ETH' in s: return 1.0
    return 0.0001

def _reset_symbol_tracking():
    ny  = get_ny_time()
    key = str(ny.date())
    if _symbol_traded_today.get('_date') != key:
        _symbol_traded_today.clear(); _first_leg_tracker.clear()
        _symbol_traded_today['_date'] = key

def mark_symbol_traded(symbol, direction):
    _reset_symbol_tracking(); _symbol_traded_today[symbol] = direction

def symbol_already_traded(symbol):
    _reset_symbol_tracking(); return symbol in _symbol_traded_today

def _record_first_leg(symbol, direction, price, candle_idx):
    _first_leg_tracker[symbol] = {
        'time': _time.time(), 'direction': direction,
        'price': price, 'candle_idx': candle_idx}

def _check_accumulation_gap(symbol, current_candle_idx):
    if symbol not in _first_leg_tracker:
        return True, 0, 'no_1st_leg', 0
    leg     = _first_leg_tracker[symbol]
    elapsed = (_time.time() - leg['time']) / 60
    candles = current_candle_idx - leg['candle_idx']
    if elapsed < 30:   return False, elapsed, 'too_early', candles
    elif elapsed > 90: del _first_leg_tracker[symbol]; return True, elapsed, 'expired', candles
    return True, elapsed, 'valid', candles

def get_adr(candles_daily, period=15):
    try:
        import pytz; from datetime import datetime
        NY_TZ = pytz.timezone('America/New_York')
        df    = candles_daily.copy()
        times = pd.to_datetime(df['time'])
        if times.dt.tz is None: times = times.dt.tz_localize('UTC')
        df['ny_date'] = times.dt.tz_convert(NY_TZ).dt.date
        daily = df.groupby('ny_date').agg(high=('high','max'), low=('low','min')).reset_index()
        daily['range'] = daily['high'] - daily['low']
        return float(daily['range'].iloc[:-1].tail(period).mean())
    except: return None

def get_today_range_pips(candles_ltf, pip_size):
    try:
        import pytz
        NY_TZ = pytz.timezone('America/New_York')
        df    = candles_ltf.copy()
        times = pd.to_datetime(df['time'])
        if times.dt.tz is None: times = times.dt.tz_localize('UTC')
        df['ny_date'] = times.dt.tz_convert(NY_TZ).dt.date
        today   = get_ny_time().date()
        today_c = df[df['ny_date'] == today]
        if today_c.empty: today_c = df.tail(20)
        return (float(today_c['high'].max()) - float(today_c['low'].min())) / pip_size
    except: return 0

def analyze_shift_candle(candles, adr, pip_size):
    try:
        if not adr: return 'market', 0, 0
        last     = candles.iloc[-1]
        bar_pct  = (abs(float(last['high']) - float(last['low'])) / adr) * 100
        if bar_pct < 10:  return 'market',      0,  bar_pct
        elif bar_pct < 20: return 'pullback_25', 25, bar_pct
        else:              return 'pullback_50', 50, bar_pct
    except: return 'market', 0, 0

def classify_pattern_type(candles, emas, signal_type):
    try:
        ketchup = float(emas['ketchup'].iloc[-1])
        close   = float(candles['close'].iloc[-1])
        low     = float(candles['low'].iloc[-1])
        high    = float(candles['high'].iloc[-1])
        if signal_type == 'BUY':
            if close > ketchup: return 'type1'
            elif low <= ketchup and close < ketchup: return 'type2'
        else:
            if close < ketchup: return 'type1'
            elif high >= ketchup and close > ketchup: return 'type2'
        return 'none'
    except: return 'none'

def check_near_miss(candles, symbol, signal_type, pip_size, tol=5):
    try:
        if symbol not in _first_leg_tracker: return True, 0
        fp = _first_leg_tracker[symbol]['price']
        if signal_type == 'BUY':
            second_low = float(candles['low'].iloc[-3:].min())
            dist = abs(second_low - fp) / pip_size
            return dist <= tol and second_low > fp, dist
        else:
            second_high = float(candles['high'].iloc[-3:].max())
            dist = abs(second_high - fp) / pip_size
            return dist <= tol and second_high < fp, dist
    except: return True, 0

def detect_straightaway(candles, emas, signal_type):
    try:
        water = float(emas['water'].iloc[-1]); close = float(candles['close'].iloc[-1])
        last3 = candles.tail(3)
        bodies = [abs(float(r['close'])-float(r['open'])) for _,r in last3.iterrows()]
        ranges = [float(r['high'])-float(r['low']) for _,r in last3.iterrows()]
        is_cow = sum(bodies)/3 > sum(ranges)/3 * 0.5
        near   = abs(close - water) / water < 0.002
        if signal_type == 'BUY':  return is_cow and near and close > water
        else:                      return is_cow and near and close < water
    except: return False

def detect_hold_mayo(candles, emas, signal_type):
    try:
        mayo  = float(emas['mayo'].iloc[-1]); last = candles.iloc[-1]
        low   = float(last['low']); high = float(last['high']); close = float(last['close'])
        if signal_type == 'BUY':  return low <= mayo <= close
        else:                      return close <= mayo <= high
    except: return False

def is_shadow_box_window(session):
    ny = get_ny_time(); t = ny.hour * 60 + ny.minute
    def _t(h,m=0): return h*60+m
    return (_t(1) <= t < _t(3)) or (_t(8) <= t < _t(10)) or (_t(13) <= t < _t(15))

def get_ema_trend(closes):
    emas      = calculate_all_emas(closes); price = float(closes.iloc[-1])
    mustard   = float(emas['mustard'].iloc[-1]); ketchup   = float(emas['ketchup'].iloc[-1])
    water     = float(emas['water'].iloc[-1]);   mayo      = float(emas['mayo'].iloc[-1])
    blueberry = float(emas['blueberry'].iloc[-1])
    bull = sum([price>blueberry,price>mayo,price>water,price>ketchup,price>mustard,
                mustard>ketchup,ketchup>water,water>mayo])
    bear = sum([price<blueberry,price<mayo,price<water,price<ketchup,price<mustard,
                mustard<ketchup,ketchup<water,water<mayo])
    if price > blueberry and price > mayo:
        return 'bullish', 'strong' if bull>=6 else 'moderate', emas, bull
    if price < blueberry and price < mayo:
        return 'bearish', 'strong' if bear>=6 else 'moderate', emas, bear
    return 'neutral', 'none', emas, 0

def calculate_book_score(ar_valid, vector_count, second_leg_fails, shark_fin,
                         blood_in_water, price_near_mayo, safety_trade, level_3,
                         in_prime_window, blueberry_aligned,
                         strike_zone_valid=False, accum_gap_valid=False,
                         pattern_type='none', near_miss=False, shadow_box=False,
                         straightaway=False, hold_mayo=False):
    score=0; reasons=[]
    if ar_valid:          score+=2; reasons.append('AR<50p')
    if vector_count>=3:   score+=2; reasons.append(f'{vector_count}v')
    if second_leg_fails:  score+=3; reasons.append('2ndLeg')
    if shark_fin:         score+=3; reasons.append('🦈Shark')
    if blood_in_water:    score+=2; reasons.append('🩸Blood')
    if price_near_mayo:   score+=2; reasons.append('Mayo')
    if safety_trade:      score+=2; reasons.append('🛡️Safety')
    if level_3:           score+=3; reasons.append('🔴L3')
    if in_prime_window:   score+=1; reasons.append('⏰Prime')
    if blueberry_aligned: score+=2; reasons.append('🫐Berry')
    if strike_zone_valid: score+=2; reasons.append('🎯SZ')
    if accum_gap_valid:   score+=2; reasons.append('⏳Gap')
    if pattern_type=='type1': score+=3; reasons.append('T1✅')
    elif pattern_type=='type2': score+=1; reasons.append('T2⚠️')
    if near_miss:         score+=2; reasons.append('NearMiss')
    if shadow_box:        score+=1; reasons.append('ShadowBox')
    if straightaway:      score+=2; reasons.append('Straightaway')
    if hold_mayo:         score+=3; reasons.append('HoldMayo')
    return score, reasons

def check_entry(candles_ltf, candles_htf, symbol, mode='btmm', candles_daily=None):
    null = {'type':None,'atr':0,'reason':'','score':0,
            'session_high':None,'session_low':None,
            'emas_ltf':None,'cycle':None,'order_type':'market','pullback_pct':0}
    try:
        _reset_symbol_tracking()
        if symbol_already_traded(symbol):
            print(f"   [{symbol}] 📵 Already traded today"); return null

        closes_ltf = candles_ltf['close']; closes_htf = candles_htf['close']
        highs = candles_ltf['high'];       lows  = candles_ltf['low']
        tdi_ltf = calculate_tdi(closes_ltf); tdi_htf = calculate_tdi(closes_htf)
        atr = calculate_atr(highs, lows, closes_ltf).iloc[-1]
        adr = get_adr(candles_daily) if candles_daily is not None else get_adr(candles_htf)
        ema_trend_htf, ema_str_htf, emas_htf, _ = get_ema_trend(closes_htf)
        ema_trend_ltf, ema_str_ltf, emas_ltf, _ = get_ema_trend(closes_ltf)

        price     = float(closes_ltf.iloc[-1])
        mustard   = float(emas_ltf['mustard'].iloc[-1])
        ketchup   = float(emas_ltf['ketchup'].iloc[-1])
        water     = float(emas_ltf['water'].iloc[-1])
        mayo      = float(emas_ltf['mayo'].iloc[-1])
        blueberry = float(emas_ltf['blueberry'].iloc[-1])
        pip = _pip_size(symbol)

        cur_rsi = float(tdi_ltf['rsi'].iloc[-1])
        cur_mbl = float(tdi_ltf['mbl'].iloc[-1])
        cur_up  = float(tdi_ltf['upper'].iloc[-1])
        cur_low = float(tdi_ltf['lower'].iloc[-1])
        htf_rsi = float(tdi_htf['rsi'].iloc[-1])
        htf_mbl = float(tdi_htf['mbl'].iloc[-1])

        w_pattern    = detect_w_bottom(tdi_ltf['rsi'])
        m_pattern    = detect_m_top(tdi_ltf['rsi'])
        manipulation = detect_manipulation(candles_ltf)
        candle_conf  = detect_candlestick_confirmation(candles_ltf)
        session      = get_session_info()

        ar_h, ar_l, ar_pips, ar_valid = detect_asian_range(candles_ltf, symbol)
        if not ar_valid:
            print(f"   [{symbol}] ❌ AR invalid (>50p)"); return null
        vector_count, hunt_dir        = count_stop_hunt_vectors(candles_ltf, ar_h, ar_l)
        session_high, session_low     = get_session_high_low(candles_ltf)
        prev_high, prev_low           = get_prev_day_levels(candles_ltf)
        bt_high, bt_low, bt_sph, bt_spl = get_blue_tracer(candles_ltf)
        near_waypoint = is_near_waypoint(price, pip)

        today_range   = get_today_range_pips(candles_ltf, pip)
        adr_pips      = (adr / pip) if adr else 0
        adr_exhausted = adr_pips > 0 and today_range >= adr_pips
        if adr_exhausted:
            print(f"   [{symbol}] ⛔ ADR exhausted ({round(today_range,0)}/{round(adr_pips,0)}p)")

        sz_valid=False; sz_dir='none'; sz_pips=0
        if ar_h and ar_l:
            above_pips = (price - ar_h) / pip; below_pips = (ar_l - price) / pip
            if 25 <= above_pips <= 50:
                sz_valid=True; sz_dir='bearish'; sz_pips=above_pips
                if symbol not in _first_leg_tracker:
                    _record_first_leg(symbol, sz_dir, price, len(candles_ltf))
                    print(f"   [{symbol}] 🎯 1st Leg! bearish {round(sz_pips,1)}p outside AR")
            elif 25 <= below_pips <= 50:
                sz_valid=True; sz_dir='bullish'; sz_pips=below_pips
                if symbol not in _first_leg_tracker:
                    _record_first_leg(symbol, sz_dir, price, len(candles_ltf))
                    print(f"   [{symbol}] 🎯 1st Leg! bullish {round(sz_pips,1)}p outside AR")

        can_enter_gap, gap_mins, gap_status, gap_candles = \
            _check_accumulation_gap(symbol, len(candles_ltf))
        
        mw_signal = detect_mw_pattern(candles_ltf, ar_h, ar_l, prev_high, prev_low, emas_ltf, symbol)
        if mw_signal:
            order_type = 'market' if mw_signal['entry_type'] == 'MARKET_OPEN' else 'pullback_50'
            pullback_pct = 0 if order_type == 'market' else 50
        else:
            order_type, pullback_pct, shift_pct = analyze_shift_candle(candles_ltf, adr, pip)

        straightaway_buy  = detect_straightaway(candles_ltf, emas_ltf, 'BUY')
        straightaway_sell = detect_straightaway(candles_ltf, emas_ltf, 'SELL')
        mayo_buy          = detect_hold_mayo(candles_ltf, emas_ltf, 'BUY')
        mayo_sell         = detect_hold_mayo(candles_ltf, emas_ltf, 'SELL')

        try:
            rsis=tdi_ltf['rsi']; prices=closes_ltf.iloc[-10:]; h=5
            bullish_div = (float(prices.iloc[:h].min())>float(prices.iloc[h:].min()) and
                           float(rsis.iloc[:h].min())<float(rsis.iloc[h:].min()))
            bearish_div = (float(prices.iloc[:h].max())<float(prices.iloc[h:].max()) and
                           float(rsis.iloc[:h].max())>float(rsis.iloc[h:].max()))
        except: bullish_div=bearish_div=False

        cycle        = detect_cycle_level(candles_daily, candles_htf)
        day_name, day_note, day_num = get_day_of_week_note()
        shadow       = is_shadow_box_window(session)
        rsi_z        = 'OVB🔴' if cur_rsi>68 else 'OVS🟢' if cur_rsi<32 else 'MID🟡'

        print(f"\n  ┌─[{symbol}]── NY:{session['ny_time']} MV:{session['mv_time']}")
        print(f"  │ Price:{round(price,5):<10} K(13):{round(ketchup,5):<9} W(50):{round(water,5)}")
        print(f"  │ Mayo:{round(mayo,5):<11} Berry:{round(blueberry,5)}")
        print(f"  │ HTF:{ema_trend_htf.upper()} RSI:{round(cur_rsi,1)} {rsi_z}")
        print(f"  │ W:{'✅' if w_pattern else '—'} M:{'✅' if m_pattern else '—'} "
              f"Hunt:{hunt_dir.upper()}({vector_count}v) AR:{round(ar_pips,1)}p")
        print(f"  │ Shark:{'✅' if tdi_ltf['shark_fin_buy'] or tdi_ltf['shark_fin_sell'] else '—'} "
              f"Blood:{'✅' if tdi_ltf['blood_buy'] or tdi_ltf['blood_sell'] else '—'} "
              f"Gap:{gap_status}({round(gap_mins,0)}m) Order:{order_type}")
        print(f"  │ {get_cycle_emoji(cycle['level'])} L{cycle['level']}:{cycle['direction']} "
              f"📅 {day_name}: {day_note[:30]}")
        print(f"  └──────────────────────────────────────────────────────────")

        # ── GATES ────────────────────────────────────────────────────────────
        if session['is_friday_exit']:
            print(f"   [{symbol}] 🚫 Friday exit"); return null
        if not is_btmm_session():
            reason = ("Dharma" if session['is_dharma'] else
                      "Lull"   if session['is_lull']   else
                      "Gap"    if session['is_gap']    else "No Session")
            print(f"   [{symbol}] ⏸ {reason}"); return null
        if day_num == 0 and cycle['level'] < 2 and not cycle['divergence']:
            print(f"   [{symbol}] ⚠️ Monday L{cycle['level']} — skip"); return null
        if not can_enter_gap:
            print(f"   [{symbol}] ⏳ Accum gap wait ({round(gap_mins,1)}m)"); return null

        result = dict(null)
        result.update({'atr':atr,'emas_ltf':emas_ltf,'session_high':session_high,
                        'session_low':session_low,'cycle':cycle,
                        'order_type':order_type,'pullback_pct':pullback_pct})

        can_buy  = ema_trend_htf=='bullish' and htf_rsi>htf_mbl
        can_sell = ema_trend_htf=='bearish' and htf_rsi<htf_mbl
        if cycle['level']==3:
            if cycle['direction']=='bullish' and ema_trend_htf!='neutral': can_sell=True
            if cycle['direction']=='bearish' and ema_trend_htf!='neutral': can_buy=True
        if adr_exhausted:
            if can_buy  and cycle['level']<3: can_buy=False
            if can_sell and cycle['level']<3: can_sell=False
        ar_penalty = 0 if ar_valid else -2

        # ── BUY ──────────────────────────────────────────────────────────────
        buy_signal = mw_signal and mw_signal['signal'] == 'W_BOTTOM'
        if can_buy and buy_signal:
            pat_type  = classify_pattern_type(candles_ltf, emas_ltf, 'BUY')
            nm_ok, _  = check_near_miss(candles_ltf, symbol, 'BUY', pip)
            score, reasons = calculate_book_score(
                ar_valid, vector_count, w_pattern,
                tdi_ltf['shark_fin_buy'], tdi_ltf['blood_buy'],
                abs(price-mayo)<atr*3,
                price>water and cur_rsi>cur_mbl and tdi_ltf['blood_buy'],
                cur_rsi<cur_low, session['is_primary'], price>blueberry,
                strike_zone_valid=(sz_valid and sz_dir=='bullish'),
                accum_gap_valid=(gap_status=='valid'),
                pattern_type=pat_type, near_miss=nm_ok,
                shadow_box=shadow, straightaway=straightaway_buy, hold_mayo=mayo_buy)
            if ema_str_htf=='strong':                  score+=1; reasons.append('StrongHTF')
            if manipulation=='bullish':                score+=2; reasons.append('🎯StopHunt')
            if session['is_brinks']:                   score+=2; reasons.append('⏰Brinks')
            if candle_conf=='hammer':                  score+=1; reasons.append('🔨Hammer')
            if candle_conf=='railroad_tracks':         score+=2; reasons.append('🛤️RRT')
            if tdi_ltf['double_cross_up']:             score+=3; reasons.append('💥DoubleCross')
            elif tdi_ltf['rsi_cross_up']:              score+=1; reasons.append('RSI×↑')
            if tdi_ltf['mbl_cross_up']:                score+=1; reasons.append('MBL×↑')
            if bullish_div:                            score+=2; reasons.append('📈Div')
            if cycle['level']==3:                      score+=2; reasons.append('L3Rev')
            if cycle.get('is_33_trade'):               score+=3; reasons.append('🎰33Trade')
            if cycle.get('is_reset'):                  score+=2; reasons.append('🔄Reset')
            if bt_spl:                                 score+=2; reasons.append('🔵BlueTracer')
            if near_waypoint:                          score+=1; reasons.append('📍Waypoint')
            score += ar_penalty
            if score >= 6:
                result.update({'type':'BUY','score':score,
                                'reason':f"BUY | {' | '.join(reasons)}"})
                print(f"   [{symbol}] ✅ BUY Score:{score} Type:{pat_type} Order:{order_type}")
            else:
                print(f"   [{symbol}] ⚠️ BUY score {score} < 6")
        elif not can_buy and mw_signal and mw_signal['signal'] == 'W_BOTTOM':
            print(f"   [{symbol}] ⏳ W_BOTTOM — HTF not aligned ({ema_trend_htf})")

        # ── SELL ─────────────────────────────────────────────────────────────
        sell_signal = mw_signal and mw_signal['signal'] == 'M_TOP'
        if can_sell and sell_signal and result['type'] is None:
            pat_type  = classify_pattern_type(candles_ltf, emas_ltf, 'SELL')
            nm_ok, _  = check_near_miss(candles_ltf, symbol, 'SELL', pip)
            score, reasons = calculate_book_score(
                ar_valid, vector_count, m_pattern,
                tdi_ltf['shark_fin_sell'], tdi_ltf['blood_sell'],
                abs(price-mayo)<atr*3,
                price<water and cur_rsi<cur_mbl and tdi_ltf['blood_sell'],
                cur_rsi>cur_up, session['is_primary'], price<blueberry,
                strike_zone_valid=(sz_valid and sz_dir=='bearish'),
                accum_gap_valid=(gap_status=='valid'),
                pattern_type=pat_type, near_miss=nm_ok,
                shadow_box=shadow, straightaway=straightaway_sell, hold_mayo=mayo_sell)
            if ema_str_htf=='strong':                  score+=1; reasons.append('StrongHTF')
            if manipulation=='bearish':                score+=2; reasons.append('🎯StopHunt')
            if session['is_brinks']:                   score+=2; reasons.append('⏰Brinks')
            if candle_conf=='shooting_star':           score+=1; reasons.append('⭐Star')
            if candle_conf=='railroad_tracks':         score+=2; reasons.append('🛤️RRT')
            if tdi_ltf['double_cross_down']:           score+=3; reasons.append('💥DoubleCross')
            elif tdi_ltf['rsi_cross_down']:            score+=1; reasons.append('RSI×↓')
            if tdi_ltf['mbl_cross_down']:              score+=1; reasons.append('MBL×↓')
            if bearish_div:                            score+=2; reasons.append('📉Div')
            if cycle['level']==3:                      score+=2; reasons.append('L3Rev')
            if cycle.get('is_33_trade'):               score+=3; reasons.append('🎰33Trade')
            if cycle.get('is_reset'):                  score+=2; reasons.append('🔄Reset')
            if bt_sph:                                 score+=2; reasons.append('🔵BlueTracer')
            if near_waypoint:                          score+=1; reasons.append('📍Waypoint')
            score += ar_penalty
            if score >= 6:
                result.update({'type':'SELL','score':score,
                                'reason':f"SELL | {' | '.join(reasons)}"})
                print(f"   [{symbol}] ✅ SELL Score:{score} Type:{pat_type} Order:{order_type}")
            else:
                print(f"   [{symbol}] ⚠️ SELL score {score} < 6")
        elif not can_sell and mw_signal and mw_signal['signal'] == 'M_TOP':
            print(f"   [{symbol}] ⏳ M_TOP — HTF not aligned ({ema_trend_htf})")

        return result
    except Exception as e:
        print(f"   [{symbol}] ❌ Strategy error: {e}")
        import traceback; traceback.print_exc()
        return null
