# screener/app.py — Streamlit UI for Market Screener

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import logging
from collections import Counter
from datetime import datetime
import pandas as pd
import streamlit as st

from screener.config import N_HOT_SECTORS, RS_STOCK_MIN, RSI_MIN, RSI_MAX, BREADTH_THRESHOLD
from screener.data import fetch_spy
from screener.sector_engine import build_sector_table
from screener.signal_engine import (
    run_screener,
    run_proximity_scanner,
    run_full_universe_screener,
    SignalResult,
    ProximityResult,
)
from screener.theme_tracker import render_theme_tracker, SORT_COLUMNS as TRACKER_SORT_COLUMNS
from screener.news_scanner import render_news_scanner
from screener.universe import get_universe, universe_cache_info
from screener.breadth import (
    render_breadth_dashboard,
    _fetch_sp500_close,
    _fetch_spy_1y,
    _fetch_vix,
)
from screener.breadth_stockbee import fetch_stockbee_breadth
from screener.dashboard import render_dashboard
from screener.ui.theme import (
    inject_theme,
    render_app_header,
    render_sidebar_brand,
    render_footer,
)

logging.basicConfig(level=logging.WARNING)

st.set_page_config(
    page_title="Market Screener",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_theme()


# ── Page identifiers ─────────────────────────────────────────────────────────
PAGE_DASHBOARD = "Dashboard"
PAGE_HOT_SIGNALS = "Hot Signals"
PAGE_PROXIMITY = "52W Proximity"
PAGE_BREADTH = "Market Breadth"
PAGE_THEMES = "Theme Rotation"
PAGE_NEWS = "News Scanner"

PAGES = [
    PAGE_DASHBOARD,
    PAGE_HOT_SIGNALS,
    PAGE_PROXIMITY,
    PAGE_BREADTH,
    PAGE_THEMES,
    PAGE_NEWS,
]


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    render_sidebar_brand()

    page = st.radio(
        "Navigation",
        PAGES,
        label_visibility="collapsed",
    )
    st.divider()

    # Page-specific controls
    run_btn = False

    if page == PAGE_DASHBOARD:
        st.caption("Market overview · refreshes every 15 min")
        if st.button("Refresh Dashboard", use_container_width=True):
            _fetch_sp500_close.clear()
            _fetch_spy_1y.clear()
            _fetch_vix.clear()
            fetch_stockbee_breadth.clear()
            from screener.theme_tracker import fetch_theme_etfs
            fetch_theme_etfs.clear()
            st.rerun()

    elif page == PAGE_HOT_SIGNALS:
        st.caption("Full universe scan · ~5,000 tickers · 30-min cache")
        n_hot = st.slider(
            "Sectors in Leaderboard",
            min_value=1, max_value=22, value=N_HOT_SECTORS,
            help="Number of sectors shown as HOT. Signal scan covers all tickers.",
        )
        st.subheader("Threshold Overrides")
        rs_min = st.number_input("Min Stock RS", min_value=0.8, max_value=2.0,
                                 value=float(RS_STOCK_MIN), step=0.05)
        rsi_lo = st.number_input("RSI Min", min_value=30, max_value=65, value=RSI_MIN)
        rsi_hi = st.number_input("RSI Max", min_value=60, max_value=85, value=RSI_MAX)
        breadth_thresh = st.slider(
            "Breadth Threshold", min_value=0.20, max_value=0.90,
            value=float(BREADTH_THRESHOLD), step=0.05,
            help="% stocks above 50d SMA — used for sector colouring.",
        )
        run_btn = st.button("Run Screener", type="primary", use_container_width=True)
        st.caption("Data cached 30 min. Click to refresh.")

    elif page == PAGE_PROXIMITY:
        st.caption("Find stocks trading near their 52-week high")
        proximity_pct = st.slider(
            "Max % below 52W high",
            min_value=1, max_value=40, value=5,
            help="5 = within 5% of the 52-week high. Sorted closest-first.",
        )
        info = universe_cache_info()
        if info["cached"] and not info["stale"]:
            st.caption(f"Universe: {info['count']:,} tickers · cached {info['age_hours']}h ago")
        else:
            st.caption("Universe: will fetch ~5,000 tickers on first run")
        if st.button("Refresh Universe", use_container_width=True):
            get_universe(force_refresh=True)
            st.rerun()
        run_btn = st.button("Run Screener", type="primary", use_container_width=True)
        st.caption("Data cached 30 min. Click to refresh.")

    elif page == PAGE_BREADTH:
        st.caption("Live S&P 500 breadth · 15-min cache")
        if st.button("Refresh Breadth Data", use_container_width=True):
            _fetch_sp500_close.clear()
            _fetch_spy_1y.clear()
            _fetch_vix.clear()
            fetch_stockbee_breadth.clear()
            st.rerun()
        if st.session_state.get("breadth_fetched_at"):
            st.caption(f"Last computed: {st.session_state['breadth_fetched_at']}")

    elif page == PAGE_THEMES:
        st.caption("39 theme/sector ETFs · 15-min cache")
        tracker_sort_by = st.selectbox(
            "Sort by",
            TRACKER_SORT_COLUMNS,
            index=1,
            help="Pick the timeframe to rank themes by.",
        )
        if st.button("Refresh Theme Data", use_container_width=True):
            from screener.theme_tracker import fetch_theme_etfs
            fetch_theme_etfs.clear()
            st.rerun()

    elif page == PAGE_NEWS:
        st.caption("Live Alpaca news feed · 60s cache")


# ── App header ───────────────────────────────────────────────────────────────
_HEADERS = {
    PAGE_DASHBOARD:    ("Market Screener", "Dashboard · Pulse · Themes · Stats"),
    PAGE_HOT_SIGNALS:  ("Market Screener", "Hot Signals · Sector RS · VCP · ATR Stack"),
    PAGE_PROXIMITY:    ("Market Screener", "52-Week High Proximity"),
    PAGE_BREADTH:      ("Market Screener", "S&P 500 Market Breadth"),
    PAGE_THEMES:       ("Market Screener", "Theme Rotation Tracker · 39 ETFs"),
    PAGE_NEWS:         ("Market Screener", "Breaking News Scanner"),
}
_t, _s = _HEADERS[page]
render_app_header(_t, _s)


# ── Session State ────────────────────────────────────────────────────────────
if "results" not in st.session_state:
    st.session_state.results = None
if "sector_table" not in st.session_state:
    st.session_state.sector_table = None
if "last_run" not in st.session_state:
    st.session_state.last_run = None
if "stats" not in st.session_state:
    st.session_state.stats = {}
if "scanner_mode_run" not in st.session_state:
    st.session_state.scanner_mode_run = None


# ── Helper functions ─────────────────────────────────────────────────────────
def _signal_tier(r: SignalResult) -> str:
    if r.tt_score >= 4 and r.filters.get("vcp"):
        return "STRONG"
    if r.score >= 3:
        return "MOD"
    return "BASE"


def _proximity_tier(r: ProximityResult) -> str:
    if r.pct_from_high <= 0.01:
        return "AT HIGH"
    if r.pct_from_high <= 0.03:
        return "NEAR"
    return "WITHIN"


def _fmt_mcap(val) -> str:
    if val is None or (isinstance(val, float) and val != val):
        return "—"
    if val >= 1e12:
        return f"${val/1e12:.2f}T"
    if val >= 1e9:
        return f"${val/1e9:.1f}B"
    if val >= 1e6:
        return f"${val/1e6:.0f}M"
    return f"${val:,.0f}"


def signal_results_to_df(results: list[SignalResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        rows.append({
            "Tier": _signal_tier(r),
            "Symbol": r.symbol,
            "Sector": r.sector,
            "Mkt Cap ($B)": (r.market_cap / 1e9) if r.market_cap is not None else float("nan"),
            "Price": r.price,
            "RSI": r.rsi,
            "RS vs SPY": r.rs,
            "TT Score": f"{r.tt_score}/4",
            "Vol Ratio": r.vol_ratio,
            "ATR Stop": r.atr_stop,
            "Target": r.target,
            "R:R": r.rr,
            "Score": r.score,
        })
    return pd.DataFrame(rows)


def proximity_results_to_df(results: list[ProximityResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        rows.append({
            "Tier": _proximity_tier(r),
            "Symbol": r.symbol,
            "Sector": r.sector,
            "ETF": r.etf,
            "Mkt Cap ($B)": (r.market_cap / 1e9) if r.market_cap is not None else float("nan"),
            "Price": r.price,
            "52W High": r.high_52w,
            "% From High": round(r.pct_from_high * 100, 2),
        })
    return pd.DataFrame(rows)


def sector_table_display(df: pd.DataFrame) -> pd.DataFrame:
    display = df.copy()
    display["Breadth %"] = display["breadth_pct"].apply(
        lambda x: f"{x:.1f}%" if x is not None else "N/A"
    )
    display["RS Score"] = display["rs_score"]
    display["Status"] = display["status"].apply(
        lambda s: "HOT" if s == "HOT" else ("watch" if s == "watch" else "cold")
    )
    return display[["rank", "sector", "etf", "RS Score", "Breadth %", "new_highs", "Status"]].rename(
        columns={"rank": "#", "sector": "Sector", "etf": "ETF",
                 "new_highs": "New Highs"}
    )


# ── Run Screener (Hot Signals / 52W Proximity) ───────────────────────────────
if run_btn:
    start_time = time.time()
    progress_bar = st.progress(0, text="Initializing…")

    def update_progress(pct: float, msg: str):
        progress_bar.progress(pct, text=msg)

    st.session_state.scanner_mode_run = page

    if page == PAGE_HOT_SIGNALS:
        with st.spinner("Fetching market data…"):
            update_progress(0.05, "Fetching SPY data…")
            spy_data = fetch_spy()

            if spy_data is None:
                st.error("Failed to fetch SPY data. Check your internet connection.")
                st.stop()

            update_progress(0.08, "Building sector leaderboard…")
            sector_table = build_sector_table(spy_data, n_hot)
            st.session_state.sector_table = sector_table

            if not sector_table.empty:
                sector_table["breadth_ok"] = sector_table["breadth_pct"].apply(
                    lambda x: (x is not None) and (x / 100 >= breadth_thresh)
                )

            results, total_scanned = run_full_universe_screener(
                spy_data=spy_data,
                progress_callback=update_progress,
            )
            st.session_state.results = results
            elapsed = round(time.time() - start_time, 1)
            st.session_state.last_run = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.session_state.stats = {
                "total_scanned": total_scanned,
                "signals_found": len(results),
                "elapsed": elapsed,
            }

    elif page == PAGE_PROXIMITY:
        with st.spinner("Scanning for stocks near 52-week highs…"):
            results, total_scanned = run_proximity_scanner(
                threshold=proximity_pct / 100.0,
                progress_callback=update_progress,
            )
            st.session_state.results = results
            st.session_state.sector_table = None
            elapsed = round(time.time() - start_time, 1)
            st.session_state.last_run = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.session_state.stats = {
                "total_scanned": total_scanned,
                "signals_found": len(results),
                "elapsed": elapsed,
            }

    progress_bar.progress(1.0, text="Done!")
    time.sleep(0.3)
    progress_bar.empty()
    st.rerun()


# ── Page Renderers ───────────────────────────────────────────────────────────

def _render_hot_signals():
    mode_run = st.session_state.scanner_mode_run

    if st.session_state.stats:
        s = st.session_state.stats
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Candidates Scanned", s.get("total_scanned", 0))
        c2.metric("Signals Found", s.get("signals_found", 0))
        c3.metric("Time Elapsed", f"{s.get('elapsed', 0)}s")
        c4.metric("Last Updated", st.session_state.last_run or "—")

    st.subheader("Sector Leaderboard")
    if st.session_state.sector_table is not None and not st.session_state.sector_table.empty:
        display_df = sector_table_display(st.session_state.sector_table)
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "#": st.column_config.NumberColumn(width="small"),
                "RS Score": st.column_config.NumberColumn(format="%.3f"),
                "Status": st.column_config.TextColumn(width="medium"),
            },
        )
        st.caption("RS Score = 0.6×(3mo RS) + 0.4×(6mo RS) vs SPY · scan covers all ~5,000 US-listed tickers")
    else:
        st.info("Sector data will appear after running the screener.")

    results = st.session_state.results

    if mode_run == PAGE_HOT_SIGNALS and results:
        sector_counts = Counter(
            r.sector for r in results if r.sector not in ("—", "Other")
        )
        clusters = [
            (sector, cnt)
            for sector, cnt in sector_counts.most_common()
            if cnt >= 3
        ]
        if clusters:
            st.subheader("Emerging Theme Clusters")
            st.caption("Sectors with 3+ stocks simultaneously passing all filters")
            for sector, cnt in clusters[:6]:
                top = next((r for r in results if r.sector == sector), None)
                top_note = f" · Leader: **{top.symbol}** (RS {top.rs:.2f})" if top else ""
                st.info(f"**{sector}** — {cnt} stocks breaking out{top_note}")

    st.subheader("Signal Results — Full Universe")
    if mode_run == PAGE_HOT_SIGNALS and results is not None:
        if not results:
            st.warning("No stocks passed all filters. Try relaxing thresholds or check market regime.")
        else:
            results_df = signal_results_to_df(results)
            st.dataframe(
                results_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Tier": st.column_config.TextColumn("Tier", width="small"),
                    "Mkt Cap ($B)": st.column_config.NumberColumn(
                        "Mkt Cap ($B)", format="$%.2fB", width="medium",
                    ),
                    "Price": st.column_config.NumberColumn(format="$%.2f"),
                    "RS vs SPY": st.column_config.NumberColumn(format="%.3f"),
                    "ATR Stop": st.column_config.NumberColumn(format="$%.2f"),
                    "Target": st.column_config.NumberColumn(format="$%.2f"),
                    "R:R": st.column_config.NumberColumn(format="%.1f"),
                    "Score": st.column_config.ProgressColumn(
                        "Score", min_value=0, max_value=5, format="%d"
                    ),
                },
            )
            st.caption("STRONG = VCP + TT 4/4  ·  MOD = score ≥ 3  ·  BASE = passes core filters")

            csv_data = results_df.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv_data,
                file_name=f"hot_signals_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
            )

            with st.expander("Filter Breakdown"):
                breakdown_rows = []
                for r in results:
                    row = {"Symbol": r.symbol, "Sector": r.sector}
                    row.update({k: ("PASS" if v else "FAIL") for k, v in r.filters.items()})
                    breakdown_rows.append(row)
                st.dataframe(pd.DataFrame(breakdown_rows), use_container_width=True, hide_index=True)
    else:
        st.info("Click **Run Screener** in the sidebar to begin scanning.")


def _render_proximity():
    if st.session_state.stats and st.session_state.scanner_mode_run == PAGE_PROXIMITY:
        s = st.session_state.stats
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Candidates Scanned", s.get("total_scanned", 0))
        c2.metric("Stocks Found", s.get("signals_found", 0))
        c3.metric("Time Elapsed", f"{s.get('elapsed', 0)}s")
        c4.metric("Last Updated", st.session_state.last_run or "—")

    st.subheader("52-Week High Proximity Results")
    st.caption("Stocks sorted by closeness to their 52-week high — no other filters applied")

    if st.session_state.scanner_mode_run == PAGE_PROXIMITY and st.session_state.results is not None:
        results = st.session_state.results
        if not results:
            st.warning("No stocks found within that threshold. Try increasing the % below 52W high.")
        else:
            results_df = proximity_results_to_df(results)
            st.dataframe(
                results_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Tier": st.column_config.TextColumn("Tier", width="small"),
                    "Mkt Cap ($B)": st.column_config.NumberColumn(
                        "Mkt Cap ($B)", format="$%.2fB", width="medium",
                    ),
                    "Price": st.column_config.NumberColumn(format="$%.2f"),
                    "52W High": st.column_config.NumberColumn(format="$%.2f"),
                    "% From High": st.column_config.NumberColumn(
                        "% From High",
                        help="0% = at the 52-week high",
                        format="%.2f%%",
                        width="small",
                    ),
                },
            )
            st.caption("AT HIGH = within 1%  ·  NEAR = within 3%  ·  WITHIN = passes threshold")

            csv_data = results_df.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv_data,
                file_name=f"52w_proximity_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
            )
    else:
        st.info("Click **Run Screener** in the sidebar to begin scanning.")


# ── Main page dispatch ───────────────────────────────────────────────────────
if page == PAGE_DASHBOARD:
    render_dashboard()
elif page == PAGE_HOT_SIGNALS:
    _render_hot_signals()
elif page == PAGE_PROXIMITY:
    _render_proximity()
elif page == PAGE_BREADTH:
    render_breadth_dashboard()
elif page == PAGE_THEMES:
    render_theme_tracker(sort_by=tracker_sort_by)
elif page == PAGE_NEWS:
    render_news_scanner()


# ── Footer ───────────────────────────────────────────────────────────────────
render_footer(st.session_state.last_run)
