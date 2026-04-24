# screener/signal_engine.py — Full 10-filter buy signal logic + 52W proximity scanner

import logging
import time
from concurrent.futures import ThreadPoolExecutor
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
    """Fetch market caps in parallel using ThreadPoolExecutor (≈20 concurrent)."""
    if not symbols:
        return {}

    def _one(sym: str) -> tuple[str, Optional[float]]:
        try:
            fi = yf.Ticker(sym).fast_info
            return sym, getattr(fi, "market_cap", None)
        except Exception:
            return sym, None

    caps: dict[str, Optional[float]] = {}
    workers = min(20, len(symbols))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for sym, cap in ex.map(_one, symbols):
            caps[sym] = cap
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

_PROXIMITY_BATCH = 500   # tickers per yfinance batch download


def _build_sector_lookup() -> dict[str, tuple[str, str]]:
    """Build symbol → (etf, sector) from the curated SECTOR_TICKERS map."""
    lookup: dict[str, tuple[str, str]] = {}
    for etf, sector_name in SECTOR_ETFS.items():
        for sym in SECTOR_TICKERS.get(etf, []):
            if sym not in lookup:
                lookup[sym] = (etf, sector_name)
    return lookup


def run_proximity_scanner(
    threshold: float = 0.05,
    progress_callback=None,
) -> tuple[list[ProximityResult], int]:
    """
    Standalone scanner: returns stocks within threshold% of their 52-week high.
    Scans the full US equity universe (~5 000 tickers) via nasdaqtrader.com.
    No SPY regime, RS, RSI, or other filters — purely proximity-based.

    Downloads in batches of _PROXIMITY_BATCH to bound memory usage and give
    fine-grained progress. Sector/ETF labels are populated for the ~400
    curated tickers; everything else gets '—'.

    Args:
        threshold: Maximum fractional distance from 52w high (0.05 = within 5%).
        progress_callback: Optional (pct: float, msg: str) -> None.

    Returns:
        (results sorted by proximity ascending, total tickers checked)
    """
    from screener.universe import get_universe

    if progress_callback:
        progress_callback(0.02, "Loading ticker universe…")

    all_symbols = get_universe()
    total = len(all_symbols)
    if total == 0:
        logger.warning("Universe is empty — check network access to nasdaqtrader.com")
        return [], 0

    sector_lookup = _build_sector_lookup()
    results: list[ProximityResult] = []
    n_batches = max(1, (total + _PROXIMITY_BATCH - 1) // _PROXIMITY_BATCH)

    for batch_idx, start in enumerate(range(0, total, _PROXIMITY_BATCH)):
        batch = tuple(all_symbols[start : start + _PROXIMITY_BATCH])
        end = min(start + len(batch), total)
        pct = 0.05 + 0.87 * (start / total)
        if progress_callback:
            progress_callback(
                pct,
                f"Batch {batch_idx + 1}/{n_batches} — tickers {start + 1}–{end} of {total}…",
            )

        try:
            batch_data = fetch_daily(batch)
        except Exception as e:
            logger.warning("Batch %d download failed: %s", batch_idx + 1, e)
            continue

        for sym in batch:
            if sym not in batch_data:
                continue
            df = batch_data[sym]
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
                etf, sector = sector_lookup.get(sym, ("—", "—"))
                results.append(
                    ProximityResult(
                        symbol=sym,
                        sector=sector,
                        etf=etf,
                        price=round(price, 2),
                        high_52w=round(high_52w, 2),
                        pct_from_high=round(pct_from_high, 4),
                    )
                )

    results.sort(key=lambda r: r.pct_from_high)

    if results:
        if progress_callback:
            progress_callback(0.97, f"Fetching market caps for {len(results)} matches…")
        mcaps = _fetch_market_caps(tuple(r.symbol for r in results))
        for r in results:
            r.market_cap = mcaps.get(r.symbol)

    return results, total


# ── Full-Universe Hot Theme Signals Scanner ────────────────────────────────────

_FULL_SCAN_BATCH = 500   # tickers per yfinance batch


def run_full_universe_screener(
    spy_data: pd.DataFrame,
    progress_callback=None,
) -> tuple[list[SignalResult], int]:
    """
    Scan the full US equity universe (~5,000 tickers) with the 10-filter signal stack.

    Two-pass approach for efficiency:
      Pass 1 — daily data in batches of 500; apply hard gates (RS, RSI, Trend Template, ATR).
               Penny stocks (<$1) are skipped.
      Pass 2 — weekly data for survivors only (~50–150 tickers); compute VCP and full scores.

    Sector/ETF labels are assigned for the ~400 curated tickers; all others are labelled
    "Other" so they still appear in results.

    Args:
        spy_data:          SPY daily DataFrame (used for RS computation).
        progress_callback: Optional (pct: float, msg: str) -> None.

    Returns:
        (list[SignalResult] sorted by score desc, total tickers scanned)
    """
    from screener.universe import get_universe

    if progress_callback:
        progress_callback(0.02, "Loading ticker universe…")

    all_symbols = get_universe()
    total = len(all_symbols)
    if total == 0:
        logger.warning("Universe empty — check nasdaqtrader.com access")
        return [], 0

    try:
        spy_close = get_close(spy_data)
    except Exception as e:
        logger.error("Could not extract SPY close: %s", e)
        return [], total

    sector_lookup = _build_sector_lookup()
    n_batches = max(1, (total + _FULL_SCAN_BATCH - 1) // _FULL_SCAN_BATCH)

    # ── Pass 1: hard gates on daily data ─────────────────────────────────────
    # survivors: sym → (etf, sector, df)
    survivors: dict[str, tuple[str, str, pd.DataFrame]] = {}

    for batch_idx, start in enumerate(range(0, total, _FULL_SCAN_BATCH)):
        batch = tuple(all_symbols[start : start + _FULL_SCAN_BATCH])
        end = min(start + len(batch), total)
        pct = 0.05 + 0.65 * (start / total)
        if progress_callback:
            progress_callback(
                pct,
                f"Scanning {start + 1}–{end} of {total} (batch {batch_idx + 1}/{n_batches})…",
            )

        try:
            batch_data = fetch_daily(batch)
        except Exception as e:
            logger.warning("Batch %d failed: %s", batch_idx + 1, e)
            continue

        for sym in batch:
            if sym not in batch_data:
                continue
            df = batch_data[sym]
            try:
                close = get_close(df)
            except Exception:
                continue
            if len(close) < 60:
                continue

            price = float(close.iloc[-1])
            if price < 1.0:          # skip penny stocks
                continue

            # Gate 1: RS vs SPY
            rs = compute_rs_vs_spy(close, spy_close)
            if np.isnan(rs) or rs <= RS_STOCK_MIN:
                continue

            # Gate 2: RSI
            rsi_ok, _ = check_rsi(close)
            if not rsi_ok:
                continue

            # Gate 3: Trend Template ≥ 2/4
            tt_ok, _ = compute_trend_template(close)
            if not tt_ok:
                continue

            # Gate 4: ATR R:R
            atr_ok, _, _, _, _ = check_atr_rr(df)
            if not atr_ok:
                continue

            etf, sector = sector_lookup.get(sym, ("—", "Other"))
            survivors[sym] = (etf, sector, df)

    if not survivors:
        return [], total

    # ── Pass 2: weekly data for survivors → VCP + composite score ────────────
    survivor_syms = tuple(sorted(survivors.keys()))
    if progress_callback:
        progress_callback(
            0.72,
            f"Fetching weekly data for {len(survivor_syms)} candidates…",
        )

    weekly_data = fetch_weekly(survivor_syms)

    if progress_callback:
        progress_callback(0.82, "Computing composite scores…")

    results: list[SignalResult] = []

    for sym, (etf, sector, df) in survivors.items():
        try:
            close = get_close(df)
            price = float(close.iloc[-1])

            filters: dict[str, bool] = {}

            rs = compute_rs_vs_spy(close, spy_close)
            filters["rs"] = True          # passed gate in pass 1

            rsi_ok, rsi_val = check_rsi(close)
            filters["rsi"] = True         # passed gate in pass 1

            filters["macd"] = check_macd(close)

            ma50 = sma(close, 50)
            price_above_ma = (
                not ma50.dropna().empty
                and price > float(ma50.dropna().iloc[-1])
            )
            filters["price_ma_roc"] = price_above_ma

            vpa_ok, vol_ratio = check_vpa(df)
            filters["vpa"] = vpa_ok

            weekly_df = weekly_data.get(sym)
            filters["vcp"] = check_vcp(close, weekly_df)

            tt_ok, tt_score = compute_trend_template(close)
            filters["trend_template"] = True  # passed gate in pass 1

            atr_ok, _, stop, target, rr = check_atr_rr(df)
            filters["atr_rr"] = True          # passed gate in pass 1

            result = SignalResult(
                symbol=sym,
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
            results.append(result)
        except Exception as e:
            logger.debug("Error scoring %s: %s", sym, e)

    results.sort(key=lambda r: (-r.score, -r.rs))

    # Parallel market cap fetch for passing tickers
    if results:
        if progress_callback:
            progress_callback(0.93, f"Fetching market caps for {len(results)} signals…")
        mcaps = _fetch_market_caps(tuple(r.symbol for r in results))
        for r in results:
            r.market_cap = mcaps.get(r.symbol)

    return results, total
