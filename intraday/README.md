# Intraday ORB System — 6-Module Pipeline

**Strategy:** Filtered Opening Range Breakout (ORB) on Nifty 100 cash equity  
**Capital:** Rs 2,00,000 (separate from swing bot)  
**Universe:** 30 liquid Nifty 100 stocks (expandable)  
**Edge:** OR breakout filtered by trend + gap + volume + Nifty gate  

---

## Architecture

```
9:00 AM  SCOUT    → screen 100 stocks, compute gap, EMA50, OR vol avg
9:31 AM  FILTER   → kill on gap/OR-width/volume/trend/Nifty gate (logs WHY)
         ANALYST  → score by RelVol, pre-compute entry/SL/target
         RISK     → enforce daily cap, position size, consecutive-loss guard
         EXECUTOR → Telegram alert (paper: stdout only)
         LOGGER   → decisions.csv — every decision, every day
```

---

## Setup

**1. Add to `.env` (in `trading-bot-v2/` root):**
```
UPSTOX_TOKEN=your_access_token_here
TELEGRAM_TOKEN=your_bot_token        # already set for swing bot
TELEGRAM_CHAT_ID=your_chat_id        # already set for swing bot
```

**2. Get Upstox token:**
- Go to https://developer.upstox.com → Your App → Generate Token
- Token expires daily — regenerate before each session

---

## Run

```bash
cd trading-bot-v2/intraday

# Test any time (paper replay on recent data):
python brain.py --mode paper_replay --token YOUR_TOKEN

# Production schedule:
# 9:00 AM — pre-market scan
python brain.py --mode pre_market

# 9:31 AM — full pipeline
python brain.py --mode market_open

# Compare stop placement:
python brain.py --mode paper_replay --stop midpoint
python brain.py --mode paper_replay --stop low
```

---

## Output files

| File | Contents |
|---|---|
| `decisions.csv` | Full audit log — every stock, every stage, every day |
| `candidates.json` | SCOUT output — reloaded by market_open |

---

## Key parameters (`config.py`)

| Param | Value | Why |
|---|---|---|
| PAPER_MODE | `True` | Start here. Set False only after 20 paper days |
| CAPITAL | Rs 2,00,000 | Intraday allocation only |
| RISK_PCT | 1% | Rs 2,000 max loss per trade |
| RR | 2.0 | 2:1 target |
| SLIPPAGE | 0.1%/side | Realistic 15-min entry delay |
| GAP_MAX_PCT | 2.0% | No exhausted gap-ups |
| MAX_OPEN_POSITIONS | 3 | Daily portfolio cap |
| MAX_POSITION_VALUE | Rs 3L | Single-trade exposure cap |

---

## Phase roadmap

| Phase | What | Gate |
|---|---|---|
| **1 — now** | Paper replay + paper_mode alerts | Run 20 paper days |
| **2** | Live Telegram alerts (PAPER_MODE=False) | Paper WR ≥ backtest WR − 5% |
| **3** | Auto bracket order via Upstox API | 20 live manual days first |

---

## Reading `decisions.csv`

Each row is one decision. Key columns:
- `stage`: which module made the call (SCOUT / FILTER / ANALYST / RISK / EXECUTOR)
- `decision`: PASS / KILL / SKIP / TRADE
- `reason`: exact kill reason (most useful column for debugging)
- `rel_vol`: relative volume at OR — higher = stronger signal
- `pnl_est`: fill manually post-market to track live edge

After 3 days, run:
```python
import pandas as pd
df = pd.read_csv("decisions.csv")
kills = df[df["decision"]=="KILL"]
print(kills.groupby("reason").size().sort_values(ascending=False))
```
This tells you which filter kills the most signals.
