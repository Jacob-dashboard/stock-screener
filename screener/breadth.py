"""
screener/breadth.py — Market Breadth Dashboard

Calculations and Streamlit rendering for the 📊 Market Breadth sidebar mode.
All heavy data fetches are cached with 15-minute TTL via @st.cache_data(ttl=900).

Indicators:
  T2108         — % of S&P 500 above 40d MA (Worden-style)
  % above 50d   — S&P 500
  % above 200d  — S&P 500 regime indicator
  A/D Line      — cumulative advances minus declines, 60 trading days
  McClellan     — 19d EMA − 39d EMA of daily A−D; ±100 thresholds
  New Highs/Lows — 1/5/10/20-day windows across S&P 500
  SPY Regime    — traffic-light: above/below 50d & 200d MA
  VIX           — current level, 20d avg, contango/backwardation note
"""

import logging
import math
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from screener.breadth_stockbee import fetch_stockbee_breadth, latest_stockbee_row

logger = logging.getLogger(__name__)


# ── Colour helpers ──────────────────────────────────────────────────────────

def _t2108_css(val: float) -> str:
    """Worden-style threshold colour."""
    if math.isnan(val):
        return "#8b949e"
    if val < 20:
        return "#3fb950"   # oversold — contrarian bullish
    if val < 40:
        return "#f0883e"   # weak
    if val < 60:
        return "#c9d1d9"   # neutral
    if val < 80:
        return "#79c0ff"   # strong
    return "#f85149"       # overbought — contrarian bearish


def _t2108_label(val: float) -> str:
    if math.isnan(val):
        return "N/A"
    if val < 20:
        return "Oversold — Contrarian Bullish"
    if val < 40:
        return "Weak"
    if val < 60:
        return "Neutral"
    if val < 80:
        return "Strong"
    return "Overbought — Contrarian Bearish"


def _safe(val, fmt=".1f", default="N/A") -> str:
    try:
        if pd.isna(val):
            return default
        return format(float(val), fmt)
    except Exception:
        return default


# ── S&P 500 Constituents ────────────────────────────────────────────────────

@st.cache_data(ttl=86400, show_spinner=False)
def get_sp500_tickers() -> list:
    """Fetch S&P 500 ticker list from Wikipedia. 24-hour TTL. Falls back to ~30 names."""
    try:
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        )
        tickers = tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()
        return [t for t in tickers if isinstance(t, str) and t]
    except Exception as exc:
        logger.warning("Wikipedia S&P 500 fetch failed: %s", exc)
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "UNH",
            "XOM", "JNJ", "V", "PG", "MA", "CVX", "HD", "ABBV", "MRK", "LLY",
            "AVGO", "PEP", "KO", "COST", "ADBE", "TMO", "WMT", "BAC", "MCD", "CRM",
            "ACN", "ORCL", "NFLX", "AMD", "INTC", "QCOM", "TXN", "CSCO", "AMAT",
        ]


# ── Heavy data fetches (15-minute TTL) ─────────────────────────────────────

@st.cache_data(ttl=900, show_spinner=False)
def _fetch_sp500_close() -> pd.DataFrame:
    """
    Download 1 year of daily Close prices for all S&P 500 constituents.
    Returns DataFrame: index=Date, columns=ticker symbols.
    """
    tickers = get_sp500_tickers()
    try:
        raw = yf.download(
            tickers,
            period="1y",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        if raw.empty:
            return pd.DataFrame()
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
        # Ensure it's a DataFrame (edge case: single ticker returns Series)
        if isinstance(close, pd.Series):
            close = close.to_frame()
        return close.dropna(axis=1, how="all")
    except Exception as exc:
        logger.error("S&P 500 close fetch failed: %s", exc)
        return pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_spy_1y() -> pd.DataFrame:
    """SPY daily OHLCV for 1 year. 15-minute TTL."""
    try:
        raw = yf.download("SPY", period="1y", auto_adjust=True, progress=False)
        if raw.empty:
            return pd.DataFrame()
        if isinstance(raw.columns, pd.MultiIndex):
            try:
                raw = raw.xs("SPY", axis=1, level=1)
            except Exception:
                raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
        return raw
    except Exception as exc:
        logger.warning("SPY fetch failed: %s", exc)
        return pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_vix() -> pd.DataFrame:
    """VIX and VIX3M close prices for 3 months. 15-minute TTL."""
    try:
        raw = yf.download(
            ["^VIX", "^VIX3M"],
            period="3mo",
            auto_adjust=True,
            progress=False,
        )
        if raw.empty:
            return pd.DataFrame()
        if isinstance(raw.columns, pd.MultiIndex):
            return raw["Close"].dropna(axis=1, how="all")
        return raw
    except Exception as exc:
        logger.warning("VIX fetch failed: %s", exc)
        return pd.DataFrame()


# ── Indicator computations ──────────────────────────────────────────────────

def _pct_above_ma(close_df: pd.DataFrame, period: int) -> float:
    """% of stocks in close_df trading above their N-day SMA. Returns 0–100."""
    if close_df.empty or len(close_df) < period:
        return float("nan")
    ma = close_df.rolling(period).mean().iloc[-1]
    last = close_df.iloc[-1]
    valid = last.notna() & ma.notna()
    if valid.sum() == 0:
        return float("nan")
    return float((last[valid] > ma[valid]).sum() / valid.sum() * 100)


def _ad_line(close_df: pd.DataFrame, days: int = 60) -> pd.Series:
    """Cumulative Advance/Decline line for the last `days` trading sessions."""
    if close_df.empty or len(close_df) < 2:
        return pd.Series(dtype=float)
    recent = close_df.tail(days + 1)
    chg = recent.diff().iloc[1:]
    return ((chg > 0).sum(axis=1) - (chg < 0).sum(axis=1)).cumsum()


def _mcclellan(close_df: pd.DataFrame) -> tuple:
    """
    McClellan Oscillator = 19d EMA − 39d EMA of daily (advances − declines).
    Returns (current_value: float, last_30_days: pd.Series).
    """
    if close_df.empty or len(close_df) < 50:
        return float("nan"), pd.Series(dtype=float)
    history = close_df.tail(min(len(close_df), 252))
    chg = history.diff().iloc[1:]
    ad = (chg > 0).sum(axis=1) - (chg < 0).sum(axis=1)
    osc = ad.ewm(span=19, adjust=False).mean() - ad.ewm(span=39, adjust=False).mean()
    return float(osc.iloc[-1]), osc.tail(30)


def _new_highs_lows(close_df: pd.DataFrame) -> pd.DataFrame:
    """
    Count S&P 500 stocks hitting 52W highs/lows over 1/5/10/20 trading-day windows.
    """
    if close_df.empty or len(close_df) < 252:
        return pd.DataFrame(columns=["Period", "New Highs", "New Lows"])
    roll_high = close_df.rolling(252).max()
    roll_low = close_df.rolling(252).min()
    rows = []
    for p, label in [(1, "1D"), (5, "5D"), (10, "10D"), (20, "20D")]:
        rec = close_df.tail(p)
        rows.append({
            "Period":    label,
            "New Highs": int((rec.max() >= roll_high.iloc[-1] * 0.999).sum()),
            "New Lows":  int((rec.min() <= roll_low.iloc[-1] * 1.001).sum()),
        })
    return pd.DataFrame(rows)


def _spy_regime(spy_df: pd.DataFrame) -> dict:
    """Traffic-light regime: 🟢 both MAs below, 🟡 mixed, 🔴 both MAs above."""
    if spy_df.empty or len(spy_df) < 200:
        return {}
    close = (
        spy_df["Close"].dropna()
        if "Close" in spy_df.columns
        else spy_df.iloc[:, 0].dropna()
    )
    price = float(close.iloc[-1])
    ma50  = float(close.rolling(50).mean().iloc[-1])
    ma200 = float(close.rolling(200).mean().iloc[-1])
    above50, above200 = price > ma50, price > ma200
    if above50 and above200:
        emoji, label = "🟢", "Bull — SPY above both 50d & 200d MA"
    elif above50 or above200:
        emoji, label = "🟡", "Mixed — SPY between 50d and 200d MA"
    else:
        emoji, label = "🔴", "Bear — SPY below both 50d & 200d MA"
    return dict(
        price=price, ma50=ma50, ma200=ma200,
        above50=above50, above200=above200,
        emoji=emoji, label=label,
    )


def _vix_stats(vix_df: pd.DataFrame) -> dict:
    """Current VIX, 20d average, and term-structure note."""
    if vix_df.empty:
        return {}
    vix_col = "^VIX" if "^VIX" in vix_df.columns else (vix_df.columns[0] if len(vix_df.columns) else None)
    if vix_col is None:
        return {}
    vix = vix_df[vix_col].dropna()
    if vix.empty:
        return {}
    cur  = float(vix.iloc[-1])
    ma20 = float(vix.tail(20).mean()) if len(vix) >= 20 else float("nan")
    result = dict(current=cur, ma20=ma20, above_ma=cur > ma20)
    v3m_col = "^VIX3M" if "^VIX3M" in vix_df.columns else None
    if v3m_col:
        v3m = vix_df[v3m_col].dropna()
        if not v3m.empty:
            v3m_cur = float(v3m.iloc[-1])
            result["vix3m"] = v3m_cur
            if cur < v3m_cur:
                result["term_note"] = (
                    f"Contango — VIX {cur:.1f} < VIX3M {v3m_cur:.1f} (normal)"
                )
            else:
                result["term_note"] = (
                    f"Backwardation — VIX {cur:.1f} > VIX3M {v3m_cur:.1f} (stressed)"
                )
    return result


# ── Master fetch ────────────────────────────────────────────────────────────

def get_breadth_data() -> dict:
    """Fetch all data and compute all breadth indicators. Not cached itself."""
    close_df = _fetch_sp500_close()
    spy_df   = _fetch_spy_1y()
    vix_df   = _fetch_vix()
    mccl_val, mccl_ser = _mcclellan(close_df)

    # Stockbee Market Monitor — authoritative daily breadth, 1-hour TTL
    sb_df  = fetch_stockbee_breadth()
    sb_row = latest_stockbee_row(sb_df)

    # Use Stockbee T2108 when available; fall back to yfinance computation
    t2108_yf = _pct_above_ma(close_df, 40)
    t2108 = sb_row.get("t2108") if sb_row.get("t2108") is not None else t2108_yf

    return {
        "fetched_at":    datetime.now(),
        "sp500_count":   len(close_df.columns) if not close_df.empty else 0,
        "t2108":         t2108,
        "t2108_source":  "Stockbee" if sb_row.get("t2108") is not None else "yfinance",
        "pct_above_50":  _pct_above_ma(close_df, 50),
        "pct_above_200": _pct_above_ma(close_df, 200),
        "ad_line":       _ad_line(close_df, 60),
        "mcclellan_val": mccl_val,
        "mcclellan_ser": mccl_ser,
        "new_hl":        _new_highs_lows(close_df),
        "spy_regime":    _spy_regime(spy_df),
        "vix":           _vix_stats(vix_df),
        "stockbee":      sb_row,
        "stockbee_df":   sb_df,
    }


# ── Plotly helpers ──────────────────────────────────────────────────────────

_PLOT_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="#0D1117",
    plot_bgcolor="#161B22",
    font=dict(family="Inter, sans-serif", color="#c9d1d9", size=12),
    height=300,
    margin=dict(l=50, r=50, t=20, b=40),
    xaxis=dict(gridcolor="#21262d", showgrid=True, zeroline=False),
    yaxis=dict(gridcolor="#21262d", showgrid=True, zeroline=False),
    showlegend=False,
)


def _metric_card(title: str, value_html: str, sub: str = "") -> str:
    return f"""
<div style="background:#161B22;border:1px solid #30363d;border-radius:8px;
            padding:16px 18px;height:120px;display:flex;flex-direction:column;
            justify-content:space-between">
  <div style="font-size:0.72em;color:#8b949e;text-transform:uppercase;
              letter-spacing:0.07em;font-family:Inter,sans-serif">{title}</div>
  {value_html}
  <div style="font-size:0.76em;color:#6e7681;font-family:Inter,sans-serif">{sub}</div>
</div>"""


# ── Dashboard renderer ──────────────────────────────────────────────────────

def render_breadth_dashboard() -> None:
    """Full Market Breadth dashboard UI. Called from app.py."""

    st.subheader("📊 Market Breadth Dashboard")

    with st.spinner("Loading S&P 500 breadth data — first load may take ~30 s…"):
        data = get_breadth_data()

    # Save timestamp for sidebar
    st.session_state["breadth_fetched_at"] = data["fetched_at"].strftime("%H:%M:%S")

    n = data["sp500_count"]
    ts = data["fetched_at"].strftime("%H:%M:%S")
    st.caption(
        f"S&P 500 breadth · {n} constituents loaded · "
        f"computed {ts} · cache TTL 15 min"
    )

    # ── Row 1: T2108 | % >50d | % >200d | SPY Regime ───────────────────────
    c1, c2, c3, c4 = st.columns(4)

    t2108 = data["t2108"]
    t2108_src = data.get("t2108_source", "yfinance")
    col = _t2108_css(t2108)
    with c1:
        st.markdown(
            _metric_card(
                "T2108 — % above 40-Day MA",
                f'<div style="font-family:JetBrains Mono,monospace;font-size:2em;'
                f'font-weight:700;color:{col}">{_safe(t2108)}%</div>',
                f"{_t2108_label(t2108)} · via {t2108_src}",
            ),
            unsafe_allow_html=True,
        )

    p50 = data["pct_above_50"]
    c50 = _t2108_css(p50)
    with c2:
        st.markdown(
            _metric_card(
                "% above 50-Day MA",
                f'<div style="font-family:JetBrains Mono,monospace;font-size:2em;'
                f'font-weight:700;color:{c50}">{_safe(p50)}%</div>',
                "S&P 500",
            ),
            unsafe_allow_html=True,
        )

    p200 = data["pct_above_200"]
    c200 = _t2108_css(p200)
    with c3:
        st.markdown(
            _metric_card(
                "% above 200-Day MA",
                f'<div style="font-family:JetBrains Mono,monospace;font-size:2em;'
                f'font-weight:700;color:{c200}">{_safe(p200)}%</div>',
                "Regime indicator",
            ),
            unsafe_allow_html=True,
        )

    regime = data["spy_regime"]
    with c4:
        if regime:
            sub_regime = (
                f"50d ${regime['ma50']:.0f} · 200d ${regime['ma200']:.0f}"
            )
            st.markdown(
                _metric_card(
                    "SPY Regime",
                    f'<div style="font-size:1.9em;line-height:1">{regime["emoji"]}'
                    f' <span style="font-size:0.55em;color:#c9d1d9;vertical-align:middle">'
                    f'{regime["label"].split("—")[0].strip()}</span></div>',
                    sub_regime,
                ),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                _metric_card("SPY Regime", '<div style="color:#8b949e">N/A</div>', ""),
                unsafe_allow_html=True,
            )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Row 2: McClellan | VIX | New Highs table ───────────────────────────
    c1, c2, c3 = st.columns([1, 1, 1])

    mccl = data["mcclellan_val"]
    mccl_col = (
        "#3fb950" if (not math.isnan(mccl) and mccl > 100)
        else ("#f85149" if (not math.isnan(mccl) and mccl < -100)
              else "#c9d1d9")
    )
    mccl_lbl = (
        "Overbought" if (not math.isnan(mccl) and mccl > 100)
        else ("Oversold" if (not math.isnan(mccl) and mccl < -100)
              else ("Neutral" if not math.isnan(mccl) else "N/A"))
    )
    with c1:
        st.markdown(
            _metric_card(
                "McClellan Oscillator",
                f'<div style="font-family:JetBrains Mono,monospace;font-size:2em;'
                f'font-weight:700;color:{mccl_col}">{_safe(mccl, ".0f")}</div>',
                f"{mccl_lbl} · thresholds ±100",
            ),
            unsafe_allow_html=True,
        )

    vix = data["vix"]
    with c2:
        if vix:
            vc = vix.get("current", float("nan"))
            vm = vix.get("ma20", float("nan"))
            vix_col = (
                "#f85149" if (not math.isnan(vc) and vc > 30)
                else ("#f0883e" if (not math.isnan(vc) and vc > 20)
                      else "#3fb950")
            )
            term = vix.get("term_note", "")
            # Trim long term note
            term_short = term[:55] + "…" if len(term) > 55 else term
            st.markdown(
                _metric_card(
                    "VIX",
                    f'<div style="font-family:JetBrains Mono,monospace;font-size:2em;'
                    f'font-weight:700;color:{vix_col}">{_safe(vc)}</div>',
                    f"20d avg: {_safe(vm)} · {term_short}",
                ),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                _metric_card("VIX", '<div style="color:#8b949e">N/A</div>', ""),
                unsafe_allow_html=True,
            )

    hl_df = data["new_hl"]
    with c3:
        st.markdown(
            '<div style="font-size:0.72em;color:#8b949e;text-transform:uppercase;'
            'letter-spacing:0.07em;margin-bottom:6px">New 52W Highs / Lows — S&P 500</div>',
            unsafe_allow_html=True,
        )
        if not hl_df.empty:
            st.dataframe(
                hl_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Period":    st.column_config.TextColumn("Window", width="small"),
                    "New Highs": st.column_config.NumberColumn("🟢 Highs", width="small"),
                    "New Lows":  st.column_config.NumberColumn("🔴 Lows",  width="small"),
                },
                height=175,
            )
        else:
            st.caption("Need 252+ days of history")

    # ── Stockbee Market Monitor row ─────────────────────────────────────────
    sb = data.get("stockbee", {})
    if sb:
        st.markdown("---")
        st.markdown(
            '<div style="font-size:0.72em;color:#8b949e;text-transform:uppercase;'
            'letter-spacing:0.07em;margin-bottom:10px">'
            'Stockbee Market Monitor — Daily Momentum Counts</div>',
            unsafe_allow_html=True,
        )
        sc1, sc2, sc3, sc4, sc5 = st.columns(5)

        def _sb_card(title: str, up_val, dn_val, up_label="Up", dn_label="Down") -> str:
            up_s = _safe(up_val, ".0f")
            dn_s = _safe(dn_val, ".0f")
            return (
                f'<div style="background:#161B22;border:1px solid #30363d;border-radius:8px;'
                f'padding:12px 14px">'
                f'<div style="font-size:0.68em;color:#8b949e;text-transform:uppercase;'
                f'letter-spacing:0.06em;margin-bottom:6px">{title}</div>'
                f'<div style="display:flex;gap:16px">'
                f'<div><span style="font-size:1.3em;font-weight:700;color:#3fb950;'
                f'font-family:JetBrains Mono,monospace">{up_s}</span>'
                f'<div style="font-size:0.65em;color:#8b949e">{up_label}</div></div>'
                f'<div><span style="font-size:1.3em;font-weight:700;color:#f85149;'
                f'font-family:JetBrains Mono,monospace">{dn_s}</span>'
                f'<div style="font-size:0.65em;color:#8b949e">{dn_label}</div></div>'
                f'</div></div>'
            )

        with sc1:
            st.markdown(
                _sb_card("4% Breakouts Today",
                         sb.get("up_4pct"), sb.get("dn_4pct")),
                unsafe_allow_html=True,
            )
        with sc2:
            r5 = sb.get("ratio_5d")
            r5_col = "#3fb950" if (r5 and r5 >= 2) else ("#f0883e" if (r5 and r5 >= 1) else "#f85149")
            st.markdown(
                f'<div style="background:#161B22;border:1px solid #30363d;border-radius:8px;'
                f'padding:12px 14px">'
                f'<div style="font-size:0.68em;color:#8b949e;text-transform:uppercase;'
                f'letter-spacing:0.06em;margin-bottom:6px">5-Day Up/Down Ratio</div>'
                f'<div style="font-size:1.6em;font-weight:700;color:{r5_col};'
                f'font-family:JetBrains Mono,monospace">{_safe(r5, ".2f")}</div>'
                f'<div style="font-size:0.65em;color:#8b949e">≥2 = bullish thrust</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with sc3:
            r10 = sb.get("ratio_10d")
            r10_col = "#3fb950" if (r10 and r10 >= 2) else ("#f0883e" if (r10 and r10 >= 1) else "#f85149")
            st.markdown(
                f'<div style="background:#161B22;border:1px solid #30363d;border-radius:8px;'
                f'padding:12px 14px">'
                f'<div style="font-size:0.68em;color:#8b949e;text-transform:uppercase;'
                f'letter-spacing:0.06em;margin-bottom:6px">10-Day Up/Down Ratio</div>'
                f'<div style="font-size:1.6em;font-weight:700;color:{r10_col};'
                f'font-family:JetBrains Mono,monospace">{_safe(r10, ".2f")}</div>'
                f'<div style="font-size:0.65em;color:#8b949e">≥2 = sustained thrust</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with sc4:
            st.markdown(
                _sb_card("Up 25%+ in a Month",
                         sb.get("up_25pct_mo"), sb.get("dn_25pct_mo")),
                unsafe_allow_html=True,
            )
        with sc5:
            st.markdown(
                _sb_card("Up 50%+ in a Month",
                         sb.get("up_50pct_mo"), sb.get("dn_50pct_mo")),
                unsafe_allow_html=True,
            )

    # ── Charts ──────────────────────────────────────────────────────────────
    st.markdown("---")
    tab_ad, tab_mccl = st.tabs(["📈 Advance / Decline Line", "〰️ McClellan Oscillator"])

    with tab_ad:
        ad = data["ad_line"]
        if not ad.empty:
            fig = go.Figure()
            # Fill below zero in red, above zero in blue
            fig.add_trace(go.Scatter(
                x=ad.index,
                y=ad.values,
                mode="lines",
                line=dict(color="#79c0ff", width=2),
                fill="tozeroy",
                fillcolor="rgba(121,192,255,0.12)",
            ))
            fig.add_hline(y=0, line_color="#30363d", line_width=1)
            fig.update_layout(**_PLOT_LAYOUT)
            fig.update_yaxes(title=dict(text="Cumulative A−D", font=dict(size=11)))
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "Cumulative advance minus decline · S&P 500 · last 60 trading days"
            )
        else:
            st.info("Advance/Decline data unavailable — need at least 2 days of history.")

    with tab_mccl:
        mccl_ser = data["mcclellan_ser"]
        if not mccl_ser.empty:
            colors = ["#3fb950" if v >= 0 else "#f85149" for v in mccl_ser.values]
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=mccl_ser.index,
                y=mccl_ser.values,
                marker_color=colors,
                marker_line_width=0,
            ))
            fig.add_hline(
                y=100, line_color="#3fb950", line_dash="dot", line_width=1,
                annotation_text="+100 overbought",
                annotation_position="top right",
                annotation_font=dict(color="#3fb950", size=10),
            )
            fig.add_hline(
                y=-100, line_color="#f85149", line_dash="dot", line_width=1,
                annotation_text="-100 oversold",
                annotation_position="bottom right",
                annotation_font=dict(color="#f85149", size=10),
            )
            fig.add_hline(y=0, line_color="#30363d", line_width=1)
            fig.update_layout(**{**_PLOT_LAYOUT, "margin": dict(l=50, r=120, t=20, b=40)})
            fig.update_yaxes(title=dict(text="Oscillator", font=dict(size=11)))
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "19d EMA − 39d EMA of daily (advances − declines) · last 30 sessions · S&P 500"
            )
        else:
            st.info(
                "McClellan data unavailable — need 50+ trading days of history."
            )

    # ── Footer ───────────────────────────────────────────────────────────────
    st.markdown(
        '<div style="margin-top:24px;font-size:0.7em;color:#6e7681">'
        'T2108 &amp; momentum counts via '
        '<a href="https://stockbee.blogspot.com/p/mm.html" target="_blank" '
        'style="color:#58a6ff">Stockbee Market Monitor</a> · '
        'A/D Line, McClellan, New Highs/Lows, SPY Regime &amp; VIX computed from yfinance.'
        '</div>',
        unsafe_allow_html=True,
    )
