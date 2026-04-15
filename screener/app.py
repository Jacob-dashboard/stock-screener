# screener/app.py — Streamlit UI for Hot Theme Stock Screener

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import logging
from datetime import datetime
import pandas as pd
import streamlit as st

from screener.config import N_HOT_SECTORS, RS_STOCK_MIN, RSI_MIN, RSI_MAX, BREADTH_THRESHOLD
from screener.data import fetch_spy
from screener.sector_engine import build_sector_table
from screener.signal_engine import run_screener, run_proximity_scanner, SignalResult, ProximityResult
from screener.news_scanner import render_news_scanner
from screener.universe import get_universe, universe_cache_info
from screener.breadth import (
    render_breadth_dashboard,
    _fetch_sp500_close,
    _fetch_spy_1y,
    _fetch_vix,
)
from screener.ui.theme import inject_theme, render_app_header, render_sidebar_brand, render_footer

logging.basicConfig(level=logging.WARNING)

st.set_page_config(
    page_title="Hot Theme Stock Screener",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Inject custom theme CSS ───────────────────────────────────────────────────
inject_theme()


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    render_sidebar_brand()

    scanner_mode = st.radio(
        "Scanner Mode",
        ["🔥 Hot Theme Signals", "📍 52-Week High Proximity", "📊 Market Breadth"],
        help=(
            "**Hot Theme**: full 10-filter signal stack (sector RS, RSI, Trend Template, VCP, ATR R:R)\n\n"
            "**52-Week High Proximity**: standalone scan — finds every stock within X% of its yearly high\n\n"
            "**Market Breadth**: live S&P 500 breadth dashboard — T2108, A/D Line, McClellan, VIX"
        ),
    )
    st.divider()

    if scanner_mode == "🔥 Hot Theme Signals":
        st.caption("Paper mode — thresholds relaxed vs live bot")
        n_hot = st.slider(
            "Sectors to Scan",
            min_value=1, max_value=22, value=N_HOT_SECTORS,
            help="Number of sectors to scan by RS rank. Set to 22 to scan all."
        )
        st.subheader("Threshold Overrides")
        rs_min = st.number_input("Min Stock RS", min_value=0.8, max_value=2.0,
                                 value=float(RS_STOCK_MIN), step=0.05)
        rsi_lo = st.number_input("RSI Min", min_value=30, max_value=65, value=RSI_MIN)
        rsi_hi = st.number_input("RSI Max", min_value=60, max_value=85, value=RSI_MAX)
        breadth_thresh = st.slider(
            "Breadth Threshold", min_value=0.20, max_value=0.90,
            value=float(BREADTH_THRESHOLD), step=0.05,
            help="% stocks above 50d SMA required for sector to qualify"
        )

    elif scanner_mode == "📍 52-Week High Proximity":
        st.caption("Find stocks trading near their 52-week high")
        proximity_pct = st.slider(
            "Max % below 52W high",
            min_value=1, max_value=40, value=5,
            help="5 = within 5% of the 52-week high. Sorted closest-first."
        )
        info = universe_cache_info()
        if info["cached"] and not info["stale"]:
            st.caption(f"Universe: {info['count']:,} tickers · cached {info['age_hours']}h ago")
        else:
            st.caption("Universe: will fetch ~5 000 tickers on first run")
        if st.button("🔄 Refresh Universe", use_container_width=True):
            get_universe(force_refresh=True)
            st.rerun()

    else:  # Market Breadth
        st.caption("Live S&P 500 breadth · 15-min cache")
        if st.button("🔄 Refresh Breadth Data", use_container_width=True):
            _fetch_sp500_close.clear()
            _fetch_spy_1y.clear()
            _fetch_vix.clear()
            st.rerun()
        if st.session_state.get("breadth_fetched_at"):
            st.caption(f"Last computed: {st.session_state['breadth_fetched_at']}")

    st.divider()

    # Run button only for scanner modes (breadth auto-renders on select)
    if scanner_mode != "📊 Market Breadth":
        run_btn = st.button("🔍 Run Screener", type="primary", use_container_width=True)
        st.caption("Data cached 30 min. Click to refresh.")
    else:
        run_btn = False


# ── App header ────────────────────────────────────────────────────────────────
render_app_header()

# ── Session State ─────────────────────────────────────────────────────────────
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


# ── Helper functions ──────────────────────────────────────────────────────────

def _row_color_signal(r: SignalResult) -> str:
    if r.tt_score >= 4 and r.filters.get("vcp"):
        return "🟢"
    elif r.score >= 3:
        return "🟡"
    return "⬜"


def _row_color_proximity(r: ProximityResult) -> str:
    if r.pct_from_high <= 0.01:
        return "🟢"
    elif r.pct_from_high <= 0.03:
        return "🟡"
    return "⬜"


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
            "": _row_color_signal(r),
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
            "": _row_color_proximity(r),
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
        lambda s: "🔥 HOT" if s == "HOT" else ("👀 watch" if s == "watch" else "❄️ cold")
    )
    return display[["rank", "sector", "etf", "RS Score", "Breadth %", "new_highs", "Status"]].rename(
        columns={"rank": "#", "sector": "Sector", "etf": "ETF",
                 "new_highs": "New Highs"}
    )


# ── Run Screener ──────────────────────────────────────────────────────────────
if run_btn:
    start_time = time.time()
    progress_bar = st.progress(0, text="Initializing...")

    def update_progress(pct: float, msg: str):
        progress_bar.progress(pct, text=msg)

    st.session_state.scanner_mode_run = scanner_mode

    if scanner_mode == "🔥 Hot Theme Signals":
        with st.spinner("Fetching market data..."):
            update_progress(0.05, "Fetching SPY data...")
            spy_data = fetch_spy()

            if spy_data is None:
                st.error("Failed to fetch SPY data. Check your internet connection.")
                st.stop()

            update_progress(0.10, "Building sector leaderboard...")
            sector_table = build_sector_table(spy_data, n_hot)
            st.session_state.sector_table = sector_table

            if not sector_table.empty:
                sector_table["breadth_ok"] = sector_table["breadth_pct"].apply(
                    lambda x: (x is not None) and (x / 100 >= breadth_thresh)
                )

            results, total_scanned = run_screener(
                spy_data=spy_data,
                sector_table=sector_table,
                n_hot=n_hot,
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

    else:  # 52-Week High Proximity
        with st.spinner("Scanning for stocks near 52-week highs..."):
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


# ── Main tabs ─────────────────────────────────────────────────────────────────
tab_screener, tab_news = st.tabs(["📊 Stock Screener", "📡 News Scanner"])

with tab_screener:

    # ── Breadth mode — auto-renders, no Run button needed ─────────────────────
    if scanner_mode == "📊 Market Breadth":
        render_breadth_dashboard()

    else:
        mode_run = st.session_state.scanner_mode_run

        # Stats row (shown for both scanner modes after a run)
        if st.session_state.stats:
            s = st.session_state.stats
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Candidates Scanned", s.get("total_scanned", 0))
            c2.metric("Signals Found", s.get("signals_found", 0))
            c3.metric("Time Elapsed", f"{s.get('elapsed', 0)}s")
            c4.metric("Last Updated", st.session_state.last_run or "—")

        if mode_run == "🔥 Hot Theme Signals":
            # Sector Leaderboard
            st.subheader("🏆 Sector Leaderboard")
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
                st.caption("🔥 HOT = top-N ranked; RS Score = 0.6×(3mo RS) + 0.4×(6mo RS) vs SPY")
            else:
                st.info("Sector data will appear after running the screener.")

            # Signal results
            st.subheader("🎯 Signal Results")
            if st.session_state.results is not None:
                results = st.session_state.results
                if not results:
                    st.warning("No stocks passed all filters. Try relaxing thresholds or increasing Sectors to Scan.")
                else:
                    results_df = signal_results_to_df(results)
                    st.dataframe(
                        results_df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "": st.column_config.TextColumn("", width="small"),
                            "Mkt Cap ($B)": st.column_config.NumberColumn(
                                "Mkt Cap ($B)",
                                help="Market cap in billions",
                                format="$%.2fB",
                                width="medium",
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
                    st.caption("🟢 Strong signal (VCP + TT 4/4)  |  🟡 Moderate  |  ⬜ Base pass")

                    csv_data = results_df.drop(columns=[""]).to_csv(index=False)
                    st.download_button(
                        label="⬇️ Download CSV",
                        data=csv_data,
                        file_name=f"hot_theme_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv",
                    )

                    with st.expander("🔬 Filter Breakdown"):
                        breakdown_rows = []
                        for r in results:
                            row = {"Symbol": r.symbol, "Sector": r.sector}
                            row.update({k: ("✅" if v else "❌") for k, v in r.filters.items()})
                            breakdown_rows.append(row)
                        st.dataframe(pd.DataFrame(breakdown_rows), use_container_width=True, hide_index=True)
            else:
                st.info("Click **Run Screener** in the sidebar to begin scanning.")

        elif mode_run == "📍 52-Week High Proximity":
            st.subheader("📍 52-Week High Proximity Results")
            st.caption("Stocks sorted by closeness to their 52-week high — no other filters applied")

            if st.session_state.results is not None:
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
                            "": st.column_config.TextColumn("", width="small"),
                            "Mkt Cap ($B)": st.column_config.NumberColumn(
                                "Mkt Cap ($B)",
                                format="$%.2fB",
                                width="medium",
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
                    st.caption("🟢 Within 1% of high  |  🟡 Within 3%  |  ⬜ Within threshold")

                    csv_data = results_df.drop(columns=[""]).to_csv(index=False)
                    st.download_button(
                        label="⬇️ Download CSV",
                        data=csv_data,
                        file_name=f"52w_proximity_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv",
                    )
            else:
                st.info("Click **Run Screener** in the sidebar to begin scanning.")

        else:
            st.info("Select a scanner mode in the sidebar and click **Run Screener** to begin.")

with tab_news:
    render_news_scanner()

# ── Footer ────────────────────────────────────────────────────────────────────
render_footer(st.session_state.last_run)
