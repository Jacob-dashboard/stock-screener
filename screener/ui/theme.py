"""
screener/ui/theme.py — Custom CSS injection & branding helpers

Call inject_theme() once near the top of app.py (after st.set_page_config).
Palette: GitHub-dark base · amber/gold accent (#E6B800) · near-black BG (#0D1117)
Typography: Inter (sans) · JetBrains Mono (numerics)
"""

import streamlit as st

# ── Core stylesheet ─────────────────────────────────────────────────────────

_CSS = """
<style>
/* ── Google Fonts ──────────────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Root typography ───────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

/* ── App background ────────────────────────────────────────────────────── */
.stApp {
    background-color: #0D1117;
}
.main .block-container {
    background-color: #0D1117;
    padding-top: 1.25rem;
    max-width: 1440px;
}

/* ── Sidebar ────────────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background-color: #0D1117;
    border-right: 1px solid #21262d;
}
section[data-testid="stSidebar"] > div:first-child {
    padding-top: 1rem;
}

/* ── Metric cards ───────────────────────────────────────────────────────── */
[data-testid="metric-container"] {
    background-color: #161B22 !important;
    border: 1px solid #30363d !important;
    border-radius: 8px !important;
    padding: 14px 18px !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.72em !important;
    color: #8b949e !important;
    text-transform: uppercase;
    letter-spacing: 0.07em;
}
[data-testid="stMetricValue"] {
    font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
    font-size: 1.55em !important;
    color: #f0f6fc !important;
}
[data-testid="stMetricDelta"] {
    font-size: 0.82em !important;
}

/* ── Dataframes / tables ────────────────────────────────────────────────── */
.stDataFrame {
    font-size: 0.84em;
}
/* Zebra rows */
.stDataFrame [data-testid="stDataFrameResizable"] tbody tr:nth-child(even) {
    background-color: rgba(22, 27, 34, 0.6);
}
/* Numeric columns: monospace right-aligned */
.stDataFrame [data-testid="stDataFrameResizable"] td {
    font-family: 'JetBrains Mono', monospace;
}

/* ── Tabs ───────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    background-color: #161B22;
    border-bottom: 1px solid #30363d;
    gap: 2px;
    padding: 0 4px;
}
.stTabs [data-baseweb="tab"] {
    color: #8b949e;
    font-size: 0.88em;
    padding: 8px 18px;
    border-radius: 6px 6px 0 0;
    border: none;
    background: transparent;
}
.stTabs [aria-selected="true"] {
    color: #E6B800 !important;
    background-color: #1c2333 !important;
    border-bottom: 2px solid #E6B800 !important;
}

/* ── Buttons ────────────────────────────────────────────────────────────── */
.stButton > button {
    background-color: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 6px;
    font-size: 0.88em;
    font-family: 'Inter', sans-serif;
    transition: background 0.15s, border-color 0.15s;
}
.stButton > button:hover {
    background-color: #2d333b;
    border-color: #E6B800;
    color: #f0f6fc;
}
.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"] {
    background-color: #E6B800 !important;
    color: #0D1117 !important;
    border-color: #E6B800 !important;
    font-weight: 600;
}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="stBaseButton-primary"]:hover {
    background-color: #f5cc00 !important;
    border-color: #f5cc00 !important;
}

/* ── Progress bar ───────────────────────────────────────────────────────── */
.stProgress > div > div > div > div {
    background-color: #E6B800;
}

/* ── Expander ───────────────────────────────────────────────────────────── */
details[data-testid="stExpander"] {
    background-color: #161B22;
    border: 1px solid #30363d;
    border-radius: 8px;
}
details[data-testid="stExpander"] summary {
    font-size: 0.88em;
    color: #c9d1d9;
}

/* ── Dividers ───────────────────────────────────────────────────────────── */
hr {
    border-color: #21262d !important;
    margin: 10px 0 !important;
}

/* ── Captions ───────────────────────────────────────────────────────────── */
.stCaption, [data-testid="stCaptionContainer"] {
    color: #6e7681 !important;
    font-size: 0.78em !important;
}

/* ── Alerts / info boxes ────────────────────────────────────────────────── */
.stAlert {
    border-radius: 8px;
    border-left-width: 3px;
}

/* ── Slider ─────────────────────────────────────────────────────────────── */
.stSlider [data-baseweb="slider"] [data-testid="stTickBarMin"],
.stSlider [data-baseweb="slider"] [data-testid="stTickBarMax"] {
    color: #6e7681;
    font-size: 0.8em;
}

/* ── Number inputs ──────────────────────────────────────────────────────── */
.stNumberInput input {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.9em;
}

/* ── Subheaders ─────────────────────────────────────────────────────────── */
h2, h3 {
    color: #f0f6fc !important;
    font-weight: 600;
}
h2 { font-size: 1.2em !important; }
h3 { font-size: 1.05em !important; }

/* ── Sidebar brand banner ───────────────────────────────────────────────── */
.sidebar-brand {
    background: linear-gradient(135deg, #1c2333 0%, #161B22 100%);
    border: 1px solid #30363d;
    border-left: 3px solid #E6B800;
    border-radius: 8px;
    padding: 10px 14px;
    margin-bottom: 10px;
}
.sidebar-brand-title {
    font-size: 1em;
    font-weight: 700;
    color: #f0f6fc;
    margin: 0;
    letter-spacing: 0.01em;
}
.sidebar-brand-sub {
    font-size: 0.72em;
    color: #8b949e;
    margin: 2px 0 0 0;
}

/* ── App header banner ──────────────────────────────────────────────────── */
.app-header {
    background: linear-gradient(135deg, #161B22 0%, #1c2333 100%);
    border: 1px solid #30363d;
    border-bottom: 2px solid #E6B800;
    border-radius: 10px;
    padding: 14px 22px;
    margin-bottom: 16px;
}
.app-header-title {
    font-size: 1.45em;
    font-weight: 700;
    color: #f0f6fc;
    margin: 0 0 3px 0;
    letter-spacing: -0.01em;
}
.app-header-sub {
    font-size: 0.78em;
    color: #8b949e;
    margin: 0;
}

/* ── Footer ─────────────────────────────────────────────────────────────── */
.app-footer {
    border-top: 1px solid #21262d;
    padding: 10px 0 4px 0;
    font-size: 0.72em;
    color: #484f58;
    text-align: center;
    font-family: 'Inter', sans-serif;
}
.app-footer a {
    color: #8b949e;
    text-decoration: none;
}
.app-footer a:hover {
    color: #E6B800;
    text-decoration: underline;
}
</style>
"""


def inject_theme() -> None:
    """Inject custom CSS. Call once after st.set_page_config."""
    st.markdown(_CSS, unsafe_allow_html=True)


def render_app_header() -> None:
    """Branded app header below page title."""
    st.markdown(
        """
        <div class="app-header">
          <div class="app-header-title">🔥 Hot Theme Stock Screener</div>
          <div class="app-header-sub">
            Sector RS ranking &nbsp;·&nbsp; Minervini Trend Template &nbsp;·&nbsp;
            VCP + ATR signal stack &nbsp;·&nbsp; Market Breadth Dashboard
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_brand() -> None:
    """Compact branded banner at top of sidebar."""
    st.markdown(
        """
        <div class="sidebar-brand">
          <div class="sidebar-brand-title">🔥 Hot Theme Screener</div>
          <div class="sidebar-brand-sub">Sector RS · Breadth · Signals</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_footer(last_refresh: str | None = None) -> None:
    """App footer with data source note and optional last-refresh time."""
    refresh = f"Last data refresh: {last_refresh} &nbsp;·&nbsp; " if last_refresh else ""
    st.markdown(
        f"""
        <div class="app-footer">
          {refresh}Data via yfinance · Alpaca &nbsp;·&nbsp;
          📋 Paper mode — thresholds relaxed vs live bot &nbsp;·&nbsp;
          Not financial advice
        </div>
        """,
        unsafe_allow_html=True,
    )
