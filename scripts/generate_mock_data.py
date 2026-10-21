#!/usr/bin/env python3
"""Generate reproducible mock data for the demo.

All numbers are FICTIONAL and deliberately kept far away from any real
business scale (store counts in the low hundreds, daily orders in the tens).

Outputs (committed under data/mock/):
  excel/daily_channel_orders_20260101_20260531.xlsx   season-to-date cumulative Excel
  report_text/channel_report_text_20260605.txt        one day of FineReport-style page text
  store_counts/store_counts_increment_20260605.json   single-day store-count cache
  store_counts/store_counts_cumulative_cache.json     season-to-date store-count cache
  logs/email_delivery_log.jsonl                        synthetic delivery audit log
  logs/automation_run_audit.jsonl                      synthetic run audit log
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
MOCK = REPO_ROOT / "data/mock"

SEASON_START = date(2026, 1, 1)
THROUGH_END = date(2026, 6, 4)  # cumulative data covers through this day
TARGET_DATE = date(2026, 6, 5)  # the demo "cutoff" day to be ingested

CHANNELS = ["OTA-A", "OTA-B", "OTA-C", "直销官网", "团购-A", "企业直连", "小程序", "APP"]
COLS = ["日期", "渠道", "售卖门店数", "有产门店数", "有产率", "出单率", "取消率", "订单数", "间夜数", "销售金额", "结算金额", "留存金额", "销售ADR"]

random.seed(42)


def day_stores(d: date) -> int:
    """Total selling stores for the day: 118-136, slowly trending up."""
    return 118 + (d - SEASON_START).days % 16 + random.randint(0, 2)


def channel_row(d: date, channel: str, total_stores: int) -> dict:
    """One detail row. Only a few channels actually produce orders on a given day."""
    active = random.random() < 0.45
    stores = random.randint(max(1, total_stores // 12), max(2, total_stores // 8)) if active else random.randint(1, total_stores)
    if not active:
        stores = min(stores, total_stores)
        productive = orders = nights = 0
        sales = settlement = retention = adr = 0.0
    else:
        productive = random.randint(1, max(1, stores // 6))
        orders = random.randint(1, 12)
        nights = orders + random.randint(0, 4)
        adr = round(random.uniform(280, 380), 2)
        sales = round(nights * adr, 2)
        settlement = round(sales * random.uniform(0.96, 1.0), 2)
        retention = round(sales - settlement, 2)
    return {
        "日期": d.isoformat(),
        "渠道": channel,
        "售卖门店数": stores,
        "有产门店数": productive,
        "有产率": round(productive / stores, 6) if stores else 0,
        "出单率": round(orders / stores, 6) if stores else 0,
        "取消率": 0,
        "订单数": orders,
        "间夜数": nights,
        "销售金额": sales,
        "结算金额": settlement,
        "留存金额": retention,
        "销售ADR": round(sales / nights, 6) if nights else 0,
    }


def build_day_rows(d: date) -> list[dict]:
    total_stores = day_stores(d)
    return [channel_row(d, ch, total_stores) for ch in CHANNELS]


def write_cumulative_excel(path: Path) -> None:
    rows: list[dict] = []
    d = SEASON_START
    while d <= THROUGH_END:
        rows.extend(build_day_rows(d))
        d += timedelta(days=1)
    pd.DataFrame(rows, columns=COLS).to_excel(path, index=False)


def fmt_num(v: int) -> str:
    return str(v)


def fmt_money(v: float) -> str:
    return f"{v:.2f}"


def fmt_pct(v: float) -> str:
    return f"{v * 100:.2f}%"


def write_report_text(path: Path) -> dict:
    """Write one day of FineReport-style tab-separated page text."""
    rows = build_day_rows(TARGET_DATE)
    # 总计行的售卖门店数是「去重门店数」，不等于渠道明细列求和（与真实报表口径一致）
    total = {
        "stores": day_stores(TARGET_DATE),
        "productive": sum(r["有产门店数"] for r in rows),
        "orders": sum(r["订单数"] for r in rows),
        "nights": sum(r["间夜数"] for r in rows),
        "sales": round(sum(r["销售金额"] for r in rows), 2),
        "settlement": round(sum(r["结算金额"] for r in rows), 2),
        "retention": round(sum(r["留存金额"] for r in rows), 2),
    }
    total["adr"] = round(total["sales"] / total["nights"], 6) if total["nights"] else 0

    lines = [
        "OTA渠道:",
        "开始时间:",
        TARGET_DATE.isoformat(),
        "结束时间:",
        TARGET_DATE.isoformat(),
        "查询",
        "\t" * 30,
        "\t".join(COLS) + "\t" * 30,
    ]
    for r in rows:
        lines.append(
            "\t".join(
                [
                    r["日期"],
                    r["渠道"],
                    fmt_num(r["售卖门店数"]),
                    fmt_num(r["有产门店数"]),
                    fmt_pct(r["有产率"]),
                    fmt_pct(r["出单率"]),
                    fmt_pct(r["取消率"]),
                    fmt_num(r["订单数"]),
                    fmt_num(r["间夜数"]),
                    fmt_money(r["销售金额"]),
                    fmt_money(r["结算金额"]),
                    fmt_money(r["留存金额"]),
                    f"{r['销售ADR']:.2f}",
                ]
            )
            + "\t" * 6
        )
    lines.append(
        "\t".join(
            [
                "总计：",
                "",
                fmt_num(total["stores"]),
                fmt_num(total["productive"]),
                fmt_pct(total["productive"] / total["stores"]),
                fmt_pct(total["orders"] / total["stores"]),
                "1.20%",
                fmt_num(total["orders"]),
                fmt_num(total["nights"]),
                fmt_money(total["sales"]),
                fmt_money(total["settlement"]),
                fmt_money(total["retention"]),
                f"{total['adr']:.2f}",
            ]
        )
        + "\t" * 30
    )
    lines.append("\t" * 30)
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return total


def write_store_counts() -> None:
    inc = {
        "results": [],
        "failures": [],
        "meta": {"source": "mock", "row_count": 0},
    }
    cumulative: list[dict] = []
    d = SEASON_START
    while d <= THROUGH_END:
        cumulative.append({"date": d.isoformat(), "store_count": day_stores(d)})
        d += timedelta(days=1)
    cache_payload = {
        "results": cumulative,
        "failures": [],
        "meta": {
            "start_date": SEASON_START.isoformat(),
            "end_date": THROUGH_END.isoformat(),
            "source": "mock（虚构数据，仅用于演示）",
            "row_count": len(cumulative),
            "cache_policy": "incremental_merge",
        },
    }
    (MOCK / "store_counts/store_counts_cumulative_cache.json").write_text(
        json.dumps(cache_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_synthetic_logs() -> None:
    subject = f"渠道日报｜截止{TARGET_DATE.isoformat()}"
    email_log = [
        {"ts": "2026-06-06T08:31:02+08:00", "recipient": "ops@example.com", "subject": subject, "png": "output/dashboard/channel_dashboard_mobile_20260101_20260605.png", "status": "prepared", "sender": "ops@example.com"},
        {"ts": "2026-06-06T08:31:04+08:00", "recipient": "ops@example.com", "subject": subject, "png": "output/dashboard/channel_dashboard_mobile_20260101_20260605.png", "status": "smtp_accepted", "sender": "ops@example.com"},
        {"ts": "2026-06-06T08:31:06+08:00", "recipient": "ops@example.com", "subject": subject, "png": "output/dashboard/channel_dashboard_mobile_20260101_20260605.png", "status": "verified_sent_visible", "mailbox": "\"Sent Messages\"", "uid": "1288", "verified": True, "sender": "ops@example.com"},
    ]
    audit_log = [
        {"ts": "2026-06-06T08:30:58+08:00", "automation": "channel_daily_report", "run_date": "2026-06-06", "cutoff_date": TARGET_DATE.isoformat(), "status": "fast_pipeline_started"},
        {"ts": "2026-06-06T08:31:07+08:00", "automation": "channel_daily_report", "run_date": "2026-06-06", "cutoff_date": TARGET_DATE.isoformat(), "status": "verified_sent_visible", "elapsed_seconds": 9.14},
    ]
    (MOCK / "logs/email_delivery_log.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in email_log) + "\n", encoding="utf-8"
    )
    (MOCK / "logs/automation_run_audit.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in audit_log) + "\n", encoding="utf-8"
    )


def main() -> None:
    for sub in ["excel", "report_text", "store_counts", "logs"]:
        (MOCK / sub).mkdir(parents=True, exist_ok=True)

    write_cumulative_excel(MOCK / f"excel/daily_channel_orders_{SEASON_START:%Y%m%d}_{THROUGH_END:%Y%m%d}.xlsx")
    total = write_report_text(MOCK / f"report_text/channel_report_text_{TARGET_DATE:%Y%m%d}.txt")
    write_store_counts()
    write_synthetic_logs()

    print(json.dumps({"status": "mock_data_generated", "target_date": TARGET_DATE.isoformat(), "day_total": total}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
