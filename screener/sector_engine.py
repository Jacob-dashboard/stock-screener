# screener/sector_engine.py — Sector RS ranking, breadth thrust, new high list

import logging
from typing import Optional
import pandas as pd
import numpy as np

from screener.config import (
    SECTOR_ETFS, SECTOR_TICKERS,
    RS_SHORT_DAYS, RS_LONG_DAYS, RS_SHORT_WEIGHT, RS_LONG_WEIGHT,
    BREADTH_THRESHOLD, BREADTH_MA_PERIOD,
    NEW_HIGH_LOOKBACK, N_HOT_SECTORS,
)
from screener.data import fetch_daily, get_close
from screener.indicators import compute_rs_vs_spy, sma

logger = logging.getLogger(__name__)


def _rs_score(etf_close: pd.Series, spy_close: pd.Series) -> float:
    """Composite RS = 0.6 * 3mo + 0.4 * 6mo."""
    rs3 = compute_rs_vs_spy(etf_close, spy_close, RS_SHORT_DAYS)
    rs6 = compute_rs_vs_spy(etf_close, spy_close, RS_LONG_DAYS)
    if np.isnan(rs3) and np.isnan(rs6):
        return float("nan")
    if np.isnan(rs3):
        return float(rs6)
    if np.isnan(rs6):
        return float(rs3)
    return RS_SHORT_WEIGHT * rs3 + RS_LONG_WEIGHT * rs6


def compute_sector_rs(spy_data: Optional[pd.DataFrame]) -> pd.DataFrame:
    """
    Download sector ETF data and compute composite RS vs SPY.
    Returns DataFrame ranked by rs_score descending.
    """
    if spy_data is None or spy_data.empty:
        return pd.DataFrame()

    spy_close = get_close(spy_data)
    etf_tickers = tuple(SECTOR_ETFS.keys())
    etf_data = fetch_daily(etf_tickers)

    rows = []
    for etf, sector_name in SECTOR_ETFS.items():
        if etf not in etf_data:
            continue
        try:
            etf_close = get_close(etf_data[etf])
            rs = _rs_score(etf_close, spy_close)
        except Exception as e:
            logger.debug(f"RS failed for {etf}: {e}")
            rs = float("nan")
        rows.append({"etf": etf, "sector": sector_name, "rs_score": rs})

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).dropna(subset=["rs_score"])
    df = df.sort_values("rs_score", ascending=False).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)
    return df


def compute_breadth(etf: str, etf_data: dict[str, pd.DataFrame]) -> float:
    """
    % of sector tickers trading above their 50d SMA.
    Returns float 0-1, or NaN if no data.
    """
    tickers = SECTOR_TICKERS.get(etf, [])
    if not tickers:
        return float("nan")

    above = 0
    valid = 0
    for sym in tickers:
        if sym not in etf_data:
            continue
        try:
            close = get_close(etf_data[sym])
            if len(close) < BREADTH_MA_PERIOD:
                continue
            ma = close.rolling(BREADTH_MA_PERIOD).mean().iloc[-1]
            valid += 1
            if close.iloc[-1] > ma:
                above += 1
        except Exception:
            continue

    return above / valid if valid > 0 else float("nan")


def compute_new_highs(etf: str, etf_data: dict[str, pd.DataFrame]) -> int:
    """Count tickers making 52-week highs (within 3% of 252d high)."""
    tickers = SECTOR_TICKERS.get(etf, [])
    count = 0
    for sym in tickers:
        if sym not in etf_data:
            continue
        try:
            close = get_close(etf_data[sym])
            lookback = min(NEW_HIGH_LOOKBACK * 5, len(close))  # ~252 trading days
            if lookback < 20:
                continue
            high_252 = close.iloc[-lookback:].max()
            if close.iloc[-1] >= high_252 * 0.97:
                count += 1
        except Exception:
            continue
    return count


def build_sector_table(spy_data: Optional[pd.DataFrame], n_hot: int = N_HOT_SECTORS) -> pd.DataFrame:
    """
    Full sector leaderboard with RS, breadth, new highs, and status.
    Fetches stock data for all sectors at once (batch).
    """
    if spy_data is None or spy_data.empty:
        return pd.DataFrame()

    # Compute ETF RS scores
    sector_rs = compute_sector_rs(spy_data)
    if sector_rs.empty:
        return pd.DataFrame()

    # Batch fetch all stock tickers needed for breadth/new-highs
    all_tickers = set()
    for tickers in SECTOR_TICKERS.values():
        all_tickers.update(tickers)
    stock_data = fetch_daily(tuple(sorted(all_tickers)))

    rows = []
    for _, row in sector_rs.iterrows():
        etf = row["etf"]
        breadth = compute_breadth(etf, stock_data)
        new_highs = compute_new_highs(etf, stock_data)
        rank = int(row["rank"])

        if rank <= n_hot:
            status = "HOT"
        elif row["rs_score"] >= 1.0:
            status = "watch"
        else:
            status = "cold"

        rows.append({
            "rank": rank,
            "sector": row["sector"],
            "etf": etf,
            "rs_score": round(float(row["rs_score"]), 3),
            "breadth_pct": round(float(breadth) * 100, 1) if not np.isnan(breadth) else None,
            "new_highs": new_highs,
            "status": status,
            "breadth_ok": (not np.isnan(breadth)) and (breadth >= BREADTH_THRESHOLD),
        })

    return pd.DataFrame(rows)
