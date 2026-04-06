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
from screener.signal_engine import run_screener, SignalResult
from screener.news_scanner import render_news_scanner

logging.basicConfig(level=logging.WARNING)

st.set_page_config(
    page_title="Hot Theme Stock Screener",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .metric-card {
        background-color: #1e1e2e;
        border-radius: 6px;
        padding: 10px 16px;
        margin: 4px 0;
    }
    .stDataFrame { font-size: 0.85em; }
</style>
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Screener Controls")
    st.caption("Paper mode — thresholds relaxed vs live bot")

    n_hot = st.slider(
        "Sectors to Scan",
        min_value=1, max_value=22, value=N_HOT_SECTORS,
        help="Number of sectors to scan by RS rank. Set to 22 to scan all."
    )
    st.divider()
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
    st.divider()
    run_btn = st.button("🔍 Run Screener", type="primary", use_container_width=True)
    st.caption("Data cached 30 min. Click to refresh.")

# ── Header ────────────────────────────────────────────────────────────────────
st.title("🔥 Hot Theme Stock Screener")
st.caption("Sector RS ranking | Minervini Trend Template | VCP + ATR signal stack")

# ── Session State ─────────────────────────────────────────────────────────────
if "results" not in st.session_state:
    st.session_state.results = None
if "sector_table" not in st.session_state:
    st.session_state.sector_table = None
if "last_run" not in st.session_state:
    st.session_state.last_run = None
if "stats" not in st.session_state:
    st.session_state.stats = {}


def _row_color(r: SignalResult) -> str:
    """Return color tag for result row."""
    if r.tt_score >= 4 and r.filters.get("vcp"):
        return "🟢"
    elif r.score >= 3:
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


def results_to_df(results: list[SignalResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        rows.append({
            "": _row_color(r),
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

    with st.spinner("Fetching market data..."):
        update_progress(0.05, "Fetching SPY data...")
        spy_data = fetch_spy()

        if spy_data is None:
            st.error("Failed to fetch SPY data. Check your internet connection.")
            st.stop()

        update_progress(0.10, "Building sector leaderboard...")
        sector_table = build_sector_table(spy_data, n_hot)
        st.session_state.sector_table = sector_table

        # Apply breadth threshold override
        if not sector_table.empty:
            sector_table["breadth_ok"] = sector_table["breadth_pct"].apply(
                lambda x: (x is not None) and (x / 100 >= breadth_thresh)
            )

        # Run signals
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

    progress_bar.progress(1.0, text="Done!")
    time.sleep(0.3)
    progress_bar.empty()
    st.rerun()


# ── Display ───────────────────────────────────────────────────────────────────

tab_screener, tab_news = st.tabs(["📊 Stock Screener", "📡 News Scanner"])

with tab_screener:
    # 1) Sector Leaderboard
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

    # 2) Screener Results
    st.subheader("🎯 Screener Results")

    if st.session_state.stats:
        s = st.session_state.stats
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Candidates Scanned", s.get("total_scanned", 0))
        c2.metric("Signals Found", s.get("signals_found", 0))
        c3.metric("Time Elapsed", f"{s.get('elapsed', 0)}s")
        c4.metric("Last Updated", st.session_state.last_run or "—")

    if st.session_state.results is not None:
        results = st.session_state.results

        if not results:
            st.warning("No stocks passed all 10 filters. Try relaxing thresholds or increasing N_HOT_SECTORS.")
        else:
            results_df = results_to_df(results)

            st.dataframe(
                results_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "": st.column_config.TextColumn("", width="small"),
                    "Mkt Cap ($B)": st.column_config.NumberColumn(
                        "Mkt Cap ($B)",
                        help="Market cap in billions — click header to sort smallest→largest",
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

            # Download CSV
            csv_data = results_df.drop(columns=[""]).to_csv(index=False)
            st.download_button(
                label="⬇️ Download CSV",
                data=csv_data,
                file_name=f"screener_results_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
            )

            # Filter breakdown expander
            with st.expander("🔬 Filter Breakdown"):
                breakdown_rows = []
                for r in results:
                    row = {"Symbol": r.symbol, "Sector": r.sector}
                    row.update({k: ("✅" if v else "❌") for k, v in r.filters.items()})
                    breakdown_rows.append(row)
                st.dataframe(pd.DataFrame(breakdown_rows), use_container_width=True, hide_index=True)
    else:
        st.info("Click **Run Screener** in the sidebar to begin scanning.")

with tab_news:
    render_news_scanner()

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "📋 Paper mode — thresholds relaxed vs live bot  |  "
    "Data via Alpaca  |  Not financial advice  |  "
    "Filters: Sector RS · Breadth · Stock RS · RSI · MACD · Price/MA/ROC · VPA · VCP · Trend Template · ATR R:R"
)
