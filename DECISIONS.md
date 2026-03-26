# DECISIONS.md — Trading Bot v2
# Claude reads this FIRST at the start of every session.
# Last updated: 2026-03-25

---

## PROJECT BASICS
- Repo: NEW GitHub repo (not the old trading-bot)
- All files in ROOT of repo — no subdirectories
- Only one bot.yml: .github/workflows/bot.yml
- Capital: Rs 6,00,000 (paper trading for first 30 trades)
- Trader: Sravan Palvai, Dallas TX (UTC-5 / UTC-6)
- Telegram: Chat ID 5001387539

## SCHEDULE (LOCKED — do not change)
- Brain + Alert : `30 14 * * 0-4`  = 8:00 PM IST
- Morning reminder: `30 2 * * 1-5` = 8:00 AM IST
- Scoreboard    : `5 10 * * 1-5`   = 3:35 PM IST
- WHY 8 PM: market data is fresh (closed at 3:30 PM), no GitHub queue delay, Sravan gets alert at 8:30 AM Dallas time — 13 hours before market open

## SIGNAL TIERS (LOCKED)
- STRONG BUY: score 5-6/6 → size 15% = Rs 90,000
- BUY: score 3-4/6 → size 10% = Rs 60,000
- WATCH: score 0-2/6 → size 5% = Rs 30,000 (Sravan's call)
- STAY IN CASH: VIX above 22 → no signals at all

## KEY THRESHOLDS (LOCKED — do not change without backtest)
- VIX_AVOID = 22
- VIX_REDUCE = 18
- ADX_TREND_MIN = 18
- ATR_SL_MULT = 1.5
- ATR_TGT_MULT = 2.5
- MAX_HOLD_DAYS = 6 (trading days)
- MIN_RR = 1.5
- TREND_RSI_MIN = 52 | TREND_RSI_MAX = 66
- OVERSOLD_RSI_MAX = 50

## ARCHITECTURE DECISIONS (LOCKED)
- brain.py → writes signals.json → alert.py reads it (decoupled)
- alert.py auto-logs ALL signals to paper_trades.csv (Sravan does NOTHING)
- scoreboard.py runs independently — works even if brain failed
- config.py is the ONLY place any number lives
- No chart images — text alerts only (faster, never fails)
- No Upstox API — phase 1 is paper trading only
- No intraday — swing only until 30 trades prove the system

## PHASE 1 GOAL (30 days)
- Bot tracks itself completely automatically
- Sravan only reads 8 PM alert and 4 AM scoreboard
- After 30 closed trades: is win rate above 55%?
- If yes → consider going live with real money

## PHASE 2 (after 30 trades prove it)
- Sentiment analysis as veto layer (not signal creator)
- Intraday signals (separate format, separate schedule)
- Upstox API for live execution
- Dashboard on GitHub Pages

## FILES IN THIS REPO (exactly these, no others)
- config.py — all settings
- fetcher.py — data download
- analyzer.py — signal detection
- brain.py — orchestrator
- alert.py — Telegram + paper trade logger
- scoreboard.py — P&L tracker
- backtest.py — 10yr backtest
- .github/workflows/bot.yml — three jobs
- DECISIONS.md — this file
- .gitignore
- requirements.txt
- paper_trades.csv (auto-generated, tracked in git)
- signals.json (auto-generated, tracked in git)

## HOW TO START EVERY SESSION
1. Say "continue from previous chat"
2. Claude reads this file first
3. One problem per session
4. Upload files if code is involved
