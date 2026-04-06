# screener/data.py — yfinance data fetching with caching

import logging
from typing import Optional
import pandas as pd
import yfinance as yf
import streamlit as st

from screener.config import CACHE_TTL, DATA_PERIOD, WEEKLY_DATA_PERIOD

logger = logging.getLogger(__name__)


def _flatten(df: pd.DataFrame, sym: str) -> pd.DataFrame:
    """
    Flatten multi-index columns that newer yfinance returns.
    ('Close','NVDA') -> 'Close'  for any ticker.
    """
    if not isinstance(df.columns, pd.MultiIndex):
        return df
    # xs by ticker at level 1 when it's still multi-index
    try:
        flat = df.xs(sym, axis=1, level=1)
        flat.columns = [str(c) for c in flat.columns]
        return flat
    except Exception:
        # Fallback: just drop the ticker level
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return df


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def fetch_daily(tickers: tuple[str, ...], period: str = DATA_PERIOD) -> dict[str, pd.DataFrame]:
    """
    Batch-download daily OHLCV for a list of tickers.
    Returns {ticker: DataFrame} with columns [Open, High, Low, Close, Volume].
    Skips tickers with insufficient data.
    """
    if not tickers:
        return {}

    ticker_list = list(tickers)
    result: dict[str, pd.DataFrame] = {}

    try:
        raw = yf.download(
            ticker_list,
            period=period,
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        logger.warning(f"Batch download failed: {e}")
        return {}

    if raw.empty:
        return {}

    for sym in ticker_list:
        try:
            df = _flatten(raw, sym).copy()
            df = df.dropna(how="all")
            if not df.empty and len(df) >= 20:
                result[sym] = df
        except Exception as e:
            logger.debug(f"Skipping {sym}: {e}")

    return result


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def fetch_weekly(tickers: tuple[str, ...], period: str = WEEKLY_DATA_PERIOD) -> dict[str, pd.DataFrame]:
    """
    Batch-download weekly OHLCV for VCP inside-bar detection.
    """
    if not tickers:
        return {}

    ticker_list = list(tickers)
    result: dict[str, pd.DataFrame] = {}

    try:
        raw = yf.download(
            ticker_list,
            period=period,
            interval="1wk",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        logger.warning(f"Weekly batch download failed: {e}")
        return {}

    if raw.empty:
        return {}

    for sym in ticker_list:
        try:
            df = _flatten(raw, sym).copy()
            df = df.dropna(how="all")
            if not df.empty and len(df) >= 5:
                result[sym] = df
        except Exception as e:
            logger.debug(f"Skipping weekly {sym}: {e}")

    return result


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def fetch_spy() -> Optional[pd.DataFrame]:
    """Fetch SPY daily data. Returns None on failure."""
    data = fetch_daily(("SPY",))
    return data.get("SPY")


def get_close(df: pd.DataFrame) -> pd.Series:
    """Safely extract Close series from a DataFrame."""
    if "Close" in df.columns:
        return df["Close"].dropna()
    if "Adj Close" in df.columns:
        return df["Adj Close"].dropna()
    raise KeyError("No Close column found")


def get_volume(df: pd.DataFrame) -> pd.Series:
    """Safely extract Volume series."""
    if "Volume" in df.columns:
        return df["Volume"].dropna()
    raise KeyError("No Volume column found")
