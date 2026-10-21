#!/usr/bin/env python3
"""Write daily store-count results to a Markdown table."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def load_rows(path: Path) -> list[dict[str, object]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("rows", data.get("results", []))
        return list(data)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Markdown for daily store-count results.")
    parser.add_argument("--input", required=True, help="JSON or CSV with date/store_count fields")
    parser.add_argument("--output", default="./data/store_counts/store_counts_daily.md")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    args = parser.parse_args()

    rows = load_rows(Path(args.input).expanduser())
    normalized = []
    for row in rows:
        date = str(row.get("date") or row.get("日期") or "").strip()
        count = str(row.get("store_count") or row.get("售卖门店数") or "").strip()
        if not date or not count:
            continue
        normalized.append({"date": date, "store_count": int(float(count.replace(",", "")))})
    normalized.sort(key=lambda r: r["date"])

    lines = [
        "# 渠道日售卖门店数取数",
        "",
        f"- 日期范围：{args.start_date} 至 {args.end_date}",
        "- 取数口径：逐日查询后台报表，读取最后一行“总计：”的“售卖门店数”列",
        "- 查询方式：每天单独设置开始时间=结束时间",
        "",
        "| 日期 | 售卖门店数 |",
        "|---|---:|",
    ]
    lines.extend(f"| {row['date']} | {row['store_count']} |" for row in normalized)
    lines.append("")

    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
