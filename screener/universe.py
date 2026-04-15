"""
screener/universe.py — Full US equity universe from nasdaqtrader.com.

Fetches all NASDAQ- and NYSE/AMEX-listed common stocks, filters out ETFs,
warrants, preferred shares, test issues, and non-standard symbols.
Disk-caches to data/universe_cache.json with a 24-hour TTL so the scan
doesn't re-download on every run.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from io import StringIO
from urllib.request import urlopen

import pandas as pd

logger = logging.getLogger(__name__)

# Cache lives next to the project root so it survives Streamlit restarts.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_FILE = os.path.join(_PROJECT_ROOT, "data", "universe_cache.json")
_CACHE_TTL_SECONDS = 24 * 3600  # 24 hours

_NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
_OTHER_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

# Names containing these strings are almost certainly not plain common stock.
# Note: "Class A/B/C" shares ARE valid common stocks (GOOGL, NBIS, etc.) — do NOT exclude them.
_NAME_EXCLUDE_RE = re.compile(
    r"\bwarrant\b|\bwarrants\b"
    r"|\bpreferred\b|\bpfr\b"
    r"|\bdepositary\b"
    r"|\bnotes due\b|% senior|% sub|% due"
    r"|\bright\b|\brights\b"
    r"|acquisition corp"
    r"|\bunits\b",
    re.IGNORECASE,
)

# Symbols must be 1–5 uppercase letters only (no digits, no suffix chars like + ^ .)
_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}$")


def _read_pipe_delimited(url: str) -> pd.DataFrame:
    """Download a pipe-delimited nasdaqtrader file, strip the footer line."""
    with urlopen(url, timeout=30) as resp:
        text = resp.read().decode("utf-8")
    lines = [l for l in text.strip().splitlines() if not l.startswith("File Creation Time")]
    return pd.read_csv(StringIO("\n".join(lines)), sep="|", dtype=str).fillna("")


def _is_common_stock(symbol: str, name: str) -> bool:
    if not _SYMBOL_RE.match(symbol.strip()):
        return False
    if _NAME_EXCLUDE_RE.search(name):
        return False
    return True


def _fetch_nasdaq() -> list[str]:
    df = _read_pipe_delimited(_NASDAQ_URL)
    df = df[
        (df["ETF"].str.strip() == "N")
        & (df["Test Issue"].str.strip() == "N")
        & (df["Financial Status"].str.strip().isin(["N", ""]))
    ]
    return [
        row["Symbol"].strip()
        for _, row in df.iterrows()
        if _is_common_stock(row["Symbol"], row["Security Name"])
    ]


def _fetch_other() -> list[str]:
    df = _read_pipe_delimited(_OTHER_URL)
    df = df[
        (df["ETF"].str.strip() == "N")
        & (df["Test Issue"].str.strip() == "N")
        & (df["Exchange"].str.strip().isin(["A", "N", "P", "Z", "V"]))
    ]
    return [
        row["ACT Symbol"].strip()
        for _, row in df.iterrows()
        if _is_common_stock(row["ACT Symbol"], row["Security Name"])
    ]


def get_universe(force_refresh: bool = False) -> list[str]:
    """
    Return a sorted, deduplicated list of US common-stock ticker symbols.

    First call (or after 24 h) downloads fresh data from nasdaqtrader.com
    and writes data/universe_cache.json. Subsequent calls within the TTL
    return the cached list instantly.

    Falls back to an empty list (with a warning) if both the cache and the
    network are unavailable.
    """
    cache_dir = os.path.dirname(_CACHE_FILE)
    os.makedirs(cache_dir, exist_ok=True)

    # ── Check disk cache ──────────────────────────────────────────────────────
    if not force_refresh and os.path.exists(_CACHE_FILE):
        age = time.time() - os.path.getmtime(_CACHE_FILE)
        if age < _CACHE_TTL_SECONDS:
            try:
                with open(_CACHE_FILE) as f:
                    data = json.load(f)
                symbols = data.get("symbols", [])
                logger.info("Universe loaded from cache: %d symbols (age %.0fh)", len(symbols), age / 3600)
                return symbols
            except Exception as e:
                logger.warning("Cache read failed (%s), re-fetching", e)

    # ── Fetch fresh data ───────────────────────────────────────────────────────
    logger.info("Fetching fresh universe from nasdaqtrader.com…")
    symbols: set[str] = set()

    for fetch_fn, label in [(_fetch_nasdaq, "NASDAQ"), (_fetch_other, "NYSE/AMEX")]:
        try:
            batch = fetch_fn()
            symbols.update(batch)
            logger.info("  %s: %d symbols", label, len(batch))
        except Exception as e:
            logger.warning("  Failed to fetch %s list: %s", label, e)

    if not symbols:
        logger.error("Universe fetch failed entirely — returning empty list")
        return []

    result = sorted(symbols)
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump({"symbols": result, "fetched_at": time.time(), "count": len(result)}, f)
        logger.info("Universe cached: %d symbols → %s", len(result), _CACHE_FILE)
    except Exception as e:
        logger.warning("Could not write cache: %s", e)

    return result


def universe_cache_info() -> dict:
    """Return metadata about the cached universe (age, count). UI-friendly."""
    if not os.path.exists(_CACHE_FILE):
        return {"cached": False, "count": 0, "age_hours": None}
    try:
        age = time.time() - os.path.getmtime(_CACHE_FILE)
        with open(_CACHE_FILE) as f:
            data = json.load(f)
        return {
            "cached": True,
            "count": data.get("count", len(data.get("symbols", []))),
            "age_hours": round(age / 3600, 1),
            "stale": age >= _CACHE_TTL_SECONDS,
        }
    except Exception:
        return {"cached": False, "count": 0, "age_hours": None}
