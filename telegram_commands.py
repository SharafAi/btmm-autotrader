"""
telegram_commands.py — Live Telegram Dashboard
Broker switching, lot override, halt/resume via inline buttons.
"""
import asyncio, requests, config, traceback
from telegram_bot import TELEGRAM_TOKEN, CHAT_ID, send_message, edit_message

_runtime = {
    'broker_switch_requested': None,
    'lot_override':            None,
    'last_update_id':          0,
    'halted_by_command':       False,
}

LOT_SIZES = [0.01, 0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.30, 0.50]

def get_runtime(): return _runtime

def get_dashboard_markup():
    current_lot = config.RISK['btmm']['fixed_lot']
    halt_text   = "🟢 RESUME Bot" if _runtime['halted_by_command'] else "⛔ HALT Bot"
    halt_data   = "resume"        if _runtime['halted_by_command'] else "halt"
    fbs_pfx = "✅ " if config.ACTIVE_BROKER == 'fbs_demo'    else ""
    exn_pfx = "✅ " if config.ACTIVE_BROKER == 'exness_cent' else ""

    lot_buttons = []
    row = []
    for lot in LOT_SIZES:
        label = f"{'✅ ' if lot == current_lot else ''}📦 {lot:.2f}"
        row.append({'text': label, 'callback_data': f'set_lot_{lot:.2f}'})
        if len(row) == 3:
            lot_buttons.append(row); row = []
    if row: lot_buttons.append(row)

    keyboard = [
        [{'text': f'{fbs_pfx}🔵 FBS Demo',    'callback_data': 'set_broker_fbs_demo'},
         {'text': f'{exn_pfx}🟠 Exness Cent', 'callback_data': 'set_broker_exness_cent'}],
        *lot_buttons,
        [{'text': halt_text, 'callback_data': halt_data},
         {'text': '📊 Refresh',  'callback_data': 'refresh'}],
    ]
    return {'inline_keyboard': keyboard}

def get_status_text():
    lot = config.RISK['btmm']['fixed_lot']
    return (
        f"📊 <b>BTMM Bot Dashboard</b>\n{'─'*28}\n"
        f"🏦 Broker:  <b>{config.BROKER_NAME}</b>\n"
        f"🆔 Account: <code>{config.ACCOUNT_ID[:8]}...</code>\n"
        f"📦 Lot:     <code>{lot:.2f}</code>\n"
        f"⛔ Halted:  <code>{'YES' if _runtime['halted_by_command'] else 'NO'}</code>\n"
        f"{'─'*28}\n<i>Tap below to change settings:</i>"
    )

def _fetch_updates(offset):
    try:
        url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates'
        r = requests.get(url, params={'offset': offset, 'timeout': 5}, timeout=10)
        return r.json().get('result', []) if r.status_code == 200 else []
    except:
        return []

def _answer_callback(cb_id):
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery',
            json={'callback_query_id': cb_id}, timeout=5)
    except:
        pass

def _handle_callback(data, msg_id):
    if data.startswith('set_broker_'):
        key = data.replace('set_broker_', '')
        if key != config.ACTIVE_BROKER:
            _runtime['broker_switch_requested'] = key
            edit_message(msg_id, f"🔄 <b>Switching to {key}...</b>")
            return
    elif data.startswith('set_lot_'):
        new_lot = float(data.replace('set_lot_', ''))
        config.RISK['btmm']['fixed_lot'] = new_lot
        config.BROKERS[config.ACTIVE_BROKER]['fixed_lot'] = new_lot
        _runtime['lot_override'] = new_lot
    elif data == 'halt':
        _runtime['halted_by_command'] = True
    elif data == 'resume':
        _runtime['halted_by_command'] = False
    edit_message(msg_id, get_status_text(), get_dashboard_markup())

def register_commands():
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands',
            json={'commands': [
                {'command': 'settings', 'description': 'Open Dashboard ⚙️'},
                {'command': 'status',   'description': 'Refresh status 📊'},
            ]}, timeout=10)
    except:
        pass

async def command_listener():
    print("   📱 Telegram command listener active")
    register_commands()
    while True:
        try:
            updates = await asyncio.to_thread(
                _fetch_updates, _runtime['last_update_id'] + 1)
            for upd in updates:
                _runtime['last_update_id'] = upd['update_id']
                if 'callback_query' in upd:
                    cb = upd['callback_query']
                    asyncio.create_task(asyncio.to_thread(_answer_callback, cb['id']))
                    if str(cb['message']['chat']['id']) == str(CHAT_ID):
                        _handle_callback(cb['data'], cb['message']['message_id'])
                elif 'message' in upd and 'text' in upd['message']:
                    msg = upd['message']
                    if str(msg['chat']['id']) == str(CHAT_ID) and msg['text'].startswith('/'):
                        send_message(get_status_text(), get_dashboard_markup())
        except Exception as e:
            print(f"   🚨 [TG LISTENER] {e}")
        await asyncio.sleep(1)
