"""
screener/dashboard.py — Main landing dashboard.

Three sections:
  A. Market Pulse  — T2108, SPY regime, VIX, % above 50d
  B. Top Themes    — Top 5 by 1M and 3M return
  C. Quick Stats   — themes positive (1W), market breadth snapshot
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import streamlit as st

from screener.breadth import get_breadth_data, _t2108_label, _t2108_css
from screener.theme_tracker import THEME_ETFS, fetch_theme_etfs, build_theme_rows
from screener.ui.theme import render_section_heading


def _metric_card(title: str, value_html: str, sub: str = "") -> str:
    return f"""
<div style="background:#161B22;border:1px solid #30363d;border-radius:8px;
            padding:16px 18px;height:128px;display:flex;flex-direction:column;
            justify-content:space-between;box-shadow:0 1px 2px rgba(0,0,0,0.25)">
  <div style="font-size:0.7em;color:#8b949e;text-transform:uppercase;
              letter-spacing:0.08em;font-family:Inter,sans-serif;font-weight:500">{title}</div>
  {value_html}
  <div style="font-size:0.74em;color:#6e7681;font-family:Inter,sans-serif">{sub}</div>
</div>"""


def _ret_color(val: float) -> str:
    if val is None or (isinstance(val, float) and (math.isnan(val) or np.isnan(val))):
        return "#8b949e"
    if val >= 5:
        return "#3fb950"
    if val > 0:
        return "#56b86b"
    if val == 0:
        return "#c9d1d9"
    if val > -5:
        return "#e89191"
    return "#f85149"


def _safe(val, fmt=".1f", default="—") -> str:
    try:
        if val is None or (isinstance(val, float) and (math.isnan(val) or np.isnan(val))):
            return default
        return format(float(val), fmt)
    except Exception:
        return default


def _render_theme_table(rows, attr: str, title: str) -> None:
    """Render a small HTML table of top 5 themes by the given attribute."""
    valid = [r for r in rows if not np.isnan(getattr(r, attr))]
    top5 = sorted(valid, key=lambda r: getattr(r, attr), reverse=True)[:5]

    body_rows = ""
    for r in top5:
        ret = getattr(r, attr)
        col = _ret_color(ret)
        body_rows += (
            f'<tr>'
            f'<td style="padding:7px 10px;color:#c9d1d9;font-family:Inter,sans-serif">{r.theme}</td>'
            f'<td style="padding:7px 10px;color:#8b949e;font-family:JetBrains Mono,monospace;'
            f'font-size:0.86em">{r.etf}</td>'
            f'<td style="padding:7px 10px;text-align:right;color:{col};'
            f'font-family:JetBrains Mono,monospace;font-weight:600">{ret:+.2f}%</td>'
            f'</tr>'
        )

    st.markdown(
        f"""
<div class="card" style="padding:0;overflow:hidden">
  <div style="padding:12px 16px;border-bottom:1px solid #21262d;
              font-size:0.74em;color:#8b949e;text-transform:uppercase;
              letter-spacing:0.08em;font-weight:600">{title}</div>
  <table style="width:100%;border-collapse:collapse;font-size:0.88em">
    <thead>
      <tr style="background:rgba(13,17,23,0.5);border-bottom:1px solid #21262d">
        <th style="padding:8px 10px;text-align:left;color:#6e7681;font-weight:500;font-size:0.78em">Theme</th>
        <th style="padding:8px 10px;text-align:left;color:#6e7681;font-weight:500;font-size:0.78em">ETF</th>
        <th style="padding:8px 10px;text-align:right;color:#6e7681;font-weight:500;font-size:0.78em">Return</th>
      </tr>
    </thead>
    <tbody>
      {body_rows}
    </tbody>
  </table>
</div>""",
        unsafe_allow_html=True,
    )


def render_dashboard() -> None:
    """Render the main dashboard landing page."""

    # ── Pull data with shared caches ─────────────────────────────────────────
    with st.spinner("Loading market data…"):
        try:
            breadth = get_breadth_data()
        except Exception:
            breadth = None

        try:
            close_map = fetch_theme_etfs(tuple(THEME_ETFS.values()))
            theme_rows = build_theme_rows(close_map) if close_map else []
        except Exception:
            theme_rows = []

    # ── Section A: Market Pulse ──────────────────────────────────────────────
    render_section_heading("Market Pulse")

    c1, c2, c3, c4 = st.columns(4)

    if breadth:
        t2108 = breadth.get("t2108")
        t_col = _t2108_css(t2108) if t2108 is not None else "#8b949e"
        t_label = _t2108_label(t2108) if t2108 is not None else "N/A"
        with c1:
            st.markdown(
                _metric_card(
                    "T2108",
                    f'<div style="font-family:JetBrains Mono,monospace;font-size:2.3em;'
                    f'font-weight:700;color:{t_col};line-height:1">{_safe(t2108, ".1f")}</div>',
                    f"{t_label}",
                ),
                unsafe_allow_html=True,
            )

        regime = breadth.get("spy_regime", {})
        with c2:
            if regime:
                st.markdown(
                    _metric_card(
                        "SPY Regime",
                        f'<div style="font-family:JetBrains Mono,monospace;font-size:2em;'
                        f'font-weight:700;color:{regime["color"]};letter-spacing:0.04em;'
                        f'line-height:1">{regime["regime"]}</div>',
                        f"50d ${regime['ma50']:.0f} · 200d ${regime['ma200']:.0f}",
                    ),
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    _metric_card("SPY Regime", '<div style="color:#8b949e">N/A</div>', ""),
                    unsafe_allow_html=True,
                )

        vix = breadth.get("vix", {}) or {}
        with c3:
            if vix:
                vc = vix.get("current", float("nan"))
                vm = vix.get("ma20", float("nan"))
                vc_col = (
                    "#f85149" if (not math.isnan(vc) and vc > 30)
                    else ("#f0883e" if (not math.isnan(vc) and vc > 20) else "#3fb950")
                )
                rel = "above" if vix.get("above_ma") else "below"
                st.markdown(
                    _metric_card(
                        "VIX",
                        f'<div style="font-family:JetBrains Mono,monospace;font-size:2.3em;'
                        f'font-weight:700;color:{vc_col};line-height:1">{_safe(vc, ".2f")}</div>',
                        f"20d avg {_safe(vm, '.2f')} · {rel} avg",
                    ),
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    _metric_card("VIX", '<div style="color:#8b949e">N/A</div>', ""),
                    unsafe_allow_html=True,
                )

        p50 = breadth.get("pct_above_50")
        p50_col = _t2108_css(p50) if p50 is not None else "#8b949e"
        with c4:
            st.markdown(
                _metric_card(
                    "% Above 50-Day MA",
                    f'<div style="font-family:JetBrains Mono,monospace;font-size:2.3em;'
                    f'font-weight:700;color:{p50_col};line-height:1">{_safe(p50, ".1f")}%</div>',
                    "S&P 500",
                ),
                unsafe_allow_html=True,
            )
    else:
        c1.info("Market Pulse data unavailable.")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Section B: Top Performing Themes ─────────────────────────────────────
    render_section_heading("Top Performing Themes")

    if theme_rows:
        col_a, col_b = st.columns(2)
        with col_a:
            _render_theme_table(theme_rows, "ret_1m", "Top 5 — 1 Month")
        with col_b:
            _render_theme_table(theme_rows, "ret_3m", "Top 5 — 3 Month")
    else:
        st.info("Theme data unavailable.")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Section C: Quick Stats ───────────────────────────────────────────────
    render_section_heading("Quick Stats")

    s1, s2, s3 = st.columns(3)

    if theme_rows:
        valid_1w = [r for r in theme_rows if not np.isnan(r.ret_1w)]
        positive = sum(1 for r in valid_1w if r.ret_1w > 0)
        total = len(valid_1w)
        pct = (positive / total * 100) if total else 0
        s1.metric(
            "Themes Positive (1W)",
            f"{positive} / {total}",
            f"{pct:.0f}%",
        )
    else:
        s1.metric("Themes Positive (1W)", "—", "")

    if breadth and breadth.get("new_hl") is not None and not breadth["new_hl"].empty:
        hl = breadth["new_hl"]
        new_highs_1d = int(hl[hl["Period"] == "1D"]["New Highs"].iloc[0]) if "1D" in hl["Period"].values else 0
        new_highs_5d = int(hl[hl["Period"] == "5D"]["New Highs"].iloc[0]) if "5D" in hl["Period"].values else 0
        s2.metric(
            "S&P 500 New 52W Highs",
            f"{new_highs_1d}",
            f"{new_highs_5d} in last 5 days",
        )
    else:
        s2.metric("S&P 500 New 52W Highs", "—", "")

    if breadth and breadth.get("pct_above_50") is not None:
        p50 = breadth["pct_above_50"]
        p200 = breadth.get("pct_above_200")
        delta = f"{p200:.0f}% above 200d" if p200 is not None and not math.isnan(p200) else ""
        s3.metric(
            "S&P 500 Breadth (>50d)",
            f"{p50:.1f}%",
            delta,
        )
    else:
        s3.metric("S&P 500 Breadth (>50d)", "—", "")

    if breadth:
        ts = breadth["fetched_at"].strftime("%H:%M:%S")
        st.caption(f"Data computed at {ts} · breadth and theme caches refresh every 15 minutes.")
