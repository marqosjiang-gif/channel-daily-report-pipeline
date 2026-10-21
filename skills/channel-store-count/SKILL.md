---
name: channel-store-count
description: 渠道后台每日总售卖门店数统计与汇总。
---

# 渠道后台每日总计售卖门店数取数

## Core Rule

Never calculate “售卖门店数” from channel rows. Do not use daily maximum, sum, average, or any inferred value. The target value is always the last row labeled `总计：` and the column labeled `售卖门店数` in the backend report.

For a date range, query one day at a time: set `开始时间 = YYYY-MM-DD` and `结束时间 = YYYY-MM-DD` for the same date, click `查询`, then read that date's total.

## Browser Workflow

Use the agent's in-app Browser plugin for channel-backend work. Reuse the user's active in-app-browser login session; do not use the Chrome plugin, the user's Google Chrome app, Chrome tabs, Chrome cookies, or Chrome extensions for backend report querying. Do not request, store, or type credentials unless the user is actively handling login.

1. Ask the user to confirm `start_date` and `end_date` before running a batch.
2. Open `$CHANNEL_REPORT_URL`（渠道后台报表中心，见 `.env.example`）.
3. If the page is not logged in or login expires, stop and show a browser `alert()` with: `当前未登录/登录失效，请先登录渠道后台后重试`.
4. Navigate through `报表中心` -> `所有报表`, then open the daily channel report page.
5. For each date in the confirmed range:
   - Set both date inputs to that same date.
   - Click `查询`.
   - Wait for the report table to refresh.
   - Locate the `售卖门店数` column by the table header text.
   - Locate the last row whose first cell contains `总计`.
   - Read the intersection value and append `date,store_count` to the output CSV.
   - Flush the CSV after every successful date so partial progress is preserved.

## Required Error Handling

Use active browser reporting for user-actionable failures. Prefer `window.alert(<specific message>)` on the page, plus a screenshot saved to the task output folder when structure or table detection fails.

- Login missing: alert `当前未登录/登录失效，请先登录渠道后台后重试`.
- Menu or input not found: alert the exact missing element, for example `未找到开始时间输入框` or `未找到查询按钮`.
- Report table not found: screenshot and alert `未找到报表表格，页面结构可能已变化`.
- `总计` row not found:
  1. Scroll the report area and page downward.
  2. Retry locating `总计`.
  3. If still missing, screenshot and alert `未找到总计行，无法猜数`.
- `售卖门店数` column not found: screenshot and alert `找到报表但未找到售卖门店数列`.
- Intersection cell not readable: screenshot and alert `找到总计行，但未找到售卖门店数列或交叉单元格`.
- Never guess a missing value. Record failed dates separately in the final response.

## Output

Default CSV path:

```text
data/store_counts/channel_daily_total_store_count.csv
```

CSV columns:

```csv
date,store_count
2025-01-01,639
```

If the user wants to update an existing dashboard or aggregate CSV, use `scripts/merge_store_counts.py` to merge the backend totals into a daily metrics file.

## Reference

Read `references/report-flow.md` when implementing or debugging the browser selectors and page flow.
