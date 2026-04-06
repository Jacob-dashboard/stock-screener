"""
news_scanner.py — Real-time market news scanner using Alpaca News API.
Pulls breaking headlines, scores market impact, and highlights key movers.
"""

from __future__ import annotations

import os
import time
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import streamlit as st
from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest

# ── Credentials ───────────────────────────────────────────────────────────────
# Prefer env vars; fall back to hardcoded keys from the swing bot .env
_API_KEY = os.getenv("ALPACA_API_KEY", "PKJQFB3HKNCN2MJGLMV2VEF7VF")
_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "ACVtfemQZTiA865YGuTEWLBQjhNaSyLQqdGnHgqVNLuj")

# ── High-impact keyword categories ───────────────────────────────────────────
IMPACT_KEYWORDS: dict[str, list[str]] = {
    "🔴 Macro / Policy": [
        "tariff", "tariffs", "trade war", "sanction", "sanctions", "executive order",
        "federal reserve", "fed rate", "rate hike", "rate cut", "interest rate",
        "inflation", "cpi", "pce", "gdp", "recession", "fomc", "powell",
        "treasury", "debt ceiling", "shutdown", "stimulus", "yellen",
        "trump", "biden", "white house", "potus", "congress", "senate",
    ],
    "🟠 Earnings / Guidance": [
        "earnings", "eps", "revenue", "guidance", "outlook", "beat", "miss",
        "quarterly results", "annual results", "forecast", "raised guidance",
        "lowered guidance", "profit warning", "preannounce",
    ],
    "🟡 M&A / Corporate": [
        "merger", "acquisition", "takeover", "buyout", "deal", "acquires",
        "acqui-hire", "spinoff", "spin-off", "ipo", "secondary offering",
        "share buyback", "dividend", "special dividend",
    ],
    "🔵 FDA / Biotech": [
        "fda", "fda approval", "fda approved", "clinical trial", "phase 3",
        "phase 2", "drug approval", "nda", "bla", "pdufa", "rejected",
        "complete response letter", "crl",
    ],
    "🟣 Geo / Energy": [
        "oil", "crude", "opec", "natural gas", "energy", "iran", "russia",
        "ukraine", "china", "north korea", "strait of hormuz", "war", "conflict",
        "ceasefire", "nato",
    ],
    "⚪ Analyst / Upgrades": [
        "upgrade", "downgrade", "price target", "buy rating", "sell rating",
        "overweight", "underweight", "outperform", "underperform", "initiate",
    ],
}

ALL_KEYWORDS = [kw for kws in IMPACT_KEYWORDS.values() for kw in kws]

def _score_headline(headline: str) -> tuple[int, list[str]]:
    """Score headline 0-10 for market impact. Returns (score, matched_categories)."""
    hl = headline.lower()
    matched_cats: list[str] = []
    score = 0

    for cat, keywords in IMPACT_KEYWORDS.items():
        hit = any(kw in hl for kw in keywords)
        if hit:
            matched_cats.append(cat)
            # Weight by category
            if "Macro" in cat:
                score += 4
            elif "FDA" in cat:
                score += 3
            elif "Earnings" in cat:
                score += 3
            elif "Geo" in cat:
                score += 3
            elif "M&A" in cat:
                score += 2
            elif "Analyst" in cat:
                score += 1

    # Boost for urgency words
    urgency_words = ["breaking", "just in", "alert", "flash", "urgent", "halted", "halt",
                     "crash", "surge", "soar", "plunge", "spike", "collapse"]
    if any(w in hl for w in urgency_words):
        score += 2

    return min(score, 10), matched_cats


def _impact_badge(score: int) -> str:
    if score >= 7:
        return "🔴 HIGH"
    elif score >= 4:
        return "🟡 MED"
    elif score >= 2:
        return "🔵 LOW"
    return "⬜ NONE"


@st.cache_data(ttl=60, show_spinner=False)
def fetch_news(hours_back: int = 4, limit: int = 50, symbols: Optional[list[str]] = None) -> pd.DataFrame:
    """Fetch and score recent news from Alpaca."""
    client = NewsClient(api_key=_API_KEY, secret_key=_SECRET_KEY)

    kwargs: dict = {
        "start": datetime.now(timezone.utc) - timedelta(hours=hours_back),
        "limit": limit,
    }
    if symbols:
        kwargs["symbols"] = symbols

    req = NewsRequest(**kwargs)
    result = client.get_news(req)

    # Unpack NewsSet
    raw_items = []
    if result.data:
        for v in result.data.values():
            raw_items.extend(v)

    rows = []
    for n in raw_items:
        score, cats = _score_headline(n.headline)
        rows.append({
            "time": n.created_at.astimezone().strftime("%H:%M"),
            "time_raw": n.created_at,
            "headline": n.headline,
            "source": n.source.replace("benzinga", "Benzinga").replace("reuters", "Reuters"),
            "symbols": ", ".join(n.symbols[:6]) if n.symbols else "—",
            "impact": _impact_badge(score),
            "score": score,
            "categories": " | ".join(cats) if cats else "—",
            "url": n.url or "",
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("time_raw", ascending=False).reset_index(drop=True)
    return df


def render_news_scanner():
    """Render the news scanner tab content."""
    st.subheader("📡 Breaking Market News")
    st.caption("Powered by Alpaca News API · Auto-refreshes every 60s · Scored for market impact")

    # ── Controls ──────────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
    with col1:
        hours_back = st.selectbox("Time window", [1, 2, 4, 8, 24], index=2,
                                  format_func=lambda x: f"Last {x}h")
    with col2:
        min_impact = st.selectbox("Min impact", ["ALL", "LOW+", "MED+", "HIGH only"],
                                  index=0)
    with col3:
        symbol_filter = st.text_input("Filter by symbol", placeholder="AAPL, TSLA, SPY...")
    with col4:
        st.write("")
        st.write("")
        refresh_btn = st.button("🔄 Refresh", use_container_width=True)

    if refresh_btn:
        st.cache_data.clear()

    # ── Fetch ─────────────────────────────────────────────────────────────────
    symbols = None
    if symbol_filter.strip():
        symbols = [s.strip().upper() for s in symbol_filter.split(",") if s.strip()]

    with st.spinner("Fetching latest news..."):
        df = fetch_news(hours_back=hours_back, limit=100, symbols=symbols)

    if df.empty:
        st.info("No news found for the selected window. Try expanding the time range.")
        return

    # ── Filter by impact ──────────────────────────────────────────────────────
    score_map = {"ALL": 0, "LOW+": 2, "MED+": 4, "HIGH only": 7}
    min_score = score_map[min_impact]
    filtered = df[df["score"] >= min_score].copy() if min_score > 0 else df.copy()

    # ── Stats row ─────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Headlines", len(df))
    c2.metric("High Impact 🔴", len(df[df["score"] >= 7]))
    c3.metric("Medium Impact 🟡", len(df[(df["score"] >= 4) & (df["score"] < 7)]))
    c4.metric("Showing", len(filtered))

    st.divider()

    # ── High impact alerts (always shown) ────────────────────────────────────
    high_impact = df[df["score"] >= 7]
    if not high_impact.empty:
        st.markdown("### 🚨 High Impact Alerts")
        for _, row in high_impact.iterrows():
            with st.container():
                col_l, col_r = st.columns([5, 1])
                with col_l:
                    url_part = f"[{row['headline']}]({row['url']})" if row['url'] else row['headline']
                    st.markdown(f"**{url_part}**")
                    st.caption(f"⏰ {row['time']}  ·  📰 {row['source']}  ·  🏷️ {row['symbols']}  ·  {row['categories']}")
                with col_r:
                    st.markdown(f"### {row['impact']}")
        st.divider()

    # ── Full feed table ───────────────────────────────────────────────────────
    st.markdown("### 📰 News Feed")

    display_df = filtered[["time", "impact", "headline", "symbols", "source", "categories"]].copy()
    display_df.columns = ["Time", "Impact", "Headline", "Symbols", "Source", "Categories"]

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        height=500,
        column_config={
            "Time": st.column_config.TextColumn("Time", width="small"),
            "Impact": st.column_config.TextColumn("Impact", width="small"),
            "Headline": st.column_config.TextColumn("Headline", width="large"),
            "Symbols": st.column_config.TextColumn("Symbols", width="medium"),
            "Source": st.column_config.TextColumn("Source", width="small"),
            "Categories": st.column_config.TextColumn("Categories", width="medium"),
        },
    )

    st.caption(f"Last fetched: {datetime.now().strftime('%H:%M:%S')} · Scores: HIGH≥7 | MED≥4 | LOW≥2 | NONE<2")
