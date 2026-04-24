"""
screener/theme_engine.py — Theme Scanner: score pre-defined sector baskets.

For each basket in THEMES, computes:
  - momentum_score (0–100): % of stocks above both 20d AND 50d MA
  - avg_rs: average RS vs SPY ratio
  - avg_pct_from_high: average distance from 52-week high (%)
  - best_1w / best_1m / best_3m: top performers by period return
  - vol_surge_count: stocks with last-day volume ≥ 2× 20d average
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from screener.data import fetch_daily, get_close, get_volume
from screener.indicators import sma, compute_rs_vs_spy
from screener.themes import THEMES

logger = logging.getLogger(__name__)


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class StockScore:
    symbol: str
    price: float
    above_20d: bool
    above_50d: bool
    rs_vs_spy: float
    pct_from_high: float   # positive = % below high
    ret_1w: float          # % (already ×100)
    ret_1m: float
    ret_3m: float
    vol_surge: bool


@dataclass
class ThemeScore:
    name: str
    momentum_score: float  # 0–100: % stocks above both 20d + 50d MA
    avg_rs: float          # average RS ratio vs SPY
    avg_pct_from_high: float  # average % below 52W high
    best_1w: str           # ticker symbol
    best_1w_ret: float     # %
    best_1m: str
    best_1m_ret: float
    best_3m: str
    best_3m_ret: float
    vol_surge_count: int   # # stocks with vol ≥ 2× 20d avg today
    stock_count: int       # # stocks with valid data
    stocks: list = field(default_factory=list)  # list[StockScore], sorted by RS desc


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_return(close: pd.Series, days: int) -> float:
    """Fractional return over `days` bars (negative = loss)."""
    if len(close) <= days:
        return 0.0
    prev = float(close.iloc[-(days + 1)])
    curr = float(close.iloc[-1])
    if prev <= 0:
        return 0.0
    return (curr - prev) / prev


def _score_theme(
    name: str,
    tickers: list[str],
    daily_data: dict[str, pd.DataFrame],
    spy_close: pd.Series,
) -> ThemeScore:
    """Compute ThemeScore for a single basket."""
    stocks: list[StockScore] = []

    for sym in tickers:
        if sym not in daily_data:
            continue
        df = daily_data[sym]
        try:
            close = get_close(df)
        except Exception:
            continue
        if len(close) < 60:
            continue

        price = float(close.iloc[-1])
        if price < 0.50:
            continue

        # Moving averages
        ma20 = sma(close, 20)
        ma50 = sma(close, 50)
        above_20d = (
            not ma20.dropna().empty and price > float(ma20.dropna().iloc[-1])
        )
        above_50d = (
            not ma50.dropna().empty and price > float(ma50.dropna().iloc[-1])
        )

        # RS vs SPY
        rs_raw = compute_rs_vs_spy(close, spy_close)
        rs_val = round(float(rs_raw), 3) if not np.isnan(rs_raw) else 0.0

        # % from 52-week high
        high_52w = float(close.tail(252).max())
        pct_from_high = (
            round((high_52w - price) / high_52w * 100, 2) if high_52w > 0 else 0.0
        )

        # Period returns (in %)
        ret_1w = round(_safe_return(close, 5) * 100, 2)
        ret_1m = round(_safe_return(close, 21) * 100, 2)
        ret_3m = round(_safe_return(close, 63) * 100, 2)

        # Volume surge: last bar vs 20d average
        try:
            vol = get_volume(df)
            avg_vol = float(vol.iloc[-21:-1].mean()) if len(vol) >= 21 else float(vol.mean())
            last_vol = float(vol.iloc[-1])
            vol_surge = avg_vol > 0 and (last_vol / avg_vol) >= 2.0
        except Exception:
            vol_surge = False

        stocks.append(StockScore(
            symbol=sym,
            price=round(price, 2),
            above_20d=above_20d,
            above_50d=above_50d,
            rs_vs_spy=rs_val,
            pct_from_high=pct_from_high,
            ret_1w=ret_1w,
            ret_1m=ret_1m,
            ret_3m=ret_3m,
            vol_surge=vol_surge,
        ))

    if not stocks:
        return ThemeScore(
            name=name,
            momentum_score=0.0,
            avg_rs=0.0,
            avg_pct_from_high=0.0,
            best_1w="—", best_1w_ret=0.0,
            best_1m="—", best_1m_ret=0.0,
            best_3m="—", best_3m_ret=0.0,
            vol_surge_count=0,
            stock_count=0,
            stocks=[],
        )

    # Momentum score: % of stocks above BOTH 20d AND 50d MA
    both_above = sum(1 for s in stocks if s.above_20d and s.above_50d)
    momentum_score = round(100.0 * both_above / len(stocks), 1)

    # Averages
    rs_list = [s.rs_vs_spy for s in stocks]
    avg_rs = round(float(np.mean(rs_list)), 3)
    avg_pct_from_high = round(float(np.mean([s.pct_from_high for s in stocks])), 2)

    # Best performers
    by_1w = max(stocks, key=lambda s: s.ret_1w)
    by_1m = max(stocks, key=lambda s: s.ret_1m)
    by_3m = max(stocks, key=lambda s: s.ret_3m)

    vol_surge_count = sum(1 for s in stocks if s.vol_surge)

    return ThemeScore(
        name=name,
        momentum_score=momentum_score,
        avg_rs=avg_rs,
        avg_pct_from_high=avg_pct_from_high,
        best_1w=by_1w.symbol,
        best_1w_ret=by_1w.ret_1w,
        best_1m=by_1m.symbol,
        best_1m_ret=by_1m.ret_1m,
        best_3m=by_3m.symbol,
        best_3m_ret=by_3m.ret_3m,
        vol_surge_count=vol_surge_count,
        stock_count=len(stocks),
        stocks=sorted(stocks, key=lambda s: -s.rs_vs_spy),
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def scan_all_themes(
    spy_close: pd.Series,
    progress_callback=None,
) -> list[ThemeScore]:
    """
    Score all themes in THEMES against the current market.

    Downloads daily data for all unique tickers across every basket in a
    single batch call (cached 30 min), then computes metrics per basket.

    Args:
        spy_close: SPY daily close series for RS computation.
        progress_callback: Optional (pct: float, msg: str) -> None.

    Returns:
        List of ThemeScore objects sorted by momentum_score descending.
    """
    # Deduplicate tickers across all themes
    all_tickers = sorted({t for tickers in THEMES.values() for t in tickers})
    n_tickers = len(all_tickers)

    if progress_callback:
        progress_callback(0.05, f"Fetching data for {n_tickers} theme stocks…")

    daily_data = fetch_daily(tuple(all_tickers))

    results: list[ThemeScore] = []
    n_themes = len(THEMES)

    for i, (name, tickers) in enumerate(THEMES.items()):
        pct = 0.15 + 0.80 * (i / n_themes)
        if progress_callback:
            progress_callback(pct, f"Scoring: {name}…")

        theme = _score_theme(name, tickers, daily_data, spy_close)
        results.append(theme)

    results.sort(key=lambda r: -r.momentum_score)
    return results
