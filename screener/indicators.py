# screener/indicators.py — RSI, MACD, MA, ROC, ATR, VPA, VCP, Trend Template, RS

import numpy as np
import pandas as pd

from screener.config import (
    RSI_PERIOD, RSI_MIN, RSI_MAX,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    MA_SHORT, ROC_PERIOD,
    VPA_HIGH_LOOKBACK, VPA_HIGH_TOLERANCE, VPA_VOL_PERIOD, VPA_VOLUME_MULTIPLIER,
    BB_PERIOD, BB_STD, VCP_BB_PERCENTILE, VCP_LOOKBACK, VCP_INSIDE_BARS,
    TT_MA_SHORT, TT_MA_MID, TT_MA_LONG, TT_MA200_TREND_BARS, TT_MIN_SCORE,
    ATR_PERIOD, ATR_STOP_MULT, ATR_TARGET_MULT, ATR_MAX_STOP_PCT, ATR_MIN_RR,
    RS_STOCK_DAYS,
)


# ── Moving Averages ────────────────────────────────────────────────────────────

def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


# ── RSI ───────────────────────────────────────────────────────────────────────

def compute_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def check_rsi(close: pd.Series) -> tuple[bool, float]:
    """Returns (passes, rsi_value)."""
    rsi_series = compute_rsi(close)
    if rsi_series.empty or rsi_series.iloc[-1] != rsi_series.iloc[-1]:
        return False, float("nan")
    val = float(rsi_series.iloc[-1])
    return RSI_MIN <= val <= RSI_MAX, val


# ── MACD ──────────────────────────────────────────────────────────────────────

def compute_macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (macd_line, signal_line, histogram)."""
    fast = ema(close, MACD_FAST)
    slow = ema(close, MACD_SLOW)
    macd_line = fast - slow
    signal_line = ema(macd_line, MACD_SIGNAL)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def check_macd(close: pd.Series) -> bool:
    """
    Bullish if MACD histogram is positive (above zero).
    Relaxed for screener — no crossover or trending-up requirement.
    """
    if len(close) < MACD_SLOW + MACD_SIGNAL + 5:
        return False
    _, _, hist = compute_macd(close)
    h = hist.dropna()
    if h.empty:
        return False
    return float(h.iloc[-1]) > 0


# ── Price / MA / ROC ─────────────────────────────────────────────────────────

def check_price_ma_roc(close: pd.Series) -> tuple[bool, float]:
    """Price above 20d SMA and ROC5 > 0. Returns (passes, roc_value)."""
    if len(close) < max(MA_SHORT, ROC_PERIOD) + 1:
        return False, float("nan")
    ma = sma(close, MA_SHORT)
    if ma.dropna().empty:
        return False, float("nan")
    price = close.iloc[-1]
    ma_val = ma.iloc[-1]
    if price <= ma_val or ma_val != ma_val:
        return False, float("nan")
    roc = (close.iloc[-1] / close.iloc[-1 - ROC_PERIOD] - 1) * 100
    return roc > 0, float(roc)


# ── VPA ───────────────────────────────────────────────────────────────────────

def check_vpa(df: pd.DataFrame) -> tuple[bool, float]:
    """
    Price within 1% of or above 10d high, and volume ratio >= VPA_VOLUME_MULTIPLIER.
    Returns (passes, volume_ratio).
    """
    close = df["Close"].dropna()
    high = df["High"].dropna()
    vol = df["Volume"].dropna()

    if len(close) < VPA_HIGH_LOOKBACK or len(vol) < VPA_VOL_PERIOD:
        return False, float("nan")

    price = close.iloc[-1]
    high_10d = high.iloc[-VPA_HIGH_LOOKBACK:].max()
    near_high = price >= high_10d * (1 - VPA_HIGH_TOLERANCE)

    avg_vol = vol.iloc[-VPA_VOL_PERIOD - 1:-1].mean()
    cur_vol = vol.iloc[-1]
    vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0.0

    passes = near_high and vol_ratio >= VPA_VOLUME_MULTIPLIER
    return passes, round(float(vol_ratio), 2)


# ── VCP ───────────────────────────────────────────────────────────────────────

def _bb_width(close: pd.Series, period: int = BB_PERIOD, std: float = BB_STD) -> pd.Series:
    ma = close.rolling(period).mean()
    sd = close.rolling(period).std()
    upper = ma + std * sd
    lower = ma - std * sd
    # Normalize by mid (avoid division by zero)
    return (upper - lower) / ma.replace(0, np.nan)


def check_vcp_daily(close: pd.Series) -> bool:
    """BB width in bottom VCP_BB_PERCENTILE of last VCP_LOOKBACK days."""
    if len(close) < VCP_LOOKBACK:
        return False
    bw = _bb_width(close)
    bw = bw.dropna()
    if bw.empty:
        return False
    lookback = bw.iloc[-VCP_LOOKBACK:]
    threshold = np.percentile(lookback, VCP_BB_PERCENTILE)
    return bool(bw.iloc[-1] <= threshold)


def check_vcp_weekly(weekly_df: pd.DataFrame) -> bool:
    """2+ consecutive inside bars on weekly data."""
    if weekly_df is None or len(weekly_df) < VCP_INSIDE_BARS + 1:
        return False
    h = weekly_df["High"].dropna()
    l = weekly_df["Low"].dropna()
    if len(h) < VCP_INSIDE_BARS + 1:
        return False
    inside_count = 0
    for i in range(-1, -(VCP_INSIDE_BARS + 1), -1):
        if h.iloc[i] <= h.iloc[i - 1] and l.iloc[i] >= l.iloc[i - 1]:
            inside_count += 1
        else:
            break
    return inside_count >= VCP_INSIDE_BARS


def check_vcp(close: pd.Series, weekly_df: pd.DataFrame | None) -> bool:
    """Pass if either daily BB contraction OR weekly inside bars."""
    return check_vcp_daily(close) or check_vcp_weekly(weekly_df)


# ── Trend Template ────────────────────────────────────────────────────────────

def compute_trend_template(close: pd.Series) -> tuple[bool, int]:
    """
    Minervini Trend Template. Returns (passes, score).
    Score = count of conditions met (need >= TT_MIN_SCORE of 4).
    """
    if len(close) < TT_MA_LONG + TT_MA200_TREND_BARS:
        return False, 0

    ma50 = sma(close, TT_MA_SHORT)
    ma150 = sma(close, TT_MA_MID)
    ma200 = sma(close, TT_MA_LONG)

    if ma50.dropna().empty or ma150.dropna().empty or ma200.dropna().empty:
        return False, 0

    price = close.iloc[-1]
    score = 0

    # 1) Price > SMA50
    if price > ma50.iloc[-1]:
        score += 1

    # 2) SMA50 > SMA150
    if ma50.iloc[-1] > ma150.iloc[-1]:
        score += 1

    # 3) SMA150 > SMA200
    if ma150.iloc[-1] > ma200.iloc[-1]:
        score += 1

    # 4) SMA200 trending up over last 20 bars
    ma200_recent = ma200.dropna().iloc[-TT_MA200_TREND_BARS:]
    if len(ma200_recent) >= TT_MA200_TREND_BARS:
        if ma200_recent.iloc[-1] > ma200_recent.iloc[0]:
            score += 1

    return score >= TT_MIN_SCORE, score


# ── ATR & R:R ─────────────────────────────────────────────────────────────────

def compute_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()


def check_atr_rr(df: pd.DataFrame) -> tuple[bool, float, float, float, float]:
    """
    Returns (passes, atr_val, stop, target, rr).
    Rejects if stop > 7% away or R:R < 3.0.
    """
    close = df["Close"].dropna()
    atr_series = compute_atr(df)
    if atr_series.dropna().empty or close.empty:
        return False, float("nan"), float("nan"), float("nan"), float("nan")

    atr_val = float(atr_series.dropna().iloc[-1])
    price = float(close.iloc[-1])

    stop = price - ATR_STOP_MULT * atr_val
    target = price + ATR_TARGET_MULT * atr_val
    stop_dist_pct = (price - stop) / price
    rr = (target - price) / (price - stop) if (price - stop) > 0 else 0.0

    passes = stop_dist_pct <= ATR_MAX_STOP_PCT and rr >= ATR_MIN_RR
    return passes, round(atr_val, 2), round(stop, 2), round(target, 2), round(rr, 2)


# ── Relative Strength vs SPY ──────────────────────────────────────────────────

def compute_rs_vs_spy(stock_close: pd.Series, spy_close: pd.Series, days: int = RS_STOCK_DAYS) -> float:
    """
    RS = (stock_return / spy_return) over `days` trading days.
    Returns ratio; > 1.0 means outperforming.
    """
    # Align on common dates
    aligned = pd.DataFrame({"stock": stock_close, "spy": spy_close}).dropna()
    if len(aligned) < days + 1:
        return float("nan")
    sub = aligned.iloc[-days - 1:]
    stock_ret = sub["stock"].iloc[-1] / sub["stock"].iloc[0]
    spy_ret = sub["spy"].iloc[-1] / sub["spy"].iloc[0]
    if spy_ret == 0:
        return float("nan")
    return round(stock_ret / spy_ret, 4)
