# BTMM AutoTrader Bot

A Python algorithmic trading bot built on **Steve Mauro's Beat The Market Maker (BTMM)** methodology, connected to MetaTrader via the **MetaAPI Cloud SDK**.

## Architecture

| Module | Responsibility |
|---|---|
| `config.py` | All constants — sessions, EMA stack, risk params, pip sizes |
| `indicators.py` | EMA, RSI, TDI, ADR calculation |
| `patterns.py` | Asian Range detection, 3-push vector count, M/W pattern detection, candlestick patterns |
| `cycles.py` | Cycle level identification (L1/L2/L3) and directional bias |
| `risk.py` | Foot Soldier position sizing, SL placement, Two-Hour Rule |
| `execution.py` | Main scan loop, 5-condition binary confluence gate, order placement |
| `tests.py` | Unit test suite (34 tests) |

## BTMM Entry Rules Implemented

### 5-Condition Binary Confluence Gate
All 5 must pass — any failure is a hard **PASS**:
1. Asian Range ≤ 50 pips
2. Stop hunt extends 25–50 pips outside Asian Range
3. Stop hunt shows **3 distinct vector pushes**
4. Second leg M/W with valid accumulation gap (30–90 min)
5. Trade within London (03:30–12:00 ET) or NY (08:00–17:00 ET) session

### Session Timing
- **Blocked**: London Gap (03:00–03:30), NY Gap (09:00–09:30), Dharma/Dead Zone (17:00–20:00)
- **Favoured**: Brinks trades at 03:45 ET and 09:45 ET

### Cycle Levels (H1 chart)
- **L1** — 13/50 EMA crossover + tightening → breakout trade
- **L2** — 50/200 EMA crossover → trend continuation
- **L3** — Full EMA fanning + TDI Shark Fin → counter-trend reversal

### Entry Types
- **Nameable pattern** (RRT, Hammer, Star, COW) → Market order at next candle open
- **Standard** → Limit order (ZRT) at 1st leg extreme

### Risk (Foot Soldier)
- Initial signal: **1% risk**
- Confirmed retest: **2% aggregate**
- SL: 10 pips beyond the 1st leg wick extreme

## Setup

```bash
pip install metaapi-cloud-sdk pandas numpy pytz
```

Set `TOKEN` and `ACCOUNT_ID` in `config.py` (or load from environment variables).

```bash
python execution.py
```

## Tests

```bash
python -m pytest tests.py -v
```
