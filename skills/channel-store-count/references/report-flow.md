# 渠道后台报表取数流程参考

## Observed page

- URL: `$CHANNEL_REPORT_URL/main`（渠道后台报表中心，见 `.env.example`）
- Left menu path: `报表中心` -> `所有报表`
- Filter controls:
  - `OTA渠道`
  - `开始时间`
  - `结束时间`
  - `查询`
- Table headers observed:
  - `日期`
  - `渠道`
  - `售卖门店数`
  - `有产门店数`
  - `有产率`
  - `出单率`
  - `取消率`
  - `订单数`
  - `间夜数`
  - `销售金额`
  - `结算金额`
  - `留存金额`
  - `销售ADR`

## Target value

Read the table row labeled `总计：`, not the channel rows. The value needed for dashboard store count is the `总计：` row under the `售卖门店数` column.

## Date range behavior

The backend task must query one day at a time. For `2026-05-01` to `2026-05-31`, run 31 independent queries:

```text
开始时间=2026-05-01, 结束时间=2026-05-01
开始时间=2026-05-02, 结束时间=2026-05-02
...
开始时间=2026-05-31, 结束时间=2026-05-31
```

## Robust table reading hints

- Prefer text-based location over pixel coordinates.
- Locate the `售卖门店数` column from the header row each time, because column positions may shift.
- Locate the `总计：` row after the query completes.
- If `总计：` is not visible, scroll the report iframe/container/page down and retry before failing.
- If the report is inside an iframe, select the frame containing the table before querying cells.
- If text extraction is unreliable, use DOM table rows first, then fallback to visible text plus screenshot diagnostics.
