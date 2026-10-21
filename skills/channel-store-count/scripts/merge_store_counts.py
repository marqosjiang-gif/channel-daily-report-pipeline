#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path


DATE_KEYS = ("date", "日期")
STORE_KEYS = ("store_count", "售卖门店数")


def pick(row: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        if name in row:
            return row[name]
    raise KeyError(f"Missing required column; expected one of: {', '.join(names)}")


def read_store_counts(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"{path} has no header")
        result: dict[str, str] = {}
        for row in reader:
            date = pick(row, DATE_KEYS).strip()
            value = pick(row, STORE_KEYS).strip().replace(",", "")
            if not date:
                continue
            if not value.isdigit():
                raise ValueError(f"Invalid store_count for {date}: {value!r}")
            result[date] = value
        return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge backend daily total store counts into a daily metrics CSV."
    )
    parser.add_argument("daily_csv", type=Path, help="Daily metrics CSV to update.")
    parser.add_argument("store_counts_csv", type=Path, help="CSV with date,store_count.")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output CSV path.")
    parser.add_argument(
        "--store-column",
        default="售卖门店数",
        help="Column in daily_csv to overwrite or create. Default: 售卖门店数",
    )
    args = parser.parse_args()

    counts = read_store_counts(args.store_counts_csv)

    with args.daily_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"{args.daily_csv} has no header")
        rows = list(reader)
        fields = list(reader.fieldnames)

    date_field = next((name for name in DATE_KEYS if name in fields), None)
    if not date_field:
        raise KeyError(f"daily_csv must contain one of: {', '.join(DATE_KEYS)}")

    if args.store_column not in fields:
        fields.append(args.store_column)

    missing: list[str] = []
    for row in rows:
        date = row.get(date_field, "").strip()
        if not date:
            continue
        if date not in counts:
            missing.append(date)
            continue
        row[args.store_column] = counts[date]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    if missing:
        print("Missing store counts for dates:")
        for date in missing:
            print(date)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
