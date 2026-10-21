---
name: store-count-collector
description: 渠道每日售卖门店数统计与汇总。
---

# 渠道日售卖门店数取数

## Core Rule

Never calculate `售卖门店数` from channel detail rows. Do not use max, sum, average, or any inferred value.

The target value is always:

```text
后台报表最后一行“总计：” × “售卖门店数”列
```

For a date range, query one day at a time. Example: `2026-05-01 至 2026-05-31` means 31 independent queries:

```text
开始时间=2026-05-01, 结束时间=2026-05-01
...
开始时间=2026-05-31, 结束时间=2026-05-31
```

## Required Date Confirmation

Before any backend query, show an interactive confirmation UI for the date range.

Use:

```bash
python3 skills/store-count-collector/scripts/confirm_dates.py \
  --start-date YYYY-MM-DD \
  --end-date YYYY-MM-DD \
  --output /tmp/store_count_dates.json
```

Continue only after the script returns `confirmed: true`. If the user cancels, stop without querying the backend.

If the local UI cannot be opened, ask for explicit confirmation in chat and record the confirmed `start_date` and `end_date` before proceeding.

## Browser Workflow

Use the agent's in-app Browser plugin and the user's active in-app-browser login session. Do not use the Chrome plugin, the user's Google Chrome app, Chrome tabs, Chrome cookies, or Chrome extensions for backend report querying. Do not save credentials.

Before querying, verify the in-app browser is logged in with the account explicitly specified by the user for this task. If the user provides credentials in the current conversation, use them only for the current login attempt and never write the password into skill files, logs, cache, screenshots, or generated reports. If the in-app browser is logged in as a different account, log out or return to the login page and sign in with the user-specified account before continuing.

1. Open or reuse `$CHANNEL_REPORT_URL`（渠道后台报表中心，见 `.env.example`）.
2. If the page is not logged in or login expires, stop and alert: `当前未登录/登录失效，请先登录渠道后台后重试`.
3. Open the report center path `报表中心` -> `所有报表`, then open the daily channel orders report.
4. If the report is embedded in a cross-origin iframe, open the report iframe `src` as a top-level browser page so DOM/table text can be read.
5. For every confirmed date:
   - Set both `开始时间` and `结束时间` to that date.
   - Click `查询`.
   - Wait until the table refreshes to that date.
   - Locate the header `售卖门店数`.
   - Locate the final row labeled `总计：`.
   - Read the intersection value.
   - Save progress immediately after each successful date.

## Incremental Daily Workflow

For scheduled daily email runs, use an incremental cache before browser querying. Do not re-query the full range from the season start (`2026-01-01`) every day.

Default canonical cache:

```text
data/store_counts/store_counts_cumulative_cache.json
```

Daily scheduled run:

1. Compute `target_end_date = run_date - 1 day`.
2. Load the canonical cache if it exists.
3. Determine missing dates from `2026-01-01` through `target_end_date`.
4. Query only missing dates in the browser. In normal daily operation this should be just yesterday.
5. After each successful date, merge the new row into the canonical cache immediately.
6. Generate dated outputs from the merged cache, such as:
   - `data/store_counts/store_counts_daily_20260101_YYYYMMDD.json`
   - `data/store_counts/store_counts_daily_20260101_YYYYMMDD.csv`
   - `data/store_counts/store_counts_daily_20260101_YYYYMMDD.md`

If the cache has gaps before `target_end_date`, query only those missing dates, not the entire historical range. If a required missing date cannot be read, stop and report the exact date; never silently carry forward an old value.

Use `scripts/merge_store_count_cache.py` to merge existing cache files and newly queried rows, validate date continuity, and write JSON/CSV/Markdown outputs.

Read `references/browser-flow.md` only when selectors, report navigation, or error handling need more detail.

## Error Handling

Use active browser reporting for user-actionable failures. Prefer `window.alert(<specific message>)` and save a screenshot in the local output folder when structure or table detection fails.

- Login missing: alert `当前未登录/登录失效，请先登录渠道后台后重试`.
- Menu/date input/query button not found: alert the exact missing element, such as `未找到开始时间输入框`.
- Report table not found: screenshot and alert `未找到报表表格，页面结构可能已变化`.
- `总计：` row not found: scroll the report/page downward once, retry, then screenshot and alert `未找到总计行，无法猜数`.
- `售卖门店数` column not found: screenshot and alert `找到报表但未找到售卖门店数列`.
- Intersection cell unreadable: screenshot and alert `找到总计行，但未找到售卖门店数列或交叉单元格`.
- Never guess missing values.

## Output

Default Markdown output:

```text
data/store_counts/store_counts_daily.md
```

Preferred table:

```markdown
| 日期 | 售卖门店数 |
|---|---:|
| 2026-05-01 | 1604 |
```

Use `scripts/write_store_counts_md.py` to write or rewrite the final Markdown from a JSON or CSV cache.

## Dashboard Data Contract

When this skill is used as part of the daily email workflow, the email body PNG must be generated from the same dashboard data contract as the HTML dashboard (see `skills/dashboard-builder/references/data-contract.md`). Do not use a simplified KPI-only snapshot when the source HTML contains charts or supporting notes.

If the user provides a backend-exported report Excel for the same date range, treat that Excel as the authoritative source for all经营指标 except daily `售卖门店数`. Do not mix an older archived Excel with newly queried partial backend data unless the user explicitly approves that fallback.

Before rendering any PNG/HTML dashboard:

1. Detect the header row containing `日期`, `渠道`, and `售卖门店数`; exported files may contain blank rows before the header.
2. Split detail rows from the final `总计：` row.
3. Aggregate detail rows by `日期` for `订单数`, `间夜数`, `销售金额`, `结算金额`, and `留存金额`; compute daily `销售ADR = 销售金额 / 间夜数`.
4. Compare the aggregated totals to the backend final `总计：` row for `订单数`, `间夜数`, `销售金额`, `结算金额`, `留存金额`, and overall `销售ADR`.
5. Validate the final day `售卖门店数` against the backend final `总计：` row when daily store-count cache is used for the store trend.
6. If any required total differs, stop and report the mismatch; do not render or email the PNG.

Mobile email rendering rules:

- Use a mobile-width canvas, default `390px` CSS width.
- Let the PNG height expand to fit all chart content; scrolling on mobile is acceptable.
- Prioritize complete chart/data visibility over fitting into one screen.
- Keep Y-axis units separated exactly as the HTML dashboard does; never place `售卖门店数`, `订单数/间夜数`, `销售金额`, and `销售ADR` on mismatched axes.
- For long daily time ranges on mobile, label only month starts plus the final date on the X axis.
- Render the PNG from the generated mobile HTML and crop to the actual content height so the email image has no large blank tail.
