"""
screener/breadth_stockbee.py — Stockbee Market Monitor integration

Fetches the Stockbee Market Monitor spreadsheet (Google Sheets, public CSV)
which publishes daily breadth readings: T2108, 4%/25%/50% momentum counts,
up/down ratios, etc.

Source: https://stockbee.blogspot.com/p/mm.html
"""

import logging

import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)

_CSV_URL = (
    "https://docs.google.com/spreadsheet/pub"
    "?key=0Am_cU8NLIU20dEhiQnVHN3Nnc3B1S3J6eGhKZFo0N3c"
    "&output=csv"
)

# Friendly column names (maps positional index → short name).
# Row 0 of the CSV is a merged section header; row 1 has the real headers.
_COLUMN_RENAMES = {
    "Date":                                        "date",
    "Number of stocks up 4% plus today":           "up_4pct",
    "Number of stocks down 4% plus today":         "dn_4pct",
    "5 day ratio":                                 "ratio_5d",
    "10 day  ratio":                               "ratio_10d",
    "Number of stocks up 25% plus in a quarter":   "up_25pct_qtr",
    "Number of stocks down 25% + in a quarter":    "dn_25pct_qtr",
    "Number of stocks up 25% + in a month":        "up_25pct_mo",
    "Number of stocks down 25% + in a month":      "dn_25pct_mo",
    "Number of stocks up 50% + in a month":        "up_50pct_mo",
    "Number of stocks down 50% + in a month":      "dn_50pct_mo",
    "Number of stocks up 13% + in 34 days":        "up_13pct_34d",
    "Number of stocks down 13% + in 34 days":      "dn_13pct_34d",
    " Worden Common stock universe":               "universe",
    "Worden Common stock universe":                "universe",
    "T2108 ":                                      "t2108",
    "T2108":                                       "t2108",
    "S&P":                                         "sp500",
}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_stockbee_breadth(n_days: int = 60) -> pd.DataFrame:
    """
    Fetch the Stockbee Market Monitor CSV and return a tidy DataFrame.

    Returns DataFrame with columns:
      date, up_4pct, dn_4pct, ratio_5d, ratio_10d,
      up_25pct_qtr, dn_25pct_qtr, up_25pct_mo, dn_25pct_mo,
      up_50pct_mo, dn_50pct_mo, up_13pct_34d, dn_13pct_34d,
      universe, t2108, sp500

    `date` is the index (pd.DatetimeIndex), sorted oldest→newest.
    Returns an empty DataFrame on any fetch/parse failure.
    """
    try:
        # The sheet has a merged "section header" in row 0; real headers in row 1.
        df = pd.read_csv(_CSV_URL, header=1)

        # Drop the leading unnamed column (blank column before "Date")
        df = df.loc[:, ~df.columns.str.match(r"^Unnamed")]

        # Normalize whitespace in column names before renaming
        df.columns = [c.strip() for c in df.columns]
        df.columns = [" ".join(c.split()) for c in df.columns]

        # Normalize the rename keys the same way for a reliable match
        normalized_renames = {
            " ".join(k.strip().split()): v
            for k, v in _COLUMN_RENAMES.items()
        }
        df = df.rename(columns=normalized_renames)

        # Parse date and set as index
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df = df.set_index("date").sort_index()

        # Coerce numeric columns
        for col in df.columns:
            if col != "sp500":
                df[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                # sp500 has commas: "7,022.57"
                df[col] = (
                    df[col].astype(str).str.replace(",", "", regex=False)
                )
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df.tail(n_days)

    except Exception as exc:
        logger.warning("Stockbee breadth fetch failed: %s", exc)
        return pd.DataFrame()


def latest_stockbee_row(df: pd.DataFrame) -> dict:
    """Return the most recent row as a plain dict (empty if df is empty)."""
    if df.empty:
        return {}
    row = df.iloc[-1]
    return {col: (None if pd.isna(row[col]) else row[col]) for col in df.columns}
