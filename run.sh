#!/bin/bash
cd "$(dirname "$0")"

# Load local env vars (not committed — contains API keys)
if [ -f ".env.local" ]; then
    set -a
    # shellcheck source=/dev/null
    source .env.local
    set +a
fi

# Use local venv if available
if [ -f ".venv/bin/streamlit" ]; then
    STREAMLIT=".venv/bin/streamlit"
else
    STREAMLIT="streamlit"
fi

$STREAMLIT run screener/app.py \
    --server.port 8510 \
    --server.headless true \
    --theme.base dark \
    --theme.primaryColor "#E6B800" \
    --theme.backgroundColor "#0D1117" \
    --theme.secondaryBackgroundColor "#161B22" \
    --theme.textColor "#c9d1d9"
