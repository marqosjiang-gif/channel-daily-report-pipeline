# 渠道后台取数流程参考

## Observed Pages

- Login page: `$CHANNEL_REPORT_URL/login`
- Report center: `$CHANNEL_REPORT_URL/main`（渠道后台报表中心，见 `.env.example`）
- Menu path: `报表中心` -> `所有报表`
- Report names observed: 每日渠道订单/出单数据报表（不同后台命名略有差异，以表头字段为准）

## Report Controls

The report page contains:

- `OTA渠道`
- `开始时间`
- `结束时间`
- `查询`

The report may be embedded inside a cross-origin iframe. If the iframe blocks DOM access, open its `src` URL as a top-level tab and continue there.

## Table Target

Headers observed:

```text
日期, 渠道, 售卖门店数, 有产门店数, 有产率, 出单率, 取消率, 订单数, 间夜数, 销售金额, 结算金额, 留存金额, 销售ADR
```

Target value:

```text
最后一行“总计：” under “售卖门店数”
```

## Robust Reading Pattern

Prefer DOM table rows when available:

1. Collect all `tr` rows.
2. Find the header row containing `售卖门店数`.
3. Store that column index.
4. Find the last row containing `总计`.
5. Read the cell at the stored column index.

If the `总计` row is not found, scroll the report container or page downward once and retry. If it is still missing, fail with a screenshot; do not infer the number from channel rows.

## Date Control Notes

FineReport-style date controls may resist normal text fill. Stable approaches observed:

- Click the date control and select the day from the date popup when querying dates in the visible month.
- If text input is active, fill can fail because the widget wraps its input. Use visible calendar cells or a tested page-specific method.
- Always verify the visible `开始时间` and `结束时间` text changed before clicking `查询`.

## Output Cache

Save each successful row immediately in memory and to disk. If a date fails, keep completed dates and report the failing date plus exact problem.
