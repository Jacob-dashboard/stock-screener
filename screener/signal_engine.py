# screener/signal_engine.py — Full 10-filter buy signal logic + 52W proximity scanner

import logging
import time
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd
import yfinance as yf

from screener.config import (
    SPY_MA_PERIOD,
    RS_STOCK_MIN,
    BREADTH_THRESHOLD,
    SECTOR_ETFS,
    SECTOR_TICKERS,
)
from screener.data import fetch_daily, fetch_weekly, get_close
from screener.indicators import (
    check_rsi,
    check_macd,
    check_price_ma_roc,
    check_vpa,
    check_vcp,
    compute_trend_template,
    check_atr_rr,
    compute_rs_vs_spy,
    sma,
)


logger = logging.getLogger(__name__)


# ── Hot Theme signal result ────────────────────────────────────────────────────

@dataclass
class SignalResult:
    symbol: str
    sector: str
    etf: str
    price: float
    rsi: float
    rs: float
    tt_score: int
    vol_ratio: float
    atr_stop: float
    target: float
    rr: float
    market_cap: Optional[float] = None
    # Composite score: higher = stronger signal
    score: int = 0
    # Filter breakdown
    filters: dict = field(default_factory=dict)


# ── 52-Week High Proximity result ──────────────────────────────────────────────

@dataclass
class ProximityResult:
    symbol: str
    sector: str
    etf: str
    price: float
    high_52w: float
    pct_from_high: float   # 0.0 = AT the high, 0.05 = 5% below
    market_cap: Optional[float] = None


# ── Shared utilities ───────────────────────────────────────────────────────────

def check_spy_regime(spy_data: pd.DataFrame) -> tuple[bool, float, float]:
    """
    SPY must be above 50d SMA.
    Returns (regime_ok, spy_price, spy_ma50).
    """
    try:
        close = get_close(spy_data)
        ma50 = sma(close, SPY_MA_PERIOD)
        price = float(close.iloc[-1])
        ma_val = float(ma50.dropna().iloc[-1])
        return price > ma_val, round(price, 2), round(ma_val, 2)
    except Exception as e:
        logger.warning(f"Regime check failed: {e}")
        return False, float("nan"), float("nan")


def _fetch_market_caps(symbols: tuple[str, ...]) -> dict[str, Optional[float]]:
    """Fetch market caps using yfinance fast_info for speed."""
    caps: dict[str, Optional[float]] = {}
    for sym in symbols:
        try:
            fi = yf.Ticker(sym).fast_info
            caps[sym] = getattr(fi, "market_cap", None)
        except Exception:
            caps[sym] = None
    return caps


# ── Hot Theme signal stack ─────────────────────────────────────────────────────

def _score_signal(result: SignalResult) -> int:
    """
    Composite score for ranking results:
    +1 VCP confirmed
    +1 TT == 4
    +1 RS > 1.25
    +1 RSI in 55-70 (sweet spot)
    +1 RR >= 4
    """
    score = 0
    if result.filters.get("vcp"):
        score += 1
    if result.tt_score >= 4:
        score += 1
    if result.rs > 1.25:
        score += 1
    if 55 <= result.rsi <= 70:
        score += 1
    if result.rr >= 4.0:
        score += 1
    return score


def scan_ticker(
    symbol: str,
    etf: str,
    sector: str,
    daily_data: dict[str, pd.DataFrame],
    weekly_data: dict[str, pd.DataFrame],
    spy_close: pd.Series,
) -> Optional[SignalResult]:
    """
    Run all 10 filters on a single ticker.
    Returns SignalResult if all pass, else None.
    """
    if symbol not in daily_data:
        return None

    df = daily_data[symbol]
    weekly_df = weekly_data.get(symbol)

    try:
        close = get_close(df)
    except Exception:
        return None

    if len(close) < 60:
        return None

    price = float(close.iloc[-1])
    filters: dict[str, bool] = {}

    # ── Filter 4: Stock RS > RS_STOCK_MIN ──────────────────────────────────────
    rs = compute_rs_vs_spy(close, spy_close)
    filters["rs"] = (not np.isnan(rs)) and (rs > RS_STOCK_MIN)
    if not filters["rs"]:
        return None

    # ── Filter 5: RSI 50-75 ────────────────────────────────────────────────────
    rsi_ok, rsi_val = check_rsi(close)
    filters["rsi"] = rsi_ok
    if not filters["rsi"]:
        return None

    # ── Filter 6: MACD (informational only — not a hard gate in screener) ───────
    filters["macd"] = check_macd(close)

    # ── Filter 7: Price > 50d SMA — soft (score bonus, doesn't hard-block) ────
    ma50 = sma(close, 50)
    price_above_ma = bool(not ma50.dropna().empty and float(close.iloc[-1]) > float(ma50.dropna().iloc[-1]))
    filters["price_ma_roc"] = price_above_ma

    # ── Filter 8: VPA — soft (score bonus only, not a hard gate) ─────────────
    vpa_ok, vol_ratio = check_vpa(df)
    filters["vpa"] = vpa_ok  # tracked for display but doesn't eliminate

    # ── Filter 9: VCP — soft (score bonus only, not a hard gate) ─────────────
    filters["vcp"] = check_vcp(close, weekly_df)  # tracked but doesn't eliminate

    # ── Filter 10: Trend Template ─────────────────────────────────────────────
    tt_ok, tt_score = compute_trend_template(close)
    filters["trend_template"] = tt_ok
    if not filters["trend_template"]:
        return None

    # ── Filter 11: ATR R:R Gate ───────────────────────────────────────────────
    atr_ok, atr_val, stop, target, rr = check_atr_rr(df)
    filters["atr_rr"] = atr_ok
    if not filters["atr_rr"]:
        return None

    result = SignalResult(
        symbol=symbol,
        sector=sector,
        etf=etf,
        price=round(price, 2),
        rsi=round(rsi_val, 1),
        rs=round(rs, 3),
        tt_score=tt_score,
        vol_ratio=vol_ratio,
        atr_stop=stop,
        target=target,
        rr=rr,
        filters=filters,
    )
    result.score = _score_signal(result)
    return result


def run_screener(
    spy_data: pd.DataFrame,
    sector_table: pd.DataFrame,
    n_hot: int,
    progress_callback=None,
) -> tuple[list[SignalResult], int]:
    """
    Main screener entry point.
    Returns (list of SignalResult, total_candidates_scanned).
    Only scans top n_hot sectors whose breadth passes threshold.
    """
    if sector_table.empty:
        return [], 0

    # Screener mode: use top n_hot sectors by RS rank, breadth is informational only
    hot_sectors = sector_table[sector_table["rank"] <= n_hot]

    # Collect unique tickers across hot sectors
    ticker_to_sector: dict[str, tuple[str, str]] = {}
    for _, row in hot_sectors.iterrows():
        etf = row["etf"]
        sector = row["sector"]
        for sym in SECTOR_TICKERS.get(etf, []):
            if sym not in ticker_to_sector:
                ticker_to_sector[sym] = (etf, sector)

    all_tickers = tuple(sorted(ticker_to_sector.keys()))
    total = len(all_tickers)

    if total == 0:
        return [], 0

    # Batch fetch data
    if progress_callback:
        progress_callback(0.1, f"Fetching daily data for {total} tickers...")
    daily_data = fetch_daily(all_tickers)

    if progress_callback:
        progress_callback(0.3, f"Fetching weekly data for {total} tickers...")
    weekly_data = fetch_weekly(all_tickers)

    try:
        spy_close = get_close(spy_data)
    except Exception:
        return [], total

    results: list[SignalResult] = []
    for i, (sym, (etf, sector)) in enumerate(ticker_to_sector.items()):
        if progress_callback and i % 10 == 0:
            pct = 0.4 + 0.55 * (i / total)
            progress_callback(pct, f"Scanning {sym} ({i+1}/{total})...")

        try:
            result = scan_ticker(sym, etf, sector, daily_data, weekly_data, spy_close)
            if result is not None:
                results.append(result)
        except Exception as e:
            logger.debug(f"Error scanning {sym}: {e}")

    results.sort(key=lambda r: (-r.score, -r.rs))

    # Batch fetch market caps for passing tickers only
    if results:
        if progress_callback:
            progress_callback(0.97, "Fetching market caps...")
        passing_syms = [r.symbol for r in results]
        mcaps = _fetch_market_caps(tuple(passing_syms))
        for r in results:
            r.market_cap = mcaps.get(r.symbol)

    return results, total


# ── 52-Week High Proximity Scanner ─────────────────────────────────────────────

def run_proximity_scanner(
    threshold: float = 0.05,
    progress_callback=None,
) -> tuple[list[ProximityResult], int]:
    """
    Standalone scanner: returns stocks within threshold% of their 52-week high.
    Scans the full sector universe. No SPY regime, RS, RSI, or other filters.

    Args:
        threshold: Maximum fractional distance from 52w high (0.05 = within 5%).
        progress_callback: Optional (pct: float, msg: str) -> None callback.

    Returns:
        (results sorted by proximity ascending, total tickers checked)
    """
    # Build deduplicated ticker → (etf, sector) map across all sectors
    ticker_to_sector: dict[str, tuple[str, str]] = {}
    for etf, sector_name in SECTOR_ETFS.items():
        for sym in SECTOR_TICKERS.get(etf, []):
            if sym not in ticker_to_sector:
                ticker_to_sector[sym] = (etf, sector_name)

    all_tickers = tuple(sorted(ticker_to_sector.keys()))
    total = len(all_tickers)

    if total == 0:
        return [], 0

    if progress_callback:
        progress_callback(0.1, f"Fetching price history for {total} tickers...")
    daily_data = fetch_daily(all_tickers)

    results: list[ProximityResult] = []
    for i, sym in enumerate(all_tickers):
        if progress_callback and i % 20 == 0:
            pct = 0.2 + 0.75 * (i / total)
            progress_callback(pct, f"Checking {sym} ({i+1}/{total})...")

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
        high_52w = float(close.tail(252).max())
        if high_52w <= 0:
            continue

        pct_from_high = (high_52w - price) / high_52w
        if pct_from_high <= threshold:
            etf, sector = ticker_to_sector[sym]
            results.append(ProximityResult(
                symbol=sym,
                sector=sector,
                etf=etf,
                price=round(price, 2),
                high_52w=round(high_52w, 2),
                pct_from_high=round(pct_from_high, 4),
            ))

    # Sort closest-to-high first
    results.sort(key=lambda r: r.pct_from_high)

    if results:
        if progress_callback:
            progress_callback(0.97, "Fetching market caps...")
        passing_syms = tuple(r.symbol for r in results)
        mcaps = _fetch_market_caps(passing_syms)
        for r in results:
            r.market_cap = mcaps.get(r.symbol)

    return results, total
