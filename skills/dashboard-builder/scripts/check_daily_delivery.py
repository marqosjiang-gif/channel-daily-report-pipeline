#!/usr/bin/env python3
"""Check whether the daily dashboard email has been verified as sent."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


def parse_date(value: str | None) -> date:
    if value:
        return date.fromisoformat(value)
    return date.today()


def iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                yield {"_invalid": line}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify daily email delivery log.")
    parser.add_argument("--log", required=True, help="email_delivery_log.jsonl")
    parser.add_argument("--run-date", default="", help="YYYY-MM-DD, defaults to today")
    parser.add_argument("--recipient", default=os.environ.get("RECIPIENT_EMAIL", ""), help="Defaults to $RECIPIENT_EMAIL")
    parser.add_argument("--notify-on-failure", action="store_true", help="Show a local macOS notification when delivery is not verified.")
    args = parser.parse_args()

    run_date = parse_date(args.run_date)
    cutoff = run_date - timedelta(days=1)
    subject = f"渠道日报｜截止{cutoff.isoformat()}"
    log_path = Path(args.log).expanduser()
    matches = []

    for row in iter_jsonl(log_path) or []:
        if (
            row.get("status") == "verified_sent_visible"
            and row.get("subject") == subject
            and str(row.get("recipient", "")).lower() == args.recipient.lower()
        ):
            matches.append(row)

    result = {
        "run_date": run_date.isoformat(),
        "cutoff_date": cutoff.isoformat(),
        "expected_subject": subject,
        "recipient": args.recipient,
        "log": str(log_path),
        "verified": bool(matches),
        "matched_count": len(matches),
        "latest_match": matches[-1] if matches else None,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not matches and args.notify_on_failure:
        message = f"缺少 {subject} 的 verified_sent_visible 记录；卡在邮件完成校验。"
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification {json.dumps(message, ensure_ascii=False)} with title "日报未完成"',
            ],
            check=False,
        )
    return 0 if matches else 2


if __name__ == "__main__":
    raise SystemExit(main())
