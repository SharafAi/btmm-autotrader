"""
telegram_bot.py — BTMM Professional Alerts
Non-blocking fire-and-forget via threading.
"""
import requests, threading, sys
from datetime import datetime

TELEGRAM_TOKEN = '8879321466:AAH8Pu5yVMuVRnmfdFbYMu6kC8HoyzQkHgE'
CHAT_ID        = '7953520542'

def _dispatch(method, data):
    try:
        url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}'
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"   ⚠️ [TG] {method} failed: {e}", file=sys.stderr)

def send_message(text, reply_markup=None):
    data = {'chat_id': CHAT_ID, 'text': text,
            'parse_mode': 'HTML', 'disable_web_page_preview': True}
    if reply_markup:
        data['reply_markup'] = reply_markup
    threading.Thread(target=_dispatch, args=('sendMessage', data), daemon=True).start()

def edit_message(msg_id, text, reply_markup=None):
    data = {'chat_id': CHAT_ID, 'message_id': msg_id,
            'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True}
    if reply_markup:
        data['reply_markup'] = reply_markup
    threading.Thread(target=_dispatch, args=('editMessageText', data), daemon=True).start()

def send_startup_banner(mode, lot_size):
    from patterns import get_ny_time, get_mv_time, get_session_info
    from cycles import get_day_of_week_note
    ny = get_ny_time(); mv = get_mv_time(); session = get_session_info()
    active = ', '.join(session['active']).upper() or 'NONE'
    day_name, day_note, _ = get_day_of_week_note()
    window = ('🟢 PRIMARY' if session['is_primary'] else
              '🟡 SECONDARY' if session['active'] else '🔴 NO TRADE ZONE')
    send_message(
        f"🤖 <b>BTMM BOT ONLINE</b>\n{'─'*30}\n"
        f"📊 Mode: <b>Steve Mauro BTMM</b>\n"
        f"📦 Lot: <b>{lot_size}</b>\n"
        f"🎯 Min Score: <b>6</b>\n"
        f"{'─'*30}\n"
        f"🕐 NY: <code>{ny.strftime('%H:%M ET')}</code>\n"
        f"🌊 MV: <code>{mv.strftime('%H:%M MVT')}</code>\n"
        f"📡 Session: <code>{active}</code>\n"
        f"🪟 Window: {window}\n"
        f"📅 Today: <b>{day_name}</b> — {day_note}\n"
        f"{'─'*30}\n"
        f"<i>Waiting for the Dealer to show his hand...</i>",
        reply_markup={'inline_keyboard': [[{'text': '⚙️ Dashboard', 'callback_data': 'status'}]]}
    )

def send_trade_alert(symbol, side, lot, price, sl, tp, score, reason, cycle_info):
    from patterns import get_ny_time, get_mv_time
    ny = get_ny_time(); mv = get_mv_time()
    emoji = "🔵 BUY" if side == 'buy' else "🔴 SELL"
    send_message(
        f"{emoji} <b>ORDER — {symbol}</b>\n{'─'*32}\n"
        f"⭐ Score: <b>{score}</b>\n"
        f"📦 Lot:   <code>{lot}</code>\n"
        f"🎯 Entry: <code>{price}</code>\n"
        f"🛡️ SL:    <code>{sl}</code>\n"
        f"🏁 TP:    <code>{tp}</code>\n"
        f"{'─'*32}\n"
        f"📊 Cycle: {cycle_info}\n"
        f"🧐 Reason: {reason}\n"
        f"{'─'*32}\n"
        f"🕐 NY: <code>{ny.strftime('%H:%M ET')}</code>  "
        f"🌊 MV: <code>{mv.strftime('%H:%M MVT')}</code>"
    )

def send_close_alert(symbol, outcome, profit, reason, position_id):
    from patterns import get_ny_time, get_mv_time
    ny = get_ny_time(); mv = get_mv_time()
    emoji  = "💰" if outcome == 'PROFIT' else "📉"
    result = f"+${profit}" if float(profit) > 0 else f"${profit}"
    edu = ''
    if 'TDI'    in reason: edu = '\n📚 <i>TDI flipped. Momentum gone.</i>'
    elif '2-Hr' in reason: edu = '\n📚 <i>2-Hour Rule fired.</i>'
    elif 'Friday' in reason: edu = '\n📚 <i>Friday exit rule.</i>'
    elif 'BE'   in reason: edu = '\n📚 <i>Stopped at breakeven.</i>'
    send_message(
        f"{'─'*32}\n{emoji} <b>TRADE CLOSED — {symbol}</b>\n{'─'*32}\n"
        f"📊 Result: <b>{outcome}</b>\n"
        f"💰 P&L:    <code>{result}</code>\n"
        f"📝 Reason: {reason}\n"
        f"🆔 Ticket: <code>{position_id}</code>\n"
        f"🕐 NY: <code>{ny.strftime('%H:%M ET')}</code>{edu}",
        reply_markup={'inline_keyboard': [[{'text': '⚙️ Dashboard', 'callback_data': 'status'}]]}
    )

def send_sl_update(symbol, new_sl, reason):
    send_message(f"🛡️ <b>SL UPDATED — {symbol}</b>\n📍 New SL: {new_sl}\n🧐 {reason}")

def send_heartbeat(symbols):
    from patterns import get_ny_time, get_mv_time, get_session_info
    ny = get_ny_time(); mv = get_mv_time(); s = get_session_info()
    window = '🟢 PRIMARY' if s['is_primary'] else '⚪ SCANNING'
    send_message(
        f"💓 <b>HEARTBEAT</b>\nNY: {ny.strftime('%H:%M ET')} "
        f"MV: {mv.strftime('%H:%M MVT')}\n{window}\n<i>{symbols}</i>",
        reply_markup={'inline_keyboard': [[{'text': '⚙️ Dashboard', 'callback_data': 'status'}]]}
    )

def send_error(msg):
    send_message(f"⚠️ <b>BOT ERROR</b>\n<code>{msg}</code>")
