# screener/config.py — All thresholds and sector universe

# ── Market Regime ──────────────────────────────────────────────────────────────
SPY_MA_PERIOD = 50          # SPY must be above this SMA

# ── Sector RS ─────────────────────────────────────────────────────────────────
RS_SHORT_DAYS = 63          # ~3 months
RS_LONG_DAYS = 126          # ~6 months
RS_SHORT_WEIGHT = 0.6
RS_LONG_WEIGHT = 0.4
N_HOT_SECTORS = 22          # scan all sectors — individual filters handle quality

# ── Breadth ───────────────────────────────────────────────────────────────────
BREADTH_THRESHOLD = 0.50    # % stocks above 50d SMA (relaxed vs 0.80 in live bot)
BREADTH_MA_PERIOD = 50

# ── Individual Stock RS ───────────────────────────────────────────────────────
RS_STOCK_MIN = 1.0          # stock return / SPY return over 63 days (relaxed for screener)
RS_STOCK_DAYS = 63

# ── RSI ───────────────────────────────────────────────────────────────────────
RSI_PERIOD = 14
RSI_MIN = 30                # widened — allow oversold bounce candidates
RSI_MAX = 85

# ── MACD ──────────────────────────────────────────────────────────────────────
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# ── Price / MA / ROC ─────────────────────────────────────────────────────────
MA_SHORT = 20               # price must be above this SMA
ROC_PERIOD = 5              # rate of change must be positive

# ── VPA (Volume-Price Analysis) ───────────────────────────────────────────────
VPA_HIGH_LOOKBACK = 10      # days for rolling high
VPA_HIGH_TOLERANCE = 0.05   # price within 5% of 10d high (relaxed from 1%)
VPA_VOL_PERIOD = 20         # avg volume period
VPA_VOLUME_MULTIPLIER = 0.5 # relaxed from 0.75 for screener

# ── VCP (Volatility Contraction Pattern) ──────────────────────────────────────
BB_PERIOD = 20
BB_STD = 2.0
VCP_BB_PERCENTILE = 75      # BB width in bottom 75th percentile (relaxed from 50)
VCP_LOOKBACK = 252          # days to compute BB percentile over
VCP_INSIDE_BARS = 1         # 1 inside bar enough for screener (relaxed from 2)

# ── Trend Template (Minervini) ────────────────────────────────────────────────
TT_MA_SHORT = 50
TT_MA_MID = 150
TT_MA_LONG = 200
TT_MA200_TREND_BARS = 20
TT_MIN_SCORE = 2            # need >= 2 of 4 conditions

# ── ATR / R:R Gate ────────────────────────────────────────────────────────────
ATR_PERIOD = 20
ATR_STOP_MULT = 1.5         # stop = price - (mult × ATR)
ATR_TARGET_MULT = 4.5       # target = price + (mult × ATR)  → 3:1 R:R
ATR_MAX_STOP_PCT = 0.15     # relaxed from 0.07 — screener allows volatile stocks
ATR_MIN_RR = 2.9            # slight buffer for float precision (true ratio = 3.0)

# ── New High ──────────────────────────────────────────────────────────────────
NEW_HIGH_LOOKBACK = 52      # weeks (~252 trading days)

# ── Cache ─────────────────────────────────────────────────────────────────────
CACHE_TTL = 1800            # seconds (30 min)
DATA_PERIOD = "1y"          # yfinance download period
WEEKLY_DATA_PERIOD = "2y"

# ── Sector ETFs Universe ──────────────────────────────────────────────────────
SECTOR_ETFS = {
    "XLK": "Technology",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLF": "Financials",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
    "SMH": "Semiconductors",
    "XBI": "Biotech",
    "ARKK": "Disruptive Innovation",
    "CIBR": "Cybersecurity",
    "ICLN": "Clean Energy",
    "GLD": "Gold",
    "ITA": "Defense Tech",
    "TAN": "Renewable Energy",
    "SKYY": "Cloud/SaaS",
    "UFO": "Space Exploration",
    "AIQ": "AI & Big Data",
}

SECTOR_TICKERS = {
    "SMH": ["NVDA","TSM","ASML","AVGO","QCOM","AMD","MU","AMAT","LRCX","KLAC","INTC","MRVL","ON","SWKS","MPWR","TER","ENTG","ONTO","ACLS"],
    "ITA": ["LMT","RTX","NOC","GD","BA","LHX","HII","TDG","KTOS","RKLB","AXON","CACI","LDOS","SAIC","BAH","DRS"],
    "UFO": ["ASTS","RKLB","PL","SPCE","MNTS","BWXT","NOC","LMT","BA","KTOS","RDW","LUNR","IRDM","SPIR","VSAT","GSAT"],
    "AIQ": ["APLD","NBIS","NVDA","AMD","SMCI","VRT","ETN","EQIX","DLR","IREN","HUT","BTBT","CORZ","CLSK","WULF","ACMR","ORCL","MSFT","GOOGL","META","DELL","HPE","ANET","CRWV","ARM","PLTR","SNOW","DDOG","NET","CRWD"],
    "SKYY": ["SNOW","PLTR","DDOG","NET","CRWD","ZS","MDB","ESTC","CFLT","GTLB","PATH","AI","S","OKTA","SAIL","SMAR"],
    "CIBR": ["PANW","CRWD","ZS","FTNT","OKTA","S","CYBR","TENB","RPD","QLYS","NET","VRNS","DDOG","ESTC","CHKP","GEN"],
    "XLK": ["AAPL","MSFT","NVDA","AVGO","ORCL","AMD","QCOM","ACN","NOW","ADBE","CSCO","IBM","TXN","AMAT","INTC","MU","LRCX","KLAC"],
    "XLF": ["JPM","BAC","WFC","GS","MS","BLK","SCHW","AXP","C","USB","PNC","TFC","COF","SPGI","MCO","ICE","CME","AON","MMC","PRU"],
    "XLV": ["UNH","JNJ","LLY","ABT","TMO","DHR","MDT","ISRG","BSX","PFE","MRK","ABBV","BMY","AMGN","GILD","HUM","CVS","CI","ELV"],
    "XBI": ["MRNA","REGN","VRTX","BIIB","ALNY","INCY","IONS","EXEL","HALO","PTCT","SRPT","RARE","FOLD","ACAD","INSM","LEGN","BMRN","PCVX","RVMD"],
    "ARKK": ["TSLA","ROKU","COIN","PATH","TDOC","EXAS","BEAM","CRSP","EDIT","NTLA","TWLO","SHOP","SQ","HOOD","U","RBLX","ZM","DKNG","PACB"],
    "XLE": ["XOM","CVX","COP","EOG","SLB","MPC","PSX","VLO","OXY","HAL","DVN","BKR","FANG","APA","CTRA"],
    "XLI": ["HON","GE","CAT","DE","LMT","RTX","UPS","FDX","NOC","GD","BA","MMM","EMR","ETN","PH","ROK","XYL","IR","CARR","OTIS"],
    "XLY": ["AMZN","TSLA","HD","MCD","NKE","LOW","SBUX","TJX","BKNG","CMG","MAR","HLT","F","GM","ORLY","AZO","CCL","RCL","NCLH"],
    "XLC": ["META","GOOGL","NFLX","DIS","CMCSA","T","VZ","TTWO","EA","CHTR","TMUS","WBD","LYV","OMC","IPG","MTCH","ZG","FOXA"],
    "ICLN": ["ENPH","SEDG","RUN","FSLR","NEE","BEP","CWEN","PLUG","BE","ARRY","MAXN","STEM","CSIQ","JKS","FLNC","SHLS","GNRC","HASI"],
    "TAN": ["FSLR","ENPH","SEDG","RUN","ARRY","MAXN","CSIQ","JKS","FLNC","SHLS","BE","PLUG","STEM","HASI","NEE","BEP","CWEN"],
    "GLD": ["NEM","GOLD","AEM","WPM","FNV","KGC","AGI","OR","PAAS","HL","EXK","AG","MAG","CDE","SILV","SVM","SAND","BTG","NGD"],
    "XLB": ["LIN","APD","SHW","FCX","NEM","ECL","DD","NUE","VMC","MLM","CF","MOS","ALB","FMC","IFF","CE","EMN","RPM"],
    "XLP": ["PG","KO","PEP","COST","WMT","PM","MO","MDLZ","CL","KMB","GIS","K","HRL","SJM","CAG","CPB","TSN","MKC"],
    "XLU": ["NEE","DUK","SO","D","AEE","EXC","SRE","XEL","AWK","PPL","ES","WEC","ETR","EIX","PEG","ED","FE","CNP","NI"],
    "XLRE": ["AMT","PLD","EQIX","CCI","PSA","DLR","O","SPG","WELL","AVB","EQR","VTR","BXP","ARE","KIM","REG","EXR","INVH","MAA"],
}
