"""
bot.py — BTMM AutoTrader Entry Point
CLI flags:  --broker fbs_demo|exness_cent
            --pairs  EURUSD,GBPUSD
"""
import asyncio, argparse

parser = argparse.ArgumentParser(description='BTMM Trading Bot')
parser.add_argument('--broker', choices=['fbs_demo','exness_cent'], default=None)
parser.add_argument('--pairs',  type=str, default=None)
args = parser.parse_args()

if args.broker:
    import config
    b = config.BROKERS[args.broker]
    config.ACTIVE_BROKER             = args.broker
    config.ACCOUNT_ID                = b['account_id']
    config.SYMBOLS                   = b['symbols']
    config.BROKER_NAME               = b['name']
    config.BROKER_TYPE               = b['type']
    config.RISK['btmm']['fixed_lot'] = b['fixed_lot']

from config import SYMBOLS, BROKER_NAME, BROKER_TYPE, ACTIVE_BROKER
from execution import run_bot

if __name__ == '__main__':
    pairs = args.pairs.split(',') if args.pairs else SYMBOLS
    print("=" * 56)
    print(f"   BTMM BOT — STRICT MODE 🎯")
    print(f"   Broker:  {BROKER_NAME}  [{BROKER_TYPE.upper()}]")
    print(f"   Profile: {ACTIVE_BROKER}")
    print(f"   Pairs:   {', '.join(pairs)}")
    print(f"   Steve Mauro · TDI · Brinks · M&W · Cycle L1-L3")
    print(f"   Lot:0.01 | Min Score:6 | R:R 1:2 min")
    print("=" * 56)
    try:
        asyncio.run(run_bot(mode='btmm', symbols=pairs))
    except KeyboardInterrupt:
        print("\n⛔ Bot stopped")
    except Exception as e:
        print(f"\n❌ Fatal: {e}")
