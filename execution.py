"""
execution.py — BTMM Trade Execution Engine

Daily rules:  2 losses → halt, 2 wins → halt (protect profits), max 3 trades
State:        Persisted to .bot_state.json across restarts
Pending:      Pullback entries registered and triggered on price touch
Trail Ladder: +5p→BE, +10p→lock+7p, +20p→lock 50%, +30p→trail Water(50 EMA)
TDI Exit:     2 consecutive bars RSI below Signal + MBL + price through Water
Brokers:      Auto-failover across BROKERS dict; hot-switch via Telegram
"""
import asyncio, json, os, pandas as pd
from datetime import datetime, timezone
from metaapi_cloud_sdk import MetaApi
import config
from config import TOKEN, TIMEFRAMES, RISK
from risk import calculate_sl_tp, profit_pips, _calculate_lot_pct, _pip
from indicators import calculate_tdi, calculate_all_emas
from strategy import check_entry, mark_symbol_traded
from patterns import get_session_info, get_ny_time, get_mv_time
from telegram_bot import (send_message, send_trade_alert, send_close_alert,
                           send_error, send_startup_banner)
from telegram_commands import command_listener, get_runtime

MODE = 'btmm'
_STATE_FILE = os.path.join(os.path.dirname(__file__), '.bot_state.json')

# ── Daily counters ────────────────────────────────────────────────────────────
_daily = {'trade_count':0, 'win_count':0, 'loss_count':0, 'halted':False, 'reset_key':None}
_pending_entries = {}   # {symbol: pending dict}

# ── State persistence ─────────────────────────────────────────────────────────
def _save_state():
    try:
        state = {}
        if os.path.exists(_STATE_FILE):
            with open(_STATE_FILE) as f: state = json.load(f)
        state['daily'] = {k: _daily[k] for k in ('reset_key','trade_count','win_count','loss_count','halted')}
        state['active_broker'] = config.ACTIVE_BROKER
        with open(_STATE_FILE, 'w') as f: json.dump(state, f)
    except Exception as e: print(f"   ⚠️ Save state: {e}")

def _load_state():
    try:
        if not os.path.exists(_STATE_FILE): return
        with open(_STATE_FILE) as f: state = json.load(f)
        saved = state.get('daily', {})
        ny    = get_ny_time()
        key   = f"{ny.date()}-{'post17' if ny.hour>=17 else 'pre17'}"
        if saved.get('reset_key') == key:
            _daily.update(saved)
            print(f"   🔄 Restored: T:{_daily['trade_count']} W:{_daily['win_count']} L:{_daily['loss_count']}")
    except: pass

def _reset_daily():
    ny  = get_ny_time()
    key = f"{ny.date()}-{'post17' if ny.hour>=17 else 'pre17'}"
    if _daily['reset_key'] != key:
        _load_state()
        if _daily['reset_key'] == key: return
        _daily.update({'trade_count':0,'win_count':0,'loss_count':0,'halted':False,'reset_key':key})
        _pending_entries.clear()
        print(f"   🔄 Daily reset NY:{ny.strftime('%H:%M')}")

def _record_result(is_win):
    if is_win: _daily['win_count'] += 1
    else:      _daily['loss_count'] += 1
    if _daily['loss_count'] >= 2:
        _daily['halted'] = True; _save_state()
        send_message("⛔ <b>2 LOSSES — DONE FOR THE DAY</b>\nHalted until 17:00 ET.")
    elif _daily['win_count'] >= 2:
        _daily['halted'] = True; _save_state()
        send_message("🏆 <b>2 WINS — DONE FOR THE DAY</b>\nProtecting profits.")

def _is_halted():
    _reset_daily()
    if _daily['halted']: return True
    if _daily['trade_count'] >= RISK[MODE]['max_trades']:
        print(f"   📵 Daily limit reached."); return True
    return False

def _pip_sym(symbol): return _pip(symbol)

# ── Candle fetching ───────────────────────────────────────────────────────────
async def get_candles(account, symbol, timeframe, count=200):
    try:
        candles = await account.get_historical_candles(symbol, timeframe, datetime.now(timezone.utc), count)
        df = pd.DataFrame(candles); df['time'] = pd.to_datetime(df['time']); return df
    except Exception as e:
        print(f"   ❌ Candle error [{symbol}]: {e}"); return None

# ── Order placement ───────────────────────────────────────────────────────────
async def place_market_order(conn, sig, symbol, lot, sl, tp, reason, price, score=0, cycle_str=''):
    try:
        if sig=='BUY': await conn.create_market_buy_order(symbol, lot, sl, tp, {'comment':'BTMM-MKT'})
        else:          await conn.create_market_sell_order(symbol, lot, sl, tp, {'comment':'BTMM-MKT'})
        print(f"   ✅ MARKET {sig} {symbol} @ {price} SL:{sl} TP:{tp}")
        _daily['trade_count'] += 1; _save_state(); mark_symbol_traded(symbol, sig)
        send_trade_alert(symbol, sig.lower(), lot, price, sl, tp, score, reason, cycle_str)
        return True
    except Exception as e:
        print(f"   ❌ Market order [{symbol}]: {e}"); send_error(f"Order failed {symbol}: {e}"); return False

async def place_limit_order(conn, sig, symbol, lot, entry, sl, tp, reason, score=0, cycle_str=''):
    try:
        if sig=='BUY': await conn.create_limit_buy_order(symbol, lot, entry, sl, tp, {'comment':'BTMM-LMT'})
        else:          await conn.create_limit_sell_order(symbol, lot, entry, sl, tp, {'comment':'BTMM-LMT'})
        print(f"   📋 LIMIT {sig} {symbol} @ {entry} SL:{sl} TP:{tp}")
        _daily['trade_count'] += 1; _save_state(); mark_symbol_traded(symbol, sig)
        send_trade_alert(symbol, sig.lower(), lot, entry, sl, tp, score, f"LIMIT — {reason}", cycle_str)
        return True
    except Exception as e:
        print(f"   ❌ Limit order [{symbol}]: {e}"); send_error(f"Limit failed {symbol}: {e}"); return False

def register_pending_entry(symbol, sig, price, sl, tp, lot, reason, score, cycle_str, order_type, pullback_pct):
    pip = _pip_sym(symbol); sl_pips = abs(price-sl)/pip
    pb_pips = sl_pips*(pullback_pct/100)
    target = round(price-(pb_pips*pip),5) if sig=='BUY' else round(price+(pb_pips*pip),5)
    _pending_entries[symbol] = {
        'type':sig,'current_price':price,'target_entry':target,'sl':sl,'tp':tp,
        'lot':lot,'reason':reason,'score':score,'cycle_str':cycle_str,
        'order_type':order_type,'pullback_pct':pullback_pct,'placed_at':datetime.now(timezone.utc)}
    print(f"   📋 [{symbol}] Pending {order_type}: wait {pullback_pct}% → {target}")
    send_message(f"⏳ <b>{symbol}</b> — Waiting {pullback_pct}% pullback\n"
                 f"Target: <code>{target}</code>")

async def check_pending_entries(conn, account, symbol, cur_price):
    if symbol not in _pending_entries: return
    p = _pending_entries[symbol]
    elapsed = (datetime.now(timezone.utc)-p['placed_at']).total_seconds()/60
    if elapsed > 90:
        del _pending_entries[symbol]
        send_message(f"🚫 <b>{symbol}</b> — Pullback entry expired")
        return
    hit = (p['type']=='BUY' and cur_price<=p['target_entry']) or \
          (p['type']=='SELL' and cur_price>=p['target_entry'])
    if hit:
        del _pending_entries[symbol]
        print(f"   [{symbol}] ✅ Pullback hit → entering")
        await place_market_order(conn, p['type'], symbol, p['lot'], p['sl'], p['tp'],
                                 f"PULLBACK({p['pullback_pct']}%) | {p['reason']}",
                                 cur_price, p['score'], p['cycle_str'])

# ── Trade management (trail ladder + TDI exit) ────────────────────────────────
async def manage_trade(conn, pos, symbol, candles_ltf):
    try:
        entry=pos.get('openPrice',0); cur=pos.get('currentPrice',entry)
        cur_sl=pos.get('stopLoss',0); cur_tp=pos.get('takeProfit',0)
        sig = 'BUY' if 'BUY' in pos.get('type','').upper() else 'SELL'
        pip = _pip_sym(symbol); pips = profit_pips(sig, entry, cur, symbol)
        closes=candles_ltf['close']; tdi=calculate_tdi(closes); emas=calculate_all_emas(closes)
        water=float(emas['water'].iloc[-1]); rsi=tdi['rsi']; signal=tdi['signal']; mbl=tdi['mbl']
        new_sl=None

        # TDI confirmed exit (2 bars + MBL + Water break + ≥10p profit)
        if sig=='BUY':
            tdi_exit=(float(rsi.iloc[-1])<float(signal.iloc[-1]) and
                      float(rsi.iloc[-2])<float(signal.iloc[-2]) and
                      float(rsi.iloc[-1])<float(mbl.iloc[-1]) and
                      cur<water and pips>10)
        else:
            tdi_exit=(float(rsi.iloc[-1])>float(signal.iloc[-1]) and
                      float(rsi.iloc[-2])>float(signal.iloc[-2]) and
                      float(rsi.iloc[-1])>float(mbl.iloc[-1]) and
                      cur>water and pips>10)
        if tdi_exit:
            pf=pos.get('unrealizedProfit')
            await conn.close_position(pos['id'])
            outcome='PROFIT' if (pf and float(pf)>=0) else 'LOSS'
            send_close_alert(symbol,outcome,pf or 0,f"TDI Exit +{round(pips,1)}p",pos['id'])
            if pf: _record_result(float(pf)>=0)
            return

        # Trail ladder
        if sig=='BUY':
            if pips>=30:
                trail=round(water-(8*pip),5)
                if trail>cur_sl and trail<cur: new_sl=trail
            elif pips>=20:
                lock=round(entry+(pips*0.5*pip),5)
                if lock>cur_sl: new_sl=lock
            elif pips>=10:
                lock=round(entry+(7*pip),5)
                if lock>cur_sl: new_sl=lock
            elif pips>=5:
                be=round(entry+pip,5)
                if be>cur_sl: new_sl=be
        else:
            if pips>=30:
                trail=round(water+(8*pip),5)
                if trail<cur_sl and trail>cur: new_sl=trail
            elif pips>=20:
                lock=round(entry-(pips*0.5*pip),5)
                if lock<cur_sl: new_sl=lock
            elif pips>=10:
                lock=round(entry-(7*pip),5)
                if lock<cur_sl: new_sl=lock
            elif pips>=5:
                be=round(entry-pip,5)
                if be<cur_sl: new_sl=be

        if new_sl:
            try:
                await conn.modify_position(pos['id'], stop_loss=new_sl, take_profit=cur_tp)
                send_message(f"🔐 <b>{symbol}</b> SL → {new_sl} (+{round(pips,1)}p)")
            except Exception as e: print(f"   ⚠️ Modify [{symbol}]: {e}")
    except Exception as e: print(f"   ⚠️ Manage trade [{symbol}]: {e}")

async def close_trade(conn, pos_id, symbol, reason="", profit=None):
    try:
        await conn.close_position(pos_id)
        print(f"   🔒 Closed {symbol} | {reason} | P&L:{profit}")
        if profit is not None: _record_result(float(profit)>=0)
        outcome='PROFIT' if (profit and float(profit)>=0) else 'LOSS'
        send_close_alert(symbol, outcome, profit or 0, reason, pos_id)
    except Exception as e: print(f"   ❌ Close [{symbol}]: {e}")

# ── Per-symbol scan ───────────────────────────────────────────────────────────
async def process_symbol(conn, account, symbol, info, positions, orders):
    try:
        tf=TIMEFRAMES[MODE]; risk=RISK[MODE]; session=get_session_info()
        sym_pos=[p for p in positions if p['symbol']==symbol]
        sym_ord=[o for o in orders    if o['symbol']==symbol]

        if session['is_friday_exit']:
            for pos in sym_pos:
                await close_trade(conn,pos['id'],symbol,"Friday Exit",pos.get('unrealizedProfit'))
            _pending_entries.pop(symbol, None); return

        if sym_pos:
            ltf=await get_candles(account,symbol,tf['entry'],100)
            for pos in sym_pos:
                if ltf is not None: await manage_trade(conn,pos,symbol,ltf)
                opened=pd.to_datetime(pos['time'])
                if opened.tzinfo is None: opened=opened.replace(tzinfo=timezone.utc)
                elapsed=(datetime.now(timezone.utc)-opened).total_seconds()/60
                profit=pos.get('unrealizedProfit',0)
                if elapsed>risk['scratch_minutes'] and float(profit)<0:
                    await close_trade(conn,pos['id'],symbol,"2-Hr Scratch",profit)
            return

        if not sym_pos and not sym_ord and symbol in _pending_entries:
            now=await get_candles(account,symbol,tf['entry'],5)
            if now is not None:
                await check_pending_entries(conn,account,symbol,float(now['close'].iloc[-1]))
            return

        if _is_halted(): return
        if sym_pos or sym_ord or symbol in _pending_entries: return

        # NY open blackout
        ny=get_ny_time()
        if ny.hour==9 and ny.minute<45: print(f"   🚫 NY open blackout"); return

        candles_ltf   = await get_candles(account,symbol,tf['entry'],200)
        candles_htf   = await get_candles(account,symbol,tf['trend'],200)
        candles_daily = await get_candles(account,symbol,tf.get('cycle','1d'),10)
        if candles_ltf is None or candles_htf is None: return

        signal=check_entry(candles_ltf,candles_htf,symbol,MODE,candles_daily=candles_daily)
        if signal['type'] is None: return
        if signal['score']<risk['min_score']:
            print(f"   [{symbol}] Score {signal['score']}<{risk['min_score']} — skip"); return

        price      = float(candles_ltf['close'].iloc[-1])
        atr        = signal['atr']
        emas       = signal.get('emas_ltf')
        balance    = float(info.get('equity', info.get('balance',1000)))
        order_type = signal.get('order_type','market')
        pullback   = signal.get('pullback_pct',0)

        sl, tp = calculate_sl_tp(signal['type'], price, atr, candles_ltf,
                                  risk['rr'], MODE, symbol, emas,
                                  session_high=signal.get('session_high'),
                                  session_low=signal.get('session_low'))
        if sl is None: print(f"   [{symbol}] ❌ No valid SL/TP"); return

        sl_pips = abs(price-sl)/_pip_sym(symbol)
        lot     = _calculate_lot_pct(balance, 1.0, sl_pips, symbol)
        ny=get_ny_time(); mv=get_mv_time()
        reason    = f"{signal['reason']} | NY:{ny.strftime('%H:%M')} MV:{mv.strftime('%H:%M')}"
        cycle     = signal.get('cycle') or {}
        cycle_str = f"L{cycle.get('level',0)} {cycle.get('direction','?')[:4].capitalize()}"

        if order_type=='market':
            await place_market_order(conn,signal['type'],symbol,lot,sl,tp,reason,price,signal['score'],cycle_str)
        elif order_type=='pullback_25':
            register_pending_entry(symbol,signal['type'],price,sl,tp,lot,reason,signal['score'],cycle_str,order_type,25)
        elif order_type=='pullback_50':
            await place_limit_order(conn,signal['type'],symbol,lot,price,sl,tp,reason,signal['score'],cycle_str)

    except Exception as e:
        print(f"   ⚠️ [{symbol}] process error: {e}")
        import traceback; traceback.print_exc()

# ── Keep-alive ────────────────────────────────────────────────────────────────
async def keep_alive(conn):
    while True:
        try:
            await asyncio.sleep(30)
            await asyncio.wait_for(conn.get_account_information(), timeout=10)
        except: break

# ── Main bot loop ─────────────────────────────────────────────────────────────
async def run_bot(mode='btmm', symbols=None):
    global MODE
    MODE = mode
    SYMS = symbols or config.SYMBOLS
    send_startup_banner(mode, config.RISK[MODE]['fixed_lot'])
    retry_delay = 30
    cmd_task    = asyncio.create_task(command_listener())

    while True:
        rt = get_runtime()
        if rt['broker_switch_requested']:
            key=rt['broker_switch_requested']; rt['broker_switch_requested']=None
            bk=config.BROKERS[key]
            config.ACTIVE_BROKER=key; config.ACCOUNT_ID=bk['account_id']
            config.SYMBOLS=bk['symbols']; config.BROKER_NAME=bk['name']
            config.BROKER_TYPE=bk['type']; config.RISK[MODE]['fixed_lot']=bk.get('fixed_lot',0.01)
            SYMS=config.SYMBOLS; _save_state()
            send_message(f"✅ <b>Switched to {bk['name']}</b>")
            print(f"\n🔄 Broker → {bk['name']}")

        api=account=conn=keepalive=None
        try:
            for bk_key in ([config.ACTIVE_BROKER]+[k for k in config.BROKERS if k!=config.ACTIVE_BROKER]):
                bk=config.BROKERS[bk_key]
                try:
                    print(f"   🔌 Trying {bk['name']}...")
                    _api=MetaApi(TOKEN); _acc=await _api.metatrader_account_api.get_account(bk['account_id'])
                    await asyncio.wait_for(_acc.wait_connected(),timeout=30)
                    _conn=_acc.get_rpc_connection(); await _conn.connect()
                    await asyncio.wait_for(_conn.wait_synchronized(),timeout=60)
                    api=_api; account=_acc; conn=_conn
                    if bk_key!=config.ACTIVE_BROKER:
                        config.ACTIVE_BROKER=bk_key; config.ACCOUNT_ID=bk['account_id']
                        config.SYMBOLS=bk['symbols']; config.BROKER_NAME=bk['name']
                        config.BROKER_TYPE=bk['type']; SYMS=config.SYMBOLS; _save_state()
                        send_message(f"⚠️ <b>Auto-switched to {bk['name']}</b>")
                    print(f"✅ Connected! ({config.BROKER_NAME})"); break
                except Exception as fe:
                    print(f"   ❌ {bk['name']} failed: {fe}")
                    try: _api.close()
                    except: pass

            if conn is None: raise Exception("All brokers failed")
            keepalive=asyncio.create_task(keep_alive(conn)); retry_delay=30

            while True:
                try:
                    _reset_daily(); rt=get_runtime()
                    if rt['broker_switch_requested']: break
                    if rt['lot_override'] is not None:
                        config.RISK[MODE]['fixed_lot']=rt['lot_override']; rt['lot_override']=None
                    if rt['halted_by_command']:
                        await asyncio.sleep(30); continue

                    info      = await asyncio.wait_for(conn.get_account_information(),timeout=15)
                    positions = await asyncio.wait_for(conn.get_positions(),timeout=15)
                    orders    = await asyncio.wait_for(conn.get_orders(),timeout=15)
                    session   = get_session_info()

                    if session['is_friday_exit'] and positions:
                        for pos in positions:
                            await close_trade(conn,pos['id'],pos['symbol'],
                                              "Friday Global Exit",pos.get('unrealizedProfit'))
                        _pending_entries.clear(); await asyncio.sleep(60); continue

                    ny=get_ny_time(); mv=get_mv_time()
                    win=('🟢 PRIMARY' if session['is_primary'] else
                         '🟡 ACTIVE'  if session['active']     else '🔴 WAITING')
                    print(f"\n{'═'*56}")
                    print(f"  💰 ${info['balance']:,.2f}  Open:{len(positions)}  "
                          f"W:{_daily['win_count']} L:{_daily['loss_count']}  "
                          f"Pending:{len(_pending_entries)}")
                    print(f"  🕐 NY:{ny.strftime('%H:%M')}  🌊 MV:{mv.strftime('%H:%M')}  {win}")
                    print(f"{'═'*56}")

                    for sym in SYMS:
                        await process_symbol(conn,account,sym,info,positions,orders)
                        await asyncio.sleep(1)
                    print(f"\n   ⏱ Next scan 60s")
                    await asyncio.sleep(60)

                except asyncio.CancelledError: raise
                except asyncio.TimeoutError:
                    print("   ⏱️ Timeout — retrying..."); await asyncio.sleep(10)
                except Exception as e:
                    err=str(e).lower()
                    if any(k in err for k in ['disconnect','connection','synchronized','closed']):
                        print(f"⚠️ Connection error: {e}"); break
                    print(f"⚠️ Scan error: {e}"); await asyncio.sleep(5)

        except asyncio.CancelledError: print("⛔ Bot cancelled."); break
        except Exception as e:
            print(f"❌ Connect failed: {e}"); send_error(f"Connection lost — retry {retry_delay}s")
            retry_delay=min(retry_delay*2,300)
        finally:
            if keepalive: keepalive.cancel()
            try:
                if conn: await conn.close()
            except: pass
            try:
                if api: api.close()
            except: pass
            print("🧹 Cleaned up.")
        await asyncio.sleep(retry_delay)
