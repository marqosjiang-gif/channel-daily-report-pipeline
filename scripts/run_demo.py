#!/usr/bin/env python3
"""One-command end-to-end demo.

Steps:
1. Copy mock fixtures from data/mock/ into the runtime directories
   (data/excel, data/report_text, data/store_counts).
2. Run the fast daily pipeline on the mock cutoff day (2026-06-05):
   parse report text -> validate totals -> merge store-count cache ->
   append cumulative Excel -> render dashboard (HTML + PNG when possible).
3. Assert every validation diff is 0 and print a summary.

No real credentials, backend, or network access are required.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MOCK = REPO_ROOT / "data/mock"
TARGET_DATE = "2026-06-05"


def copy_fixtures() -> None:
    pairs = [
        (MOCK / "excel/daily_channel_orders_20260101_20260604.xlsx", REPO_ROOT / "data/excel/daily_channel_orders_20260101_20260604.xlsx"),
        (MOCK / "report_text/channel_report_text_20260605.txt", REPO_ROOT / "data/report_text/channel_report_text_20260605.txt"),
        (MOCK / "store_counts/store_counts_cumulative_cache.json", REPO_ROOT / "data/store_counts/store_counts_cumulative_cache.json"),
    ]
    for src, dst in pairs:
        if not src.exists():
            raise FileNotFoundError(f"缺少 mock 数据: {src}（先运行 scripts/generate_mock_data.py）")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def run_pipeline(skip_png: bool) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "skills/dashboard-builder/scripts/fast_daily_from_report_text.py"),
        "--date",
        TARGET_DATE,
        "--report-text",
        str(REPO_ROOT / "data/report_text/channel_report_text_20260605.txt"),
    ]
    if skip_png:
        cmd.append("--skip-png")
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)


def main() -> int:
    copy_fixtures()

    proc = run_pipeline(skip_png=False)
    if proc.returncode != 0:
        # PNG 渲染需要 node + playwright；不可用时降级为仅 HTML，不影响校验逻辑演示
        print("[note] PNG 渲染不可用（缺 node/playwright），降级为仅生成 HTML 看板。\n")
        proc = run_pipeline(skip_png=True)
    print(proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        print("DEMO FAILED", file=sys.stderr)
        return proc.returncode

    # fast pipeline 的 stdout 可能包含子脚本输出，取最后一个完整 JSON 对象
    stdout = proc.stdout
    idx = stdout.rfind("\n{")
    result = json.loads(stdout[idx:].strip() if idx >= 0 else stdout)
    diff = result.get("dashboard", {}).get("diff", {})
    bad = {k: v for k, v in diff.items() if abs(float(v)) > 0.01}
    if bad:
        print(f"校验失败，diff 非零: {bad}", file=sys.stderr)
        return 2

    print("=" * 60)
    print("DEMO OK")
    print(f"  目标日期: {TARGET_DATE}")
    print(f"  当日总计: {json.dumps(result.get('day_total', {}), ensure_ascii=False)}")
    print(f"  看板 HTML: {result.get('dashboard', {}).get('html')}")
    print(f"  看板 PNG: {result.get('dashboard', {}).get('png')}")
    print(f"  校验 diff: {json.dumps(diff, ensure_ascii=False)}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
