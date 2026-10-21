# 渠道日报自动化执行规则

## Scope

这些规则适用于本仓库的渠道日报、后台取数、手机 PNG 看板和邮件发送自动化。

## 每次任务执行前自检

执行任何后台取数前，必须先完成并记录以下自检：

1. 自动化状态必须为 `ACTIVE`，任务为 `渠道日报邮件`。
2. 截止日期必须是运行当天的前一日。
3. 后台取数只允许使用 Agent 内置浏览器 / Browser 插件。
4. 严禁使用 `computer-use`、Chrome、用户桌面浏览器、浏览器扩展或外部 cookies 做渠道后台/FineReport 登录、查询、导出、读数。
5. 如果 Browser 插件不可用或内置浏览器未登录，立即停止并弹窗：`日报未完成：Browser 插件不可用/内置浏览器未登录`。
6. 先运行缺失日期规划，只补取累计缓存中缺失的日期，不重新跑 2026-01-01 至昨日的全量。
7. 缺失日期补取时，每天都必须设置 `开始时间 = 结束时间 = 当天`，读取该日 `总计：` 行，不得用渠道最大值替代。
8. 单日缓存只是加速缓存。后台可能回写历史日期；发送前必须用网页报表中 `2026-01-01 至 截止日` 的全周期 `总计：` 行校验缓存汇总。
9. 全周期校验不要求导出 Excel。必须在内置浏览器里设置开始/结束日期，点击 `查询`，点击 `末页`，下滚报表区域直到最终 `总计：` 行可读，然后读取该行。
10. 如果网页末页 `总计：` 行与缓存汇总不一致，不得发送缓存生成的 PNG。必须报告 `日报未完成：全周期总计与缓存看板不一致` 及差异字段；只有用户明确提供全周期导出或要求重建时，才使用导出/全量明细重建看板。
11. 全周期 `总计：` 行里的 `售卖门店数` 是周期售卖门店数，不等同于最后一天的单日售卖门店数；KPI 应展示周期口径，趋势图仍可展示每日口径。
12. 补缺日期只更新缓存和累计 Excel；只在最终截止日期渲染 PNG 并发送邮件。
13. 邮件成功标准只能是 `verified_sent_visible`，即 SMTP accepted、IMAP 追加到 Sent Messages、并按主题和收件人在已发送箱反查成功。
14. 任务结束达到 `verified_sent_visible` 后可调用本机通知脚本弹成功通知（`--notify-script`，未提供则跳过）。非 `verified_sent_visible` 状态不得弹成功通知。
15. 任务被阻断或失败时，必须弹失败通知，不能只写审计日志。

## 固定命令

补缺日期，只更新缓存和 Excel：

```bash
python3 skills/dashboard-builder/scripts/fast_daily_from_report_text.py \
  --date YYYY-MM-DD \
  --report-text data/report_text/channel_report_text_YYYYMMDD.txt \
  --notify-on-failure
```

最终截止日，生成 PNG 并发邮件（需先在环境变量中配置 `RECIPIENT_EMAIL` 与 SMTP 凭据，见 `.env.example`）：

```bash
python3 skills/dashboard-builder/scripts/fast_daily_from_report_text.py \
  --date YYYY-MM-DD \
  --report-text data/report_text/channel_report_text_YYYYMMDD.txt \
  --send-email \
  --notify-on-failure
```

发送校验：

```bash
python3 skills/dashboard-builder/scripts/check_daily_delivery.py \
  --log output/logs/email_delivery_log.jsonl \
  --run-date YYYY-MM-DD \
  --notify-on-failure
```
