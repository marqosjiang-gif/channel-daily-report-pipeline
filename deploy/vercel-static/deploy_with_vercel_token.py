#!/usr/bin/env python3
"""Deploy the static dashboard to Vercel with a bearer token.

Usage:
  VERCEL_TOKEN=... python3 deploy_with_vercel_token.py
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


API = "https://api.vercel.com"
PROJECT = os.environ.get("VERCEL_PROJECT", "channel-dashboard-demo")
ROOT = Path(__file__).resolve().parent


def request(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Vercel API failed: HTTP {exc.code}\n{detail}") from exc


def main() -> int:
    token = os.environ.get("VERCEL_TOKEN")
    if not token:
        raise SystemExit("Please set VERCEL_TOKEN before running this script.")

    index = (ROOT / "index.html").read_text(encoding="utf-8")
    package = (ROOT / "package.json").read_text(encoding="utf-8")
    vercel_json = (ROOT / "vercel.json").read_text(encoding="utf-8")

    body = {
        "name": PROJECT,
        "target": "production",
        "projectSettings": {
            "framework": None,
            "buildCommand": None,
            "devCommand": None,
            "installCommand": None,
            "outputDirectory": ".",
        },
        "files": [
            {"file": "index.html", "data": index},
            {"file": "package.json", "data": package},
            {"file": "vercel.json", "data": vercel_json},
        ],
    }
    deployment = request("POST", "/v13/deployments?skipAutoDetectionConfirmation=1&forceNew=1", token, body)
    dep_id = deployment.get("id")
    url = deployment.get("url")
    if not dep_id or not url:
        print(json.dumps(deployment, ensure_ascii=False, indent=2))
        raise SystemExit("Deployment response did not include id/url.")

    for _ in range(60):
        status = request("GET", f"/v13/deployments/{dep_id}", token)
        state = status.get("readyState") or status.get("status")
        if state == "READY":
            print("https://" + status.get("url", url))
            return 0
        if state in {"ERROR", "CANCELED"}:
            print(json.dumps(status, ensure_ascii=False, indent=2))
            raise SystemExit(f"Deployment failed: {state}")
        time.sleep(2)

    print("https://" + url)
    raise SystemExit("Deployment created but did not become READY within the wait window.")


if __name__ == "__main__":
    raise SystemExit(main())
