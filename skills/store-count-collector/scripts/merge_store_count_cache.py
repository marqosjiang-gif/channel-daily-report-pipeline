#!/usr/bin/env python3
"""Merge daily store-count cache files and write dated outputs."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def iter_dates(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def load_rows(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("results") or data.get("rows") or []
        if isinstance(data, dict):
            return [{"date": k, "store_count": v} for k, v in data.items()]
        return list(data)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def normalize_rows(paths: list[Path]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for path in paths:
        for row in load_rows(path):
            day = str(row.get("date") or row.get("日期") or "").strip()
            raw = str(row.get("store_count") or row.get("售卖门店数") or "").strip()
            if not day or not raw:
                continue
            merged[day] = int(float(raw.replace(",", "")))
    return merged


def write_outputs(rows: list[dict[str, int]], start: str, end: str, out_dir: Path, prefix: str, canonical: Path | None) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{prefix}_{start.replace('-', '')}_{end.replace('-', '')}"
    json_path = out_dir / f"{stem}.json"
    csv_path = out_dir / f"{stem}.csv"
    md_path = out_dir / f"{stem}.md"

    payload = {
        "results": rows,
        "failures": [],
        "meta": {
            "start_date": start,
            "end_date": end,
            "row_count": len(rows),
            "source": "渠道后台逐日查询总计行售卖门店数",
            "cache_policy": "incremental_merge",
        },
    }
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    json_path.write_text(json_text, encoding="utf-8")
    if canonical:
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_text(json_text, encoding="utf-8")

    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "store_count"])
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# 渠道日售卖门店数取数",
        "",
        f"- 日期范围：{start} 至 {end}",
        "- 取数口径：逐日查询后台报表，读取最后一行“总计：”的“售卖门店数”列",
        "- 缓存策略：增量累计；每日仅补齐缺失日期后合并输出",
        "",
        "| 日期 | 售卖门店数 |",
        "|---|---:|",
    ]
    lines.extend(f"| {row['date']} | {row['store_count']} |" for row in rows)
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")

    return {"json": str(json_path), "csv": str(csv_path), "md": str(md_path), "canonical": str(canonical) if canonical else ""}


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge incremental daily store-count cache files.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--input", action="append", default=[], help="Existing JSON/CSV cache. Can be repeated.")
    parser.add_argument("--canonical-cache", help="Canonical JSON cache to update.")
    parser.add_argument("--output-dir", default="./data/store_counts")
    parser.add_argument("--prefix", default="store_counts_daily")
    parser.add_argument("--allow-gaps", action="store_true")
    args = parser.parse_args()

    start = parse_date(args.start_date)
    end = parse_date(args.end_date)
    if start > end:
        raise SystemExit("start-date cannot be after end-date")

    input_paths = [Path(p).expanduser() for p in args.input]
    canonical = Path(args.canonical_cache).expanduser() if args.canonical_cache else None
    if canonical:
        input_paths.insert(0, canonical)

    merged = normalize_rows(input_paths)
    expected = [d.isoformat() for d in iter_dates(start, end)]
    missing = [d for d in expected if d not in merged]
    if missing and not args.allow_gaps:
        print(json.dumps({"status": "missing_dates", "missing_dates": missing}, ensure_ascii=False))
        return 2

    rows = [{"date": d, "store_count": merged[d]} for d in expected if d in merged]
    outputs = write_outputs(rows, args.start_date, args.end_date, Path(args.output_dir).expanduser(), args.prefix, canonical)
    print(json.dumps({"status": "ok", "row_count": len(rows), "outputs": outputs}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
