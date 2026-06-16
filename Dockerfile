# CRS Competitive Intelligence — Hugging Face Spaces (Docker SDK)
# Runs the existing Streamlit app with no code changes. Secrets are injected
# from the Space's "Secrets" settings (env vars) into a Streamlit secrets.toml
# at container startup, so every st.secrets.get(...) call keeps working.

FROM python:3.11-slim

# HF Spaces run containers as UID 1000. Match it so $HOME is writable
# (Streamlit writes ~/.streamlit; we also write the secrets file there).
RUN useradd -m -u 1000 user
USER user

ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /home/user/app

# Install dependencies first for better layer caching
COPY --chown=user requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the repo (expects app/streamlit_app.py, app/monday_client.py,
# app/assets/… at these paths relative to the repo root)
COPY --chown=user . .

RUN chmod +x entrypoint.sh

# HF Spaces routes traffic to this port by default (matches app_port in README)
EXPOSE 7860

ENTRYPOINT ["./entrypoint.sh"]