#!/usr/bin/env python3
"""Open a small local confirmation UI for a store-count date range."""

from __future__ import annotations

import argparse
import html
import json
import re
import socket
import threading
import time
import urllib.parse
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value: str) -> date:
    if not DATE_RE.match(value):
        raise argparse.ArgumentTypeError(f"Invalid date: {value}; expected YYYY-MM-DD")
    return datetime.strptime(value, "%Y-%m-%d").date()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def build_html(start: str, end: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>确认取数日期</title>
  <style>
    :root {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #172033; background: #f4f7fb; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; }}
    main {{ width: min(520px, calc(100vw - 40px)); background: white; border: 1px solid #d8e2ef; border-radius: 14px; box-shadow: 0 18px 55px rgba(25, 43, 77, .12); padding: 28px; }}
    h1 {{ margin: 0 0 10px; font-size: 24px; }}
    p {{ margin: 0 0 22px; color: #52627a; line-height: 1.6; }}
    label {{ display: block; margin: 14px 0 6px; font-weight: 700; }}
    input {{ box-sizing: border-box; width: 100%; height: 42px; border: 1px solid #cad6e6; border-radius: 8px; padding: 0 12px; font-size: 16px; }}
    .actions {{ display: flex; gap: 12px; margin-top: 24px; }}
    button {{ height: 42px; border: 0; border-radius: 8px; padding: 0 18px; font-weight: 700; cursor: pointer; }}
    .primary {{ background: #1f73f1; color: white; }}
    .secondary {{ background: #e9eef6; color: #23304a; }}
    .note {{ margin-top: 16px; font-size: 13px; color: #718096; }}
  </style>
</head>
<body>
  <main>
    <h1>渠道日售卖门店数取数</h1>
    <p>请确认本次取数日期范围。确认后会按天拆分查询，每天都用同一天作为开始时间和结束时间。</p>
    <form method="post" action="/confirm">
      <label for="start_date">开始日期</label>
      <input id="start_date" name="start_date" type="date" value="{html.escape(start)}" required>
      <label for="end_date">结束日期</label>
      <input id="end_date" name="end_date" type="date" value="{html.escape(end)}" required>
      <div class="actions">
        <button class="primary" type="submit" name="action" value="confirm">确认开始取数</button>
        <button class="secondary" type="submit" name="action" value="cancel">取消</button>
      </div>
    </form>
    <div class="note">取数口径：读取后台报表最后一行“总计：”的“售卖门店数”，不会用渠道最大值代替。</div>
  </main>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Confirm a date range in a local browser UI.")
    parser.add_argument("--start-date", required=True, type=parse_date)
    parser.add_argument("--end-date", required=True, type=parse_date)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    if args.start_date > args.end_date:
        raise SystemExit("start-date must be on or before end-date")

    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    result: dict[str, object] = {}
    done = threading.Event()
    start = args.start_date.isoformat()
    end = args.end_date.isoformat()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *values: object) -> None:
            return

        def do_GET(self) -> None:
            body = build_html(start, end).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            data = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
            action = data.get("action", ["cancel"])[0]
            posted_start = data.get("start_date", [start])[0]
            posted_end = data.get("end_date", [end])[0]
            confirmed = action == "confirm"
            error = None
            try:
                ps = parse_date(posted_start)
                pe = parse_date(posted_end)
                if ps > pe:
                    error = "开始日期不能晚于结束日期"
                    confirmed = False
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                confirmed = False
            result.update(
                {
                    "confirmed": confirmed,
                    "start_date": posted_start,
                    "end_date": posted_end,
                    "error": error,
                }
            )
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            done.set()
            message = "已确认，可以返回 Codex。" if confirmed else "已取消，可以关闭此页。"
            body = f"<html><body style='font-family:sans-serif;padding:32px'><h2>{html.escape(message)}</h2></body></html>".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", free_port()), Handler)
    url = f"http://127.0.0.1:{server.server_port}/"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(url, flush=True)
    if not args.no_open:
        webbrowser.open(url)

    if not done.wait(args.timeout):
        result.update({"confirmed": False, "start_date": start, "end_date": end, "error": "confirmation timed out"})
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        server.shutdown()
        return 2
    server.shutdown()
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result.get("confirmed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
