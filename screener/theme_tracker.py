"""
screener/theme_tracker.py — Theme Rotation Tracker

Tracks 39 sector/theme ETFs across 5 timeframes (1D, 1W, 1M, 3M, YTD) and
detects rotation: where money is flowing IN vs OUT, which themes are leading
vs lagging, and how rankings shift week-over-week.

Inspired by Jacob's TradingView Pine Script "Theme Tracker", with rotation
analysis layered on top.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

logger = logging.getLogger(__name__)


# ── Theme → ETF map ────────────────────────────────────────────────────────────

THEME_ETFS: dict[str, str] = {
    "AI": "BOTZ",
    "Biotech": "XBI",
    "Bitcoin Miners": "WGMI",
    "China Internet": "KWEB",
    "Cybersecurity": "HACK",
    "Aerospace & Defense": "ITA",
    "Airlines": "JETS",
    "Genomics": "ARKG",
    "Gold Miners": "GDX",
    "Growth Stocks": "VUG",
    "Health Care": "XLV",
    "Homebuilders": "XHB",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Medical Devices": "IHI",
    "Energy": "XLE",
    "Quantum": "QTUM",
    "Real Estate": "XLRE",
    "Retail": "XRT",
    "Robotics": "ROBO",
    "Semiconductors (SMH)": "SMH",
    "Semiconductors (SOXX)": "SOXX",
    "Silver Miners": "SIL",
    "Social Media": "SOCL",
    "Software": "IGV",
    "Steel": "SLX",
    "Telecom": "IYZ",
    "Transports": "IYT",
    "Utilities": "XLU",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Long Term Treasuries": "TLT",
    "Regional Banks": "KRE",
    "Uranium / Nuclear": "URA",
    "Copper Miners": "COPX",
    "Lithium / Battery": "LIT",
    "Cloud Computing": "SKYY",
    "Space": "ARKX",
    "Emerging Markets": "EEM",
    "Rare Earth Metals": "REMX",
}

SORT_COLUMNS = ["1 Day", "1 Week", "1 Month", "3 Month", "YTD"]

HISTORY_PATH = Path(__file__).resolve().parent.parent / "data" / "theme_rotation_history.json"


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class ThemeRow:
    theme: str
    etf: str
    ret_1d: float       # %
    ret_1w: float
    ret_1m: float
    ret_3m: float
    ret_ytd: float
    rotation: str       # "INFLOW" | "OUTFLOW" | "HOLDING"
    rotation_arrow: str # ↑↑ ↑ → ↓ ↓↓


# ── Data fetch ─────────────────────────────────────────────────────────────────


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_theme_etfs(tickers: tuple[str, ...]) -> dict[str, pd.Series]:
    """
    Batch-download 1y of daily Close for all theme ETFs.
    Returns {ticker: close_series} for tickers with usable data.
    """
    if not tickers:
        return {}

    try:
        raw = yf.download(
            list(tickers),
            period="1y",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        logger.warning(f"Theme ETF batch download failed: {e}")
        return {}

    if raw is None or raw.empty:
        return {}

    out: dict[str, pd.Series] = {}

    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            close_block = raw["Close"]
            for sym in tickers:
                if sym in close_block.columns:
                    s = close_block[sym].dropna()
                    if len(s) >= 30:
                        out[sym] = s
    else:
        # Single ticker case
        if "Close" in raw.columns:
            s = raw["Close"].dropna()
            if len(s) >= 30 and len(tickers) == 1:
                out[tickers[0]] = s

    return out


# ── Return calcs ───────────────────────────────────────────────────────────────


def _pct_change_n(close: pd.Series, n: int) -> float:
    """% change from n bars ago to last bar. NaN if not enough history."""
    if len(close) <= n:
        return float("nan")
    prev = float(close.iloc[-(n + 1)])
    curr = float(close.iloc[-1])
    if prev <= 0:
        return float("nan")
    return (curr / prev - 1.0) * 100.0


def _ytd_return(close: pd.Series) -> float:
    """% change from first trading day of current year to last bar."""
    if close.empty:
        return float("nan")
    last_date = close.index[-1]
    year_start = pd.Timestamp(year=last_date.year, month=1, day=1, tz=close.index.tz)
    in_year = close[close.index >= year_start]
    if in_year.empty:
        return float("nan")
    base = float(in_year.iloc[0])
    curr = float(in_year.iloc[-1])
    if base <= 0:
        return float("nan")
    return (curr / base - 1.0) * 100.0


def _rotation_signal(ret_1w: float, ret_1m: float) -> tuple[str, str]:
    """
    Detect if money is rotating IN, OUT, or HOLDING.

    Compares 1-week pace (ret_1w / 5) against 1-month pace (ret_1m / 21)
    to decide whether the theme is accelerating or decelerating.

    Returns (label, arrow).
    """
    if np.isnan(ret_1w) or np.isnan(ret_1m):
        return "HOLDING", "→"

    weekly_pace = ret_1w / 5.0          # avg %/day over the past week
    monthly_pace = ret_1m / 21.0        # avg %/day over the past month
    accel = weekly_pace - monthly_pace  # >0 = accelerating, <0 = decelerating

    # Strong inflow: positive return AND clearly accelerating
    if ret_1w > 0 and accel > 0.15:
        return "INFLOW", "↑↑"
    # Mild inflow: positive return, slight acceleration or just steady gains
    if ret_1w > 0 and accel > 0:
        return "INFLOW", "↑"
    # Strong outflow: negative return AND clearly decelerating
    if ret_1w < 0 and accel < -0.15:
        return "OUTFLOW", "↓↓"
    # Mild outflow: negative return, slight deceleration
    if ret_1w < 0 and accel < 0:
        return "OUTFLOW", "↓"

    return "HOLDING", "→"


def build_theme_rows(close_map: dict[str, pd.Series]) -> list[ThemeRow]:
    """Compute per-theme returns + rotation signal."""
    rows: list[ThemeRow] = []
    for theme_name, etf in THEME_ETFS.items():
        s = close_map.get(etf)
        if s is None or s.empty:
            continue

        ret_1d = _pct_change_n(s, 1)
        ret_1w = _pct_change_n(s, 5)
        ret_1m = _pct_change_n(s, 21)
        ret_3m = _pct_change_n(s, 63)
        ret_ytd = _ytd_return(s)

        rotation, arrow = _rotation_signal(ret_1w, ret_1m)

        rows.append(ThemeRow(
            theme=theme_name,
            etf=etf,
            ret_1d=round(ret_1d, 2) if not np.isnan(ret_1d) else float("nan"),
            ret_1w=round(ret_1w, 2) if not np.isnan(ret_1w) else float("nan"),
            ret_1m=round(ret_1m, 2) if not np.isnan(ret_1m) else float("nan"),
            ret_3m=round(ret_3m, 2) if not np.isnan(ret_3m) else float("nan"),
            ret_ytd=round(ret_ytd, 2) if not np.isnan(ret_ytd) else float("nan"),
            rotation=rotation,
            rotation_arrow=arrow,
        ))
    return rows


# ── Week-over-week ranking history ─────────────────────────────────────────────


def _load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {"snapshots": []}
    try:
        with HISTORY_PATH.open() as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not read rotation history: {e}")
        return {"snapshots": []}


def _save_history(hist: dict) -> None:
    try:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY_PATH.open("w") as f:
            json.dump(hist, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not write rotation history: {e}")


def _ranking_by_1w(rows: list[ThemeRow]) -> dict[str, int]:
    """Rank by 1W return desc → {theme: rank} (1-indexed). NaN sorts last."""
    sortable = [(r.theme, r.ret_1w if not np.isnan(r.ret_1w) else -1e9) for r in rows]
    sortable.sort(key=lambda t: -t[1])
    return {theme: i + 1 for i, (theme, _) in enumerate(sortable)}


def update_and_compare_history(rows: list[ThemeRow]) -> dict[str, int]:
    """
    Persist the current 1W ranking and return {theme: rank_change_vs_last_week}.
    Positive = improved (moved up the leaderboard), negative = dropped.

    Snapshots older than the most-recent one taken ≥6 days ago are used as the
    "last week" baseline. If no such snapshot exists, returns {} (no deltas).
    """
    today = datetime.utcnow().date().isoformat()
    current_ranks = _ranking_by_1w(rows)

    hist = _load_history()
    snapshots = hist.get("snapshots", [])

    # Find the most-recent snapshot at least 6 days old
    cutoff = (datetime.utcnow() - timedelta(days=6)).date().isoformat()
    baseline = None
    for snap in reversed(snapshots):
        if snap["date"] <= cutoff:
            baseline = snap
            break

    deltas: dict[str, int] = {}
    if baseline:
        prev_ranks = baseline.get("ranks", {})
        for theme, rank in current_ranks.items():
            if theme in prev_ranks:
                # positive = moved UP (lower rank number is better)
                deltas[theme] = prev_ranks[theme] - rank

    # Append today's snapshot (replace if same date)
    snapshots = [s for s in snapshots if s["date"] != today]
    snapshots.append({"date": today, "ranks": current_ranks})
    # Keep last 60 snapshots (~2 months)
    snapshots = snapshots[-60:]
    _save_history({"snapshots": snapshots})

    return deltas


# ── Color helpers ──────────────────────────────────────────────────────────────


def _color_1d(val: float) -> str:
    """Background color for 1-day % cell."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return ""
    if val >= 7:
        return "background-color: #0d6e2c; color: #fff;"      # dark green
    if val >= 3:
        return "background-color: #1f9d55; color: #fff;"      # medium green
    if val > 0:
        return "background-color: #2d4f3a; color: #d4f1d8;"   # light green
    if val == 0:
        return ""
    if val > -3:
        return "background-color: #5a3030; color: #fad8d8;"   # light red
    if val > -7:
        return "background-color: #b03030; color: #fff;"      # medium red
    if val <= -20:
        return "background-color: #5c0000; color: #fff;"      # very dark red
    return "background-color: #8b1a1a; color: #fff;"          # dark red


def _color_period(val: float) -> str:
    """Background color for weekly+ % cells (1W, 1M, 3M, YTD)."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return ""
    if val >= 15:
        return "background-color: #0d6e2c; color: #fff;"
    if val >= 5:
        return "background-color: #1f9d55; color: #fff;"
    if val > 0:
        return "background-color: #2d4f3a; color: #d4f1d8;"
    if val == 0:
        return ""
    if val > -5:
        return "background-color: #5a3030; color: #fad8d8;"
    if val > -15:
        return "background-color: #b03030; color: #fff;"
    return "background-color: #5c0000; color: #fff;"


def _color_rotation(val: str) -> str:
    if val == "INFLOW":
        return "color: #3fb950; font-weight: 600;"
    if val == "OUTFLOW":
        return "color: #f85149; font-weight: 600;"
    return "color: #8b949e;"


# ── Plot ───────────────────────────────────────────────────────────────────────


def build_rotation_quadrant(rows: list[ThemeRow]) -> go.Figure:
    """
    Scatter: x = 1M return, y = 3M return.
    Quadrants: Leading (TR), Weakening (TL — was strong, fading short-term),
               Lagging (BL), Improving (BR — was weak, recovering short-term).
    """
    pts = [r for r in rows if not (np.isnan(r.ret_1m) or np.isnan(r.ret_3m))]

    xs = [r.ret_1m for r in pts]
    ys = [r.ret_3m for r in pts]
    labels = [f"{r.theme} ({r.etf})" for r in pts]
    hover = [
        f"<b>{r.theme}</b> ({r.etf})<br>"
        f"1M: {r.ret_1m:+.2f}%<br>"
        f"3M: {r.ret_3m:+.2f}%<br>"
        f"1W: {r.ret_1w:+.2f}%<br>"
        f"Signal: {r.rotation_arrow} {r.rotation}"
        for r in pts
    ]
    colors = [
        "#3fb950" if (r.ret_1m > 0 and r.ret_3m > 0) else
        "#f0883e" if (r.ret_1m > 0 and r.ret_3m <= 0) else
        "#79c0ff" if (r.ret_1m <= 0 and r.ret_3m > 0) else
        "#f85149"
        for r in pts
    ]

    fig = go.Figure()

    fig.add_shape(type="line", x0=0, x1=0, y0=min(ys + [-1]) - 5, y1=max(ys + [1]) + 5,
                  line=dict(color="#30363d", width=1, dash="dot"))
    fig.add_shape(type="line", y0=0, y1=0, x0=min(xs + [-1]) - 5, x1=max(xs + [1]) + 5,
                  line=dict(color="#30363d", width=1, dash="dot"))

    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers+text",
        text=[r.etf for r in pts],
        textposition="top center",
        textfont=dict(size=9, color="#c9d1d9"),
        marker=dict(size=12, color=colors, line=dict(color="#0D1117", width=1)),
        hovertext=hover,
        hoverinfo="text",
        name="Themes",
    ))

    x_max = max(xs + [1])
    x_min = min(xs + [-1])
    y_max = max(ys + [1])
    y_min = min(ys + [-1])

    annotations = [
        dict(x=x_max, y=y_max, text="<b>LEADING</b><br>strong 1M & 3M",
             showarrow=False, xanchor="right", yanchor="top",
             font=dict(color="#3fb950", size=11)),
        dict(x=x_min, y=y_max, text="<b>WEAKENING</b><br>strong 3M, fading 1M",
             showarrow=False, xanchor="left", yanchor="top",
             font=dict(color="#79c0ff", size=11)),
        dict(x=x_min, y=y_min, text="<b>LAGGING</b><br>weak 1M & 3M",
             showarrow=False, xanchor="left", yanchor="bottom",
             font=dict(color="#f85149", size=11)),
        dict(x=x_max, y=y_min, text="<b>IMPROVING</b><br>weak 3M, recovering 1M",
             showarrow=False, xanchor="right", yanchor="bottom",
             font=dict(color="#f0883e", size=11)),
    ]

    fig.update_layout(
        title="Theme Rotation Quadrant (1M vs 3M)",
        xaxis_title="1-Month Return (%)",
        yaxis_title="3-Month Return (%)",
        template="plotly_dark",
        plot_bgcolor="#0D1117",
        paper_bgcolor="#0D1117",
        font=dict(color="#c9d1d9", family="Inter, sans-serif"),
        height=520,
        margin=dict(l=50, r=30, t=50, b=50),
        annotations=annotations,
        showlegend=False,
    )
    fig.update_xaxes(gridcolor="#21262d", zerolinecolor="#30363d")
    fig.update_yaxes(gridcolor="#21262d", zerolinecolor="#30363d")
    return fig


# ── Streamlit renderer ─────────────────────────────────────────────────────────


def _heat_label(green_pct: float) -> str:
    if green_pct >= 70:
        return "Bullish"
    if green_pct < 30:
        return "Bearish"
    return "Neutral"


def render_theme_tracker(sort_by: str = "1 Week") -> None:
    """Main entry point for the Streamlit tab."""
    st.subheader("Theme Rotation Tracker")
    st.caption(
        "39 sector/theme ETFs · 1D / 1W / 1M / 3M / YTD returns · "
        "Rotation signals (INFLOW/OUTFLOW) · 15-min cache"
    )

    with st.spinner("Fetching theme ETF data…"):
        close_map = fetch_theme_etfs(tuple(THEME_ETFS.values()))

    if not close_map:
        st.error("No theme ETF data available. Check your internet connection.")
        return

    rows = build_theme_rows(close_map)
    if not rows:
        st.warning("Could not compute returns for any theme.")
        return

    deltas = update_and_compare_history(rows)

    # ── Top metrics ──────────────────────────────────────────────────────────
    n = len(rows)
    counts = {col: {"green": 0, "red": 0} for col in SORT_COLUMNS}
    field_for = {
        "1 Day": "ret_1d", "1 Week": "ret_1w", "1 Month": "ret_1m",
        "3 Month": "ret_3m", "YTD": "ret_ytd",
    }
    for r in rows:
        for col, attr in field_for.items():
            v = getattr(r, attr)
            if np.isnan(v):
                continue
            if v > 0:
                counts[col]["green"] += 1
            elif v < 0:
                counts[col]["red"] += 1

    valid_1w = [r for r in rows if not np.isnan(r.ret_1w)]
    hottest = max(valid_1w, key=lambda r: r.ret_1w) if valid_1w else None
    coldest = min(valid_1w, key=lambda r: r.ret_1w) if valid_1w else None
    green_1w = counts["1 Week"]["green"]
    green_pct_1w = (green_1w / n * 100) if n else 0
    heat = _heat_label(green_pct_1w)

    c1, c2, c3, c4 = st.columns(4)
    if hottest:
        c1.metric("Hottest (1W)", f"{hottest.theme}", f"{hottest.ret_1w:+.2f}%")
    if coldest:
        c2.metric("Coldest (1W)", f"{coldest.theme}", f"{coldest.ret_1w:+.2f}%")
    c3.metric("Themes Green / Red (1W)", f"{green_1w} / {counts['1 Week']['red']}",
              f"{green_pct_1w:.0f}% green")
    c4.metric("Market Heat (1W)", heat)

    st.divider()

    # ── "Where's the money going?" ───────────────────────────────────────────
    st.subheader("Where's the Money Going?")
    inflows = sorted(
        [r for r in rows if r.rotation == "INFLOW"],
        key=lambda r: -r.ret_1w,
    )[:3]
    outflows = sorted(
        [r for r in rows if r.rotation == "OUTFLOW"],
        key=lambda r: r.ret_1w,
    )[:3]

    col_in, col_out = st.columns(2)
    with col_in:
        st.markdown("**Top Inflows (this week)**")
        if inflows:
            for r in inflows:
                st.markdown(
                    f"- {r.rotation_arrow} **{r.theme}** ({r.etf}) &nbsp;"
                    f"<span style='color:#3fb950'>{r.ret_1w:+.2f}%</span> "
                    f"<span style='color:#8b949e'>1W · 1M {r.ret_1m:+.1f}%</span>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No themes showing INFLOW signal.")
    with col_out:
        st.markdown("**Top Outflows (this week)**")
        if outflows:
            for r in outflows:
                st.markdown(
                    f"- {r.rotation_arrow} **{r.theme}** ({r.etf}) &nbsp;"
                    f"<span style='color:#f85149'>{r.ret_1w:+.2f}%</span> "
                    f"<span style='color:#8b949e'>1W · 1M {r.ret_1m:+.1f}%</span>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No themes showing OUTFLOW signal.")

    if inflows and outflows:
        from_names = ", ".join(r.theme for r in outflows[:2])
        to_names = ", ".join(r.theme for r in inflows[:2])
        st.info(f"**Rotation signal:** Money moving FROM **{from_names}** → TO **{to_names}**")

    st.divider()

    # ── Returns table ────────────────────────────────────────────────────────
    st.subheader("Theme Returns + Rotation")

    sort_attr = field_for.get(sort_by, "ret_1w")
    sorted_rows = sorted(
        rows,
        key=lambda r: getattr(r, sort_attr) if not np.isnan(getattr(r, sort_attr)) else -1e9,
        reverse=True,
    )

    table_rows = []
    for r in sorted_rows:
        wow = deltas.get(r.theme)
        if wow is None:
            wow_str = "—"
        elif wow > 0:
            wow_str = f"↑{wow}"
        elif wow < 0:
            wow_str = f"↓{abs(wow)}"
        else:
            wow_str = "="
        table_rows.append({
            "Theme": r.theme,
            "ETF": r.etf,
            "Rot": r.rotation_arrow,
            "Signal": r.rotation,
            "WoW Rank": wow_str,
            "1 Day": r.ret_1d,
            "1 Week": r.ret_1w,
            "1 Month": r.ret_1m,
            "3 Month": r.ret_3m,
            "YTD": r.ret_ytd,
        })

    df = pd.DataFrame(table_rows)

    styler = (
        df.style
        .map(_color_1d, subset=["1 Day"])
        .map(_color_period, subset=["1 Week", "1 Month", "3 Month", "YTD"])
        .map(_color_rotation, subset=["Signal"])
        .format({
            "1 Day": "{:+.2f}%", "1 Week": "{:+.2f}%", "1 Month": "{:+.2f}%",
            "3 Month": "{:+.2f}%", "YTD": "{:+.2f}%",
        }, na_rep="—")
    )

    st.dataframe(styler, use_container_width=True, hide_index=True, height=min(40 + 35 * len(df), 700))

    st.caption(
        "**Rot arrows:** ↑↑ strong inflow · ↑ mild inflow · → flat · ↓ mild outflow · ↓↓ strong outflow  "
        "·  **WoW Rank:** change vs last week's 1W ranking  "
        "·  Color scale: green = positive, red = negative"
    )

    csv = df.to_csv(index=False)
    st.download_button(
        "Download CSV",
        data=csv,
        file_name=f"theme_rotation_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
    )

    st.divider()

    # ── Quadrant chart ───────────────────────────────────────────────────────
    st.subheader("Rotation Quadrant")
    st.caption(
        "Identifies leadership rotation: **Leading** (TR) is where you want to be, "
        "**Improving** (BR) is where money is starting to flow, **Weakening** (TL) is "
        "where money is leaving, **Lagging** (BL) is to avoid."
    )
    fig = build_rotation_quadrant(rows)
    st.plotly_chart(fig, use_container_width=True)
