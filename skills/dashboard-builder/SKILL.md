---
name: dashboard-builder
description: 生成并校验渠道经营数据看板。
---

# 渠道经营数据看板

## Core Rule

Use the backend-exported report Excel as the authoritative source for经营指标, and validate every dashboard total against the final `总计：` row before rendering.

Do not generate or email a PNG if validation fails.

## Required Inputs

- Backend export Excel: 每日渠道出单数据（如 `daily_channel_orders_20260101_YYYYMMDD.xlsx`）.
- Daily store-count JSON/CSV from `store-count-collector`; required for the daily `售卖门店数` trend.
- Output directory for generated HTML/PNG.

If the user provides a new backend Excel, prefer it over archived Excel files for the same date range.

## Standard Workflow

1. Read `references/data-contract.md` when changing metrics, chart layout, or validation behavior.
2. Run:

```bash
python3 skills/dashboard-builder/scripts/build_dashboard.py \
  --excel /path/to/daily_channel_orders.xlsx \
  --store-counts /path/to/store_counts_daily.json \
  --output-dir output/dashboard \
  --prefix channel_dashboard
```

3. Check the script output. It must report `diff` values of zero for required totals.
4. Open or inspect the PNG if layout changes were made.
5. Use the generated PNG for email-body embedding. Do not recreate a simplified KPI-only image.

## Fast Daily Workflow

For scheduled daily runs, avoid rebuilding the workflow step-by-step in the agent. The browser should only collect the previous day's report page text; all parsing, cache merge, Excel append, dashboard rendering, validation, and optional email sending should be delegated to one script.

Browser steps:

1. Use the in-app Browser session only.
2. Open the channel backend report center and enter the daily channel orders report.
3. Set `开始时间 = 结束时间 = run_date - 1 day`.
4. Click `查询`.
5. Read `document.body.innerText` after the table contains `总计：`.
6. Save that text to `data/report_text/channel_report_text_YYYYMMDD.txt`.

Then run:

```bash
python3 skills/dashboard-builder/scripts/fast_daily_from_report_text.py \
  --date YYYY-MM-DD \
  --report-text data/report_text/channel_report_text_YYYYMMDD.txt \
  --send-email \
  --notify-on-failure
```

This script is the preferred daily path. It validates the single-day `总计：` row, merges the daily store-count cache, creates the cumulative Excel, renders the mobile PNG, validates dashboard totals, and calls the strict email sender. A normal run should spend only a few seconds after report text is captured.

Do not export Excel during normal daily runs. Use Excel export only if the page table never renders text after `查询`, and record that fallback in the audit log.

## Browser Source Rule

For scheduled backend data collection, use only the agent's in-app Browser plugin/session. Do not use the Chrome plugin, the user's Google Chrome app, Chrome tabs, Chrome cookies, or Chrome extensions to log in, query, export, or read backend report data.

If the in-app browser is not logged in or the session expires, stop and ask the user to log in there. Do not fall back to Chrome.

## Email Sending Contract

Never report `发送成功` from SMTP success alone. Some SMTP providers may accept an SMTP message without showing it in the web `已发送` folder automatically.

Before any scheduled run starts business work, write a run-start audit line to:

- `output/audit/automation_run_audit.jsonl`

At the end, write one final audit line with `status=verified_sent_visible`, `failed`, or `blocked`. A scheduled run that does not create a run-start line should be treated as an automation platform empty run, not as a completed report.

Use the strict sender script for daily emails:

```bash
python3 skills/dashboard-builder/scripts/send_daily_email.py \
  --smtp-config config/smtp_config.json \
  --png /path/to/看板.png \
  --recipient "$RECIPIENT_EMAIL" \
  --subject "渠道日报｜截止YYYY-MM-DD" \
  --body "您好，截止昨日渠道经营数据看板已更新，如下：" \
  --log output/logs/email_delivery_log.jsonl
```

The only final success status is `verified_sent_visible`, meaning:

1. SMTP accepted the message.
2. The same MIME message was appended to the IMAP `Sent Messages` mailbox.
3. The mailbox was reopened and the message was found by matching recipient and subject.

If SMTP succeeds but the sent-folder append or verification fails, report `partial_smtp_accepted_but_sent_folder_unverified`, not `发送成功`. Tell the user the email may have been accepted by SMTP but is not verified in `已发送`.

Do not print or expose SMTP/IMAP passwords. Logs may include sender, recipient, subject, PNG path, mailbox, UID/message ID, status, and error text, but never secrets.

To check whether the daily task actually completed for a run date, use:

```bash
python3 skills/dashboard-builder/scripts/check_daily_delivery.py \
  --log output/logs/email_delivery_log.jsonl \
  --run-date YYYY-MM-DD
```

Exit code `0` means the expected cutoff email has `verified_sent_visible`. Exit code `2` means the day is not verified and must be reported or retried.

## Mobile PNG Layout Rules

- Canvas width: `390px` CSS width.
- Height: expand to fit all content; mobile scrolling is acceptable.
- Include KPI cards:
  - 统计周期
  - 总订单数
  - 总间夜数
  - 总销售金额
  - 总留存金额
  - 整体销售ADR
  - 期末售卖门店数
- Include two chart cards:
  - `供给与成交趋势`: `订单数`, `间夜数`, `售卖门店数`.
  - `收入与价格质量`: `销售金额`, `销售ADR`.
- Keep axes separated by unit. Never mix `售卖门店数`, `订单数/间夜数`, `销售金额`, and `销售ADR` on mismatched axes.
- For long daily ranges, label only month starts and the final date on the X axis. If the final date is near a month-start label, hide that nearby month-start label.
- Do not show the subtitle `以日期为轴呈现...`.
- Do not show the bottom `高峰销售日...` note in the mobile email PNG.

## Output Contract

The script writes:

- `output/dashboard/channel_dashboard_mobile_<start>_<end>.html`
- `output/dashboard/channel_dashboard_mobile_<start>_<end>.png`
- `output/dashboard/channel_dashboard_metrics_<start>_<end>.json`

The JSON contains `meta.backend_total`, `meta.computed`, and `meta.diff`. Treat this as the audit trail for the rendered dashboard.
