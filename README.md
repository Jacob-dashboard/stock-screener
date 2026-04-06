# 🔥 Hot Theme Stock Screener

A standalone Streamlit web app that mirrors a live trading bot's signal stack, scanning sector ETF universes for high-probability momentum setups.

## Install

```bash
cd ~/Projects/stock-screener
pip install -r requirements.txt
```

## Run

```bash
bash run.sh
# or directly:
streamlit run screener/app.py --server.port 8510
```

Open http://localhost:8510 in your browser.

## What It Does

The screener applies **10 sequential filters** — all must pass for a BUY signal:

| # | Filter | Rule |
|---|--------|------|
| 1 | **SPY Regime Gate** | SPY must be above its 50d SMA |
| 2 | **Sector RS Ranking** | Only scan stocks in top N hot sectors (composite RS = 0.6×3mo + 0.4×6mo vs SPY) |
| 3 | **Breadth Thrust** | ≥50% of sector stocks above their 50d SMA |
| 4 | **Stock RS** | Individual stock RS vs SPY > 1.10 (63 trading days) |
| 5 | **RSI** | RSI(14) between 50 and 75 |
| 6 | **MACD** | Histogram positive AND just crossed or trending up |
| 7 | **Price/MA/ROC** | Price above 20d SMA + 5-day ROC > 0 |
| 8 | **VPA** | Price within 1% of 10d high; volume ≥ 0.75× 20d avg |
| 9 | **VCP** | Bollinger Band width in bottom 50th percentile (252d), OR 2+ weekly inside bars |
| 10 | **Trend Template** | Minervini: ≥2 of 4 (Price>SMA50, SMA50>SMA150, SMA150>SMA200, SMA200 trending up) |
| 11 | **ATR R:R Gate** | Stop ≤7% away, R:R ≥ 3:1 (1.5×ATR stop, 4.5×ATR target) |

## UI Sections

1. **Regime Banner** — green/red SPY status, prominent at top
2. **Sector Leaderboard** — all 22 sector ETFs ranked by composite RS with breadth % and new highs
3. **Screener Results** — stocks passing all filters, color-coded by signal strength, with CSV download

## Configuration

All thresholds live in `screener/config.py` as named constants. Key ones:

- `N_HOT_SECTORS = 3` — sectors to scan (also tunable in sidebar)
- `BREADTH_THRESHOLD = 0.50` — relaxed from 0.80 in live bot
- `RS_STOCK_MIN = 1.10` — minimum relative strength
- `ATR_MAX_STOP_PCT = 0.07` — max 7% stop distance
- `ATR_MIN_RR = 3.0` — minimum reward:risk ratio

## Sector Universe

22 sector ETFs from broad market (XLK, XLF, XLV...) to thematic (SMH, CIBR, AIQ, UFO, SKYY...).

## Notes

- Data is cached for 30 minutes via `@st.cache_data(ttl=1800)`
- **Paper mode** — thresholds are relaxed vs the live trading bot
- Not financial advice
