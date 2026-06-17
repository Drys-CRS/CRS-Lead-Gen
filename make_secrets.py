#!/usr/bin/env python3
"""
make_secrets.py — bridge HF Spaces "Secrets" (env vars) into a Streamlit
secrets.toml, so the existing app's st.secrets.get(...) calls need no changes.

Runs once at container startup (see entrypoint.sh). Only keys that are actually
set in the environment are written; missing keys are simply skipped, exactly
like an optional secret in Streamlit Cloud.

Add a key to ALLOWED_KEYS if the app ever reads a new st.secrets value, or set
EXTRA_SECRET_KEYS="FOO,BAR" in the Space to pass extras without editing this file.
"""

import os
import json
import pathlib

# Every key the CRS app reads via st.secrets, across all tabs/modules.
ALLOWED_KEYS = [
    # Core
    "SUPABASE_URL", "SUPABASE_KEY",
    "MONDAY_API_KEY",
    # AI providers (cascade)
    "GEMINI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY", "OPENROUTER_API_KEY",
    "GITHUB_TOKEN", "GH_PAT", "NVIDIA_API_KEY", "DEEPSEEK_API_KEY",
    # Lead enrichment / verification
    "APOLLO_API_KEY", "LUSHA_API_KEY", "HUNTER_API_KEY",
    # Threat intel / news
    "FLARE_API_KEY", "FLARE_TENANT_ID", "NEWSAPI_KEY",
    # Search / dorking
    "GOOGLE_API_KEY", "GOOGLE_CSE_ID", "SERPER_API_KEY", "SERPAPI_API_KEY",
    # Optional in-app password gate
    "APP_PASSWORD",
]

extra = os.environ.get("EXTRA_SECRET_KEYS", "")
keys = list(dict.fromkeys(ALLOWED_KEYS + [k.strip() for k in extra.split(",") if k.strip()]))


def _toml_escape(value: str) -> str:
    # json.dumps uses the same escape sequences as TOML basic strings
    # (handles \n, \r, \t, \b, \f, \\, \" and all control chars correctly).
    # Strip the surrounding double-quotes that json.dumps adds.
    return json.dumps(value)[1:-1]


def main():
    lines, written = [], 0
    for k in keys:
        v = os.environ.get(k)
        if v is None or v == "":
            continue
        lines.append(f'{k} = "{_toml_escape(v)}"')
        written += 1

    dest = pathlib.Path.home() / ".streamlit" / "secrets.toml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Don't print values — just the count and which keys were found.
    found = [k for k in keys if os.environ.get(k)]
    print(f"make_secrets: wrote {written} secret(s) to {dest}: {', '.join(found)}")


if __name__ == "__main__":
    main()