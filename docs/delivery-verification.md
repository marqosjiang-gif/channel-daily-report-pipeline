# 交付核验机制（verified_sent_visible）

日报属于「静默失败高发」场景：SMTP 网关返回 accepted，不代表邮件真的送达或在网页端可见。本项目的唯一成功标准是 `verified_sent_visible`，由 `skills/dashboard-builder/scripts/send_daily_email.py` 严格执行。

## 状态机

| 状态 | 含义 | 后续动作 |
|---|---|---|
| `prepared` | 邮件已构建（MIME + 内嵌 PNG） | — |
| `smtp_accepted` | SMTP 网关已接收 | 继续 IMAP 校验 |
| `verified_sent_visible` | SMTP accepted + 同一封 MIME 已追加到 IMAP 已发送箱 + 重开邮箱按主题/收件人反查命中 | 唯一可报告「成功」的状态 |
| `partial_smtp_accepted_but_sent_folder_unverified` | SMTP 接收，但已发送箱追加或反查失败 | 报告「可能已发出但未核验」，不得计为成功 |
| `failed` | SMTP 发送即失败 | 告警 + 审计记录 |

## 核验流程

1. 发送前先写一条 run-start 审计行到 `output/audit/automation_run_audit.jsonl`（无 run-start 行的运行视为自动化平台空跑，不算完成）。
2. SMTP SSL 发送。
3. 将同一封 MIME 原文 `APPEND` 到 IMAP 已发送箱（如 `Sent Messages`），从 `APPENDUID` 拿到 UID。
4. 重新 `SELECT` 已发送箱（只读），按 UID `FETCH` 头部；失败则回退到最近 30 封逐封比对。
5. 比对规则：主题完全相等 + 收件人包含匹配。
6. 全部通过才写 `status=verified_sent_visible` 终态审计行。

## 为什么不用「SMTP 返回成功」当标准

企业邮箱（如腾讯企业邮）存在「SMTP accepted 但网页端已发送箱不显示」的真实案例。日报的验收人是收邮件的人，不是 SMTP 网关。以 `verified_sent_visible` 为唯一成功口径，可以把「发了没」从玄学变成可断言的事实，并通过 `check_daily_delivery.py --run-date YYYY-MM-DD`（退出码 0/2）随时复核任意一天的交付状态。

日志只记录收发件人、主题、状态、UID 等，绝不记录密码/令牌（写入前按字段名过滤）。
