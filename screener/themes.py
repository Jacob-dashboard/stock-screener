# screener/themes.py — Pre-defined theme baskets for the Theme Scanner

THEMES: dict[str, list[str]] = {
    "AI / Data Center": [
        "NVDA", "AMD", "AVGO", "MRVL", "SMCI", "DELL", "NBIS", "APLD",
        "IREN", "CRWV", "CORZ", "WULF", "VRT", "EQIX", "DLR",
    ],
    "Photonics / Optical": [
        "COHR", "LITE", "CIEN", "INFN", "AAOI", "POET", "LPTH",
        "FNSR", "IIVI", "LUMENTUM",
    ],
    "Semiconductor Foundry": [
        "TSM", "INTC", "GFS", "UMC", "ASX",
    ],
    "CPU / Hardware": [
        "INTC", "AMD", "QCOM", "ARM", "MRVL", "AVGO", "TXN",
        "ADI", "NXPI", "MCHP", "ON", "SWKS", "QRVO",
    ],
    "Semiconductor Equipment (Pick & Shovel)": [
        "AMAT", "LRCX", "KLAC", "ASML", "ONTO", "ACLS",
        "TER", "ENTG", "MKSI", "CAMT",
    ],
    "AI Software / Applications": [
        "PLTR", "CRM", "NOW", "SNOW", "DDOG", "MDB", "ESTC",
        "AI", "PATH", "BBAI",
    ],
    "Cybersecurity": [
        "CRWD", "PANW", "ZS", "FTNT", "NET", "S", "OKTA",
        "CYBR", "TENB", "RPD",
    ],
    "EV / Battery": [
        "TSLA", "RIVN", "LCID", "NIO", "XPEV", "LI", "QS",
        "BEEM", "CHPT", "BLNK", "EVGO",
    ],
    "Nuclear / Uranium": [
        "CCJ", "LEU", "NNE", "SMR", "OKLO", "UEC", "DNN", "URG", "UUUU",
    ],
    "Space / Defense Tech": [
        "RKLB", "LUNR", "ASTS", "PL", "BKSY", "RDW", "KTOS",
        "AVAV", "LMT", "NOC",
    ],
    "Bitcoin / Crypto Miners": [
        "MSTR", "MARA", "RIOT", "CLSK", "CIFR", "BTBT", "HUT", "BTDR", "COIN",
    ],
    "GLP-1 / Obesity Pharma": [
        "LLY", "NVO", "AMGN", "VKTX", "GPCR", "ALT", "STRM",
    ],
    "Solar / Clean Energy": [
        "ENPH", "FSLR", "RUN", "SEDG", "ARRY", "NEE", "CSIQ", "JKS",
    ],
    "Gold / Precious Metals": [
        "NEM", "GOLD", "AEM", "FNV", "WPM", "KGC", "AGI",
    ],
    "Oil / Energy": [
        "XOM", "CVX", "COP", "OXY", "DVN", "EOG", "PR", "SLB",
    ],
    "REIT / Real Estate": [
        "O", "SPG", "PLD", "AMT", "EQIX", "DLR", "WELL", "IRM",
    ],
    "Quantum Computing": [
        "IONQ", "RGTI", "QBTS", "QUBT", "ARQQ",
    ],
    "Robotics / Automation": [
        "ISRG", "TER", "ABB", "ROK", "CGNX", "IRBT",
    ],
}
