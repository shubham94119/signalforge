"""Write the browser API endpoint used by the Render static site build."""

from __future__ import annotations

import json
import os
from pathlib import Path


def main() -> None:
    api_base = os.getenv("SIGNALFORGE_API_BASE", "http://127.0.0.1:8000").strip().rstrip("/")
    if not api_base.startswith(("http://", "https://")):
        raise SystemExit("SIGNALFORGE_API_BASE must start with http:// or https://")
    target = Path("apps/web/config.js")
    target.write_text(
        "// Generated during the Render static-site build.\n"
        f"window.SIGNALFORGE_API_BASE = {json.dumps(api_base)};\n",
        encoding="utf-8",
    )
    print(f"Configured SignalForge web API base: {api_base}")


if __name__ == "__main__":
    main()
