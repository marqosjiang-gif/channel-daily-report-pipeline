#!/usr/bin/env python3
"""Run the channel daily report workflow."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import smtplib
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_CACHE = PROJECT_ROOT / "data/store_counts/store_counts_cumulative_cache.json"
STORE_COUNT_MERGER = PROJECT_ROOT / "skills/store-count-collector/scripts/merge_store_count_cache.py"
DASHBOARD_BUILDER = PROJECT_ROOT / "skills/dashboard-builder/scripts/build_dashboard.py"
OUTPUT_DIR = PROJECT_ROOT / "output/dashboard"
REPORT_OUTPUT_DIR = PROJECT_ROOT / "data/store_counts"
SMTP_CONFIG_PATH = PROJECT_ROOT / "config/smtp_config.json"
RUN_LOG_PATH = PROJECT_ROOT / "output/logs/channel_daily_report_run_log.jsonl"
EMAIL_LOG_PATH = PROJECT_ROOT / "output/logs/email_delivery_log.jsonl"
REPORT_START_DATE = date(2026, 1, 1)
RECIPIENT = os.environ.get("RECIPIENT_EMAIL", "")
EMAIL_GREETING = os.environ.get("EMAIL_GREETING", "您好")
EMAIL_BODY = f"{EMAIL_GREETING}，截止昨日渠道经营数据看板已更新，如下："

# 国办发明电〔2025〕7号，2026年部分节假日安排。
HOLIDAYS_2026 = {
    "2026-01-01",
    "2026-01-02",
    "2026-01-03",
    "2026-02-15",
    "2026-02-16",
    "2026-02-17",
    "2026-02-18",
    "2026-02-19",
    "2026-02-20",
    "2026-02-21",
    "2026-02-22",
    "2026-02-23",
    "2026-04-04",
    "2026-04-05",
    "2026-04-06",
    "2026-05-01",
    "2026-05-02",
    "2026-05-03",
    "2026-05-04",
    "2026-05-05",
    "2026-06-19",
    "2026-06-20",
    "2026-06-21",
    "2026-09-25",
    "2026-09-26",
    "2026-09-27",
    "2026-10-01",
    "2026-10-02",
    "2026-10-03",
    "2026-10-04",
    "2026-10-05",
    "2026-10-06",
    "2026-10-07",
}
MAKEUP_WORKDAYS_2026 = {
    "2026-01-04",
    "2026-02-14",
    "2026-02-28",
    "2026-05-09",
    "2026-09-20",
    "2026-10-10",
}


@dataclass
class ExcelCoverage:
    path: Path
    start_date: date
    end_date: date


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run channel daily report workflow.")
    parser.add_argument("--run-date", help="Execution date in YYYY-MM-DD, defaults to today.")
    parser.add_argument("--excel", help="Optional backend export excel. Auto-discovered when omitted.")
    parser.add_argument(
        "--store-count-input",
        action="append",
        default=[],
        help="Additional JSON/CSV store-count files to merge before rendering.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Build outputs without sending email.")
    return parser.parse_args()


def today_local() -> date:
    return datetime.now().date()


def parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def list_missing_dates(rows: list[dict[str, Any]], target_end: date) -> list[str]:
    seen = {str(row.get("date") or row.get("日期")).strip() for row in rows}
    missing: list[str] = []
    cursor = REPORT_START_DATE
    while cursor <= target_end:
        if cursor.isoformat() not in seen:
            missing.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return missing


def load_canonical_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return list(payload.get("results") or payload.get("rows") or [])
    if isinstance(payload, list):
        return payload
    return []


def is_china_workday(day: date) -> tuple[bool, str]:
    if day.year != 2026:
        if day.weekday() >= 5:
            return False, f"{day.isoformat()} 为周末，且当前脚本未内置 {day.year} 年调休规则"
        return True, f"{day.isoformat()} 为工作日，当前脚本未内置 {day.year} 年调休规则，按普通周内工作日处理"

    iso = day.isoformat()
    if iso in MAKEUP_WORKDAYS_2026:
        return True, f"{iso} 为 2026 年法定调休工作日"
    if iso in HOLIDAYS_2026:
        return False, f"{iso} 为 2026 年法定节假日"
    if day.weekday() >= 5:
        return False, f"{iso} 为周末，且不属于 2026 年调休工作日"
    return True, f"{iso} 为普通工作日"


def read_excel_coverage(path: Path) -> ExcelCoverage:
    raw = pd.read_excel(path, header=None)
    header_idx = None
    for index in range(min(30, len(raw))):
        values = [str(item).strip() for item in raw.iloc[index].tolist()]
        if {"日期", "渠道", "售卖门店数"}.issubset(set(values)):
            header_idx = index
            break
    if header_idx is None:
        raise ValueError(f"{path} 未找到 日期/渠道/售卖门店数 表头")

    df = pd.read_excel(path, header=header_idx)
    detail = df[df["日期"].astype(str).str.strip() != "总计："].copy()
    detail["日期"] = pd.to_datetime(detail["日期"], errors="coerce")
    detail = detail[detail["日期"].notna()]
    if detail.empty:
        raise ValueError(f"{path} 没有可用明细日期")
    start = detail["日期"].min().date()
    end = detail["日期"].max().date()
    return ExcelCoverage(path=path, start_date=start, end_date=end)


def discover_excel(explicit: str | None) -> ExcelCoverage:
    """Find the cumulative Excel: explicit arg -> $CHANNEL_EXCEL_PATH -> newest in data/excel."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env_path = os.environ.get("CHANNEL_EXCEL_PATH", "")
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.extend(sorted((PROJECT_ROOT / "data/excel").glob("daily_channel_orders_*.xlsx"), reverse=True))
    seen: set[Path] = set()
    valid: list[ExcelCoverage] = []
    for candidate in candidates:
        if candidate in seen or not candidate.exists():
            continue
        seen.add(candidate)
        try:
            valid.append(read_excel_coverage(candidate))
        except Exception:
            continue
    if not valid:
        raise FileNotFoundError("未找到可用的每日渠道出单数据 Excel（data/excel/daily_channel_orders_*.xlsx）")
    valid.sort(key=lambda item: (item.end_date, item.path.stat().st_mtime), reverse=True)
    return valid[0]


def run_subprocess(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"command failed: {command}")
    text = result.stdout.strip()
    return json.loads(text) if text.startswith("{") else {"stdout": text}


def merge_store_counts(target_end: date, extra_inputs: list[str]) -> dict[str, str]:
    command = [
        "python3",
        str(STORE_COUNT_MERGER),
        "--start-date",
        REPORT_START_DATE.isoformat(),
        "--end-date",
        target_end.isoformat(),
        "--canonical-cache",
        str(CANONICAL_CACHE),
        "--output-dir",
        str(REPORT_OUTPUT_DIR),
    ]
    for item in extra_inputs:
        command.extend(["--input", item])
    payload = run_subprocess(command)
    outputs = payload.get("outputs") or {}
    return {key: value for key, value in outputs.items() if value}


def build_dashboard(excel: ExcelCoverage, store_counts_json: str) -> dict[str, str]:
    command = [
        "python3",
        str(DASHBOARD_BUILDER),
        "--excel",
        str(excel.path),
        "--store-counts",
        store_counts_json,
        "--output-dir",
        str(OUTPUT_DIR),
    ]
    payload = run_subprocess(command)
    outputs = {key: value for key, value in payload.items() if key in {"html", "png", "json"} and value}
    diff = payload.get("diff") or {}
    if any(abs(float(value)) > 0 for value in diff.values()):
        raise RuntimeError(f"后台校验 diff 非零: {diff}")
    return outputs


def load_smtp_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def send_email(subject: str, png_path: Path, smtp_config: dict[str, Any]) -> None:
    message = MIMEMultipart("related")
    message["Subject"] = subject
    message["From"] = smtp_config["sender_email"]
    message["To"] = RECIPIENT

    alternative = MIMEMultipart("alternative")
    message.attach(alternative)
    html = f"""<html><body><p>{EMAIL_BODY}</p><img src="cid:channel_daily_png" style="max-width:100%;height:auto;" /></body></html>"""
    alternative.attach(MIMEText(html, "html", "utf-8"))

    mime_type, _ = mimetypes.guess_type(str(png_path))
    image_subtype = (mime_type or "image/png").split("/")[-1]
    image_part = MIMEImage(png_path.read_bytes(), _subtype=image_subtype)
    image_part.add_header("Content-ID", "<channel_daily_png>")
    image_part.add_header("Content-Disposition", "inline", filename=png_path.name)
    message.attach(image_part)

    with smtplib.SMTP_SSL(smtp_config["smtp_server"], int(smtp_config["smtp_port"]), timeout=30) as server:
        server.login(smtp_config["smtp_user"], smtp_config["smtp_password"])
        server.sendmail(smtp_config["sender_email"], [RECIPIENT], message.as_string())


def main() -> int:
    args = parse_args()
    run_date = parse_day(args.run_date) if args.run_date else today_local()
    target_end = run_date - timedelta(days=1)
    subject = f"渠道日报｜截止{target_end.isoformat()}"
    is_workday, workday_reason = is_china_workday(run_date)

    rows = load_canonical_rows(CANONICAL_CACHE)
    missing_dates = list_missing_dates(rows, target_end)
    query_range = f"{REPORT_START_DATE.isoformat()} 至 {target_end.isoformat()}"
    base_record: dict[str, Any] = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "run_date": run_date.isoformat(),
        "target_end_date": target_end.isoformat(),
        "workday_reason": workday_reason,
        "query_range": query_range,
        "missing_backfill_dates": missing_dates,
        "store_count_inputs": args.store_count_input,
        "outputs": {},
        "email_subject": subject,
    }

    if not is_workday:
        base_record["status"] = "skipped_non_workday"
        append_jsonl(RUN_LOG_PATH, base_record)
        return 0

    excel = discover_excel(args.excel)
    base_record["excel_path"] = str(excel.path)
    base_record["excel_start_date"] = excel.start_date.isoformat()
    base_record["excel_end_date"] = excel.end_date.isoformat()

    block_reasons: list[str] = []
    if missing_dates and not args.store_count_input:
        block_reasons.append(
            "累计缓存缺少日期，需先通过渠道后台补查并提供新增 store-count 文件: " + ", ".join(missing_dates)
        )
    if excel.end_date < target_end:
        block_reasons.append(
            f"后台导出 Excel 仅覆盖到 {excel.end_date.isoformat()}，未覆盖截止日期 {target_end.isoformat()}"
        )
    if block_reasons:
        base_record["status"] = "blocked_missing_inputs"
        base_record["block_reasons"] = block_reasons
        append_jsonl(RUN_LOG_PATH, base_record)
        return 2

    merged_outputs = merge_store_counts(target_end, args.store_count_input)
    base_record["outputs"].update(merged_outputs)
    store_counts_json = merged_outputs["json"]
    dashboard_outputs = build_dashboard(excel, store_counts_json)
    base_record["outputs"].update(dashboard_outputs)

    smtp_config = load_smtp_config(SMTP_CONFIG_PATH)
    append_jsonl(
        EMAIL_LOG_PATH,
        {
            "time": datetime.now().isoformat(timespec="seconds"),
            "type": "channel_daily_report",
            "recipient": RECIPIENT,
            "subject": subject,
            "png": dashboard_outputs["png"],
            "status": "pending",
        },
    )
    if args.dry_run:
        base_record["status"] = "dry_run_ready"
        append_jsonl(RUN_LOG_PATH, base_record)
        return 0

    send_email(subject, Path(dashboard_outputs["png"]), smtp_config)
    append_jsonl(
        EMAIL_LOG_PATH,
        {
            "time": datetime.now().isoformat(timespec="seconds"),
            "type": "channel_daily_report",
            "recipient": RECIPIENT,
            "subject": subject,
            "png": dashboard_outputs["png"],
            "status": "sent",
        },
    )
    base_record["status"] = "sent"
    append_jsonl(RUN_LOG_PATH, base_record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
