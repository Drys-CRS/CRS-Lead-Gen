#!/usr/bin/env bash
set -euo pipefail

# Turn the Space's env-var Secrets into a Streamlit secrets.toml so the app's
# existing st.secrets.get(...) / st.secrets[...] calls work without any code
# changes.
python make_secrets.py

# Launch Streamlit on the HF Spaces port. CORS/XSRF are disabled because the
# app is served inside the Spaces proxy iframe (avoids websocket failures).
exec streamlit run app/streamlit_app.py \
  --server.port=7860 \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --server.enableCORS=false \
  --server.enableXsrfProtection=false