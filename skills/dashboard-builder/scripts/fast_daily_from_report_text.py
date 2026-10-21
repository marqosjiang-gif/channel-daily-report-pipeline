#!/usr/bin/env python3
"""Fast daily pipeline from one report page text to dashboard/email outputs.

Pipeline: parse report text -> validate totals (diff must be 0) -> merge
store-count cache -> append cumulative Excel -> render dashboard -> optional
strict email send. All runtime paths are relative to the repository root (or
the directory given via --project-dir).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]

COLS = ["日期", "渠道", "售卖门店数", "有产门店数", "有产率", "出单率", "取消率", "订单数", "间夜数", "销售金额", "结算金额", "留存金额", "销售ADR"]


def notify(title: str, message: str) -> None:
    """Optional local macOS notification; silently skipped when unavailable."""
    subprocess.run(
        ["osascript", "-e", f'display notification {json.dumps(message, ensure_ascii=False)} with title {json.dumps(title, ensure_ascii=False)}'],
        check=False,
    )


def append_audit(project: Path, record: dict) -> None:
    path = project / "output/audit/automation_run_audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"), **record}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def pct_or_num(value: str) -> float:
    value = str(value).strip().replace(",", "")
    if value.endswith("%"):
        return float(value[:-1]) / 100
    return float(value or 0)


def parse_report_text(text: str, target_date: str) -> tuple[pd.DataFrame, dict]:
    """Parse tab-separated report page text; validate detail rows against the 总计 row."""
    rows: list[dict] = []
    total: dict | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if parts[0] not in {target_date, "总计："}:
            continue
        core = parts[: len(COLS)]
        if len(core) < len(COLS):
            continue
        rec = dict(zip(COLS, core))
        if parts[0] == "总计：":
            total = rec
        else:
            rows.append(rec)

    if not rows:
        raise ValueError(f"未解析到 {target_date} 明细行")
    if not total:
        raise ValueError("未解析到总计行，不能猜数")

    for rec in rows:
        for col in ["售卖门店数", "有产门店数", "订单数", "间夜数"]:
            rec[col] = int(float(str(rec[col]).replace(",", "")))
        for col in ["有产率", "出单率", "取消率", "销售金额", "结算金额", "留存金额", "销售ADR"]:
            rec[col] = pct_or_num(rec[col])

    df = pd.DataFrame(rows, columns=COLS)
    total_norm = {
        "stores": int(float(str(total["售卖门店数"]).replace(",", ""))),
        "productive": int(float(str(total["有产门店数"]).replace(",", ""))),
        "orders": int(float(str(total["订单数"]).replace(",", ""))),
        "nights": int(float(str(total["间夜数"]).replace(",", ""))),
        "sales": round(float(str(total["销售金额"]).replace(",", "")), 2),
        "settlement": round(float(str(total["结算金额"]).replace(",", "")), 2),
        "retention": round(float(str(total["留存金额"]).replace(",", "")), 2),
        "adr": round(float(str(total["销售ADR"]).replace(",", "")), 6),
    }
    computed = {
        "orders": int(df["订单数"].sum()),
        "nights": int(df["间夜数"].sum()),
        "sales": round(float(df["销售金额"].sum()), 2),
        "settlement": round(float(df["结算金额"].sum()), 2),
        "retention": round(float(df["留存金额"].sum()), 2),
        "adr": round(float(df["销售金额"].sum()) / float(df["间夜数"].sum()), 6) if float(df["间夜数"].sum()) else 0,
    }
    diff = {k: round(computed[k] - total_norm[k], 6) for k in computed}
    bad = {k: v for k, v in diff.items() if abs(v) > (0.01 if k in {"sales", "settlement", "retention", "adr"} else 0)}
    if bad:
        raise ValueError(f"{target_date} 明细与总计行不一致: {bad}")
    return df, total_norm


def find_previous_excel(project: Path, prev_date: str) -> Path:
    exact = project / f"data/excel/daily_channel_orders_20260101_{prev_date.replace('-', '')}.xlsx"
    if exact.exists():
        return exact
    candidates = sorted((project / "data/excel").glob("daily_channel_orders_20260101_*.xlsx"))
    if not candidates:
        raise FileNotFoundError("未找到上一期累计 Excel")
    return candidates[-1]


def update_store_cache(project: Path, start_date: str, target_date: str, store_count: int) -> Path:
    inc = project / f"data/store_counts/store_counts_increment_{target_date.replace('-', '')}.json"
    inc.write_text(
        json.dumps(
            {
                "results": [{"date": target_date, "store_count": store_count}],
                "failures": [],
                "meta": {"start_date": target_date, "end_date": target_date, "source": "渠道后台报表DOM文本总计行", "row_count": 1},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    merge_script = REPO_ROOT / "skills/store-count-collector/scripts/merge_store_count_cache.py"
    subprocess.run(
        [
            sys.executable,
            str(merge_script),
            "--start-date",
            start_date,
            "--end-date",
            target_date,
            "--canonical-cache",
            str(project / "data/store_counts/store_counts_cumulative_cache.json"),
            "--input",
            str(inc),
            "--output-dir",
            str(project / "data/store_counts"),
            "--prefix",
            "store_counts_daily",
        ],
        check=True,
    )
    return project / f"data/store_counts/store_counts_daily_{start_date.replace('-', '')}_{target_date.replace('-', '')}.json"


def build_combined_excel(project: Path, target_date: str, day_df: pd.DataFrame, day_total: dict) -> Path:
    prev_date = (datetime.fromisoformat(target_date).date() - timedelta(days=1)).isoformat()
    prev = pd.read_excel(find_previous_excel(project, prev_date))
    detail = prev[prev["日期"].astype(str).str.strip() != "总计："].copy()
    combined = pd.concat([detail, day_df], ignore_index=True)
    for col in ["售卖门店数", "有产门店数", "订单数", "间夜数", "销售金额", "结算金额", "留存金额"]:
        combined[col] = pd.to_numeric(combined[col], errors="coerce").fillna(0)

    total_row = {c: "" for c in COLS}
    total_row["日期"] = "总计："
    total_row["售卖门店数"] = day_total["stores"]
    total_row["有产门店数"] = int(combined["有产门店数"].sum())
    total_row["订单数"] = int(combined["订单数"].sum())
    total_row["间夜数"] = int(combined["间夜数"].sum())
    total_row["销售金额"] = round(float(combined["销售金额"].sum()), 2)
    total_row["结算金额"] = round(float(combined["结算金额"].sum()), 2)
    total_row["留存金额"] = round(float(combined["留存金额"].sum()), 2)
    total_row["销售ADR"] = round(total_row["销售金额"] / total_row["间夜数"], 6) if total_row["间夜数"] else 0
    total_row["有产率"] = round(total_row["有产门店数"] / total_row["售卖门店数"], 6) if total_row["售卖门店数"] else 0
    total_row["出单率"] = round(total_row["订单数"] / total_row["售卖门店数"], 6) if total_row["售卖门店数"] else 0
    total_row["取消率"] = 0

    out = project / f"data/excel/daily_channel_orders_20260101_{target_date.replace('-', '')}.xlsx"
    pd.concat([combined, pd.DataFrame([total_row], columns=COLS)], ignore_index=True).to_excel(out, index=False)
    return out


def build_dashboard(project: Path, excel: Path, store_counts: Path, skip_png: bool = False) -> dict:
    script = REPO_ROOT / "skills/dashboard-builder/scripts/build_dashboard.py"
    cmd = [
        sys.executable,
        str(script),
        "--excel",
        str(excel),
        "--store-counts",
        str(store_counts),
        "--output-dir",
        str(project / "output/dashboard"),
        "--prefix",
        "channel_dashboard",
    ]
    if skip_png:
        cmd.append("--no-png")
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(proc.stdout)


def send_email(project: Path, target_date: str, png: Path) -> dict:
    script = REPO_ROOT / "skills/dashboard-builder/scripts/send_daily_email.py"
    recipient = os.environ.get("RECIPIENT_EMAIL", "")
    if not recipient:
        raise RuntimeError("缺少 RECIPIENT_EMAIL 环境变量，无法发送邮件")
    greeting = os.environ.get("EMAIL_GREETING", "您好")
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--smtp-config",
            str(project / "config/smtp_config.json"),
            "--png",
            str(png),
            "--recipient",
            recipient,
            "--subject",
            f"渠道日报｜截止{target_date}",
            "--body",
            f"{greeting}，截止昨日渠道经营数据看板已更新，如下：",
            "--log",
            str(project / "output/logs/email_delivery_log.jsonl"),
        ],
        capture_output=True,
        text=True,
    )
    output = proc.stdout if proc.returncode == 0 else proc.stderr
    try:
        result = json.loads(output)
    except json.JSONDecodeError:
        result = {"status": "failed", "raw_output": output}
    if proc.returncode != 0:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast daily pipeline from report page text.")
    parser.add_argument("--project-dir", default=str(REPO_ROOT))
    parser.add_argument("--date", required=True, help="Target report date, YYYY-MM-DD")
    parser.add_argument("--start-date", default="2026-01-01", help="Season start date for cumulative caches")
    parser.add_argument("--report-text", help="Text file copied from the report page. Reads stdin when omitted.")
    parser.add_argument("--send-email", action="store_true")
    parser.add_argument("--skip-png", action="store_true", help="Skip PNG rendering (HTML only); useful when playwright/node is unavailable")
    parser.add_argument("--notify-on-failure", action="store_true")
    args = parser.parse_args()

    project = Path(args.project_dir).expanduser()
    started = time.perf_counter()
    append_audit(project, {"automation": "channel_daily_report", "run_date": datetime.now().date().isoformat(), "cutoff_date": args.date, "status": "fast_pipeline_started"})
    try:
        text = Path(args.report_text).read_text(encoding="utf-8") if args.report_text else sys.stdin.read()
        day_df, day_total = parse_report_text(text, args.date)
        report_text_path = project / f"data/report_text/channel_report_text_{args.date.replace('-', '')}.txt"
        report_text_path.parent.mkdir(parents=True, exist_ok=True)
        report_text_path.write_text(text, encoding="utf-8")

        store_counts = update_store_cache(project, args.start_date, args.date, day_total["stores"])
        excel = build_combined_excel(project, args.date, day_df, day_total)
        dashboard = build_dashboard(project, excel, store_counts, skip_png=args.skip_png)
        email_result = send_email(project, args.date, Path(dashboard["png"])) if args.send_email else None
        status = email_result.get("status") if email_result else "dashboard_built"
        result = {
            "status": status,
            "target_date": args.date,
            "day_total": day_total,
            "excel": str(excel),
            "store_counts": str(store_counts),
            "dashboard": dashboard,
            "email": email_result,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
        }
        append_audit(project, {"automation": "channel_daily_report", "run_date": datetime.now().date().isoformat(), "cutoff_date": args.date, "status": status, "elapsed_seconds": result["elapsed_seconds"]})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        message = f"截止 {args.date}：{exc}"
        append_audit(project, {"automation": "channel_daily_report", "run_date": datetime.now().date().isoformat(), "cutoff_date": args.date, "status": "failed", "error": str(exc)})
        if args.notify_on_failure:
            notify("日报未完成", message)
        print(json.dumps({"status": "failed", "target_date": args.date, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
