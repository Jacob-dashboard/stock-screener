#!/bin/bash
cd "$(dirname "$0")"

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
    --theme.primaryColor "#ff4b4b" \
    --theme.backgroundColor "#0e1117" \
    --theme.secondaryBackgroundColor "#1e2130"
