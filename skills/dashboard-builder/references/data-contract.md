# 渠道经营数据看板数据契约

## Authoritative Sources

- 经营指标: backend-exported daily channel orders Excel（如 `daily_channel_orders_20260101_YYYYMMDD.xlsx`）.
- Daily store trend: JSON/CSV produced by `store-count-collector`, where each date's `store_count` is the backend final `总计：` row's `售卖门店数`.

## Excel Parsing

The backend export may contain blank rows before the real header. Detect the header row by finding a row containing all of:

- `日期`
- `渠道`
- `售卖门店数`

Rows after the header are split into:

- detail rows: `日期 != 总计：`
- backend total row: final row where `日期 == 总计：`

## Daily Aggregation

Aggregate detail rows by date:

- `订单数`: sum
- `间夜数`: sum
- `销售金额`: sum
- `结算金额`: sum
- `留存金额`: sum
- `销售ADR`: `销售金额 / 间夜数`

Attach `售卖门店数` from the daily store-count file by date.

## Validation

Before rendering, compare aggregated values to the backend total row:

- `订单数`
- `间夜数`
- `销售金额`
- `结算金额`
- `留存金额`
- overall `销售ADR`
- final-day `售卖门店数`

All differences must be zero after normal rounding (`0.01` for money, exact integer for counts). Stop if any required check fails.

## Required Dashboard Elements

KPI cards:

- 统计周期
- 总订单数
- 总间夜数
- 总销售金额
- 总留存金额
- 整体销售ADR
- 期末售卖门店数

Charts:

- `供给与成交趋势`: line `订单数`, line `间夜数`, bar `售卖门店数`; count and store axes are separated.
- `收入与价格质量`: bar `销售金额`, line `销售ADR`; amount and ADR axes are separated.

Mobile X axis:

- Show sparse labels only.
- Prefer month starts and the final date.
- If the final date is within about 18 days of a month-start label, hide that nearby month-start label.
