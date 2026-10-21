#!/usr/bin/env python3
"""Send the daily dashboard PNG email with strict sent-folder verification."""

from __future__ import annotations

import argparse
import email
import imaplib
import json
import os
import re
import smtplib
import ssl
import sys
import time
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import EmailMessage
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def log_event(path: Path | None, event: dict) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: v for k, v in event.items() if "password" not in k.lower() and "token" not in k.lower()}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now_iso(), **clean}, ensure_ascii=False) + "\n")


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    # 支持 "$ENV_VAR" 形式的占位符，运行时从环境变量注入，凭据不落盘
    for key, value in list(cfg.items()):
        if isinstance(value, str) and value.startswith("$"):
            cfg[key] = os.environ.get(value[1:], "")
    required = ["smtp_server", "smtp_port", "smtp_user", "smtp_password"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        raise ValueError(f"SMTP配置缺少字段: {', '.join(missing)}（真实值请通过环境变量或本地 config/smtp_config.json 注入）")
    cfg.setdefault("sender_email", cfg["smtp_user"])
    cfg.setdefault("imap_server", "imap.exmail.qq.com")
    cfg.setdefault("imap_port", 993)
    cfg.setdefault("imap_user", cfg["smtp_user"])
    cfg.setdefault("imap_password", cfg["smtp_password"])
    return cfg


def build_message(cfg: dict, recipient: str, subject: str, body: str, png_path: Path) -> EmailMessage:
    if not png_path.exists():
        raise FileNotFoundError(f"PNG不存在: {png_path}")

    msg = EmailMessage()
    msg["From"] = cfg["sender_email"]
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=cfg["sender_email"].split("@")[-1])
    msg.set_content(f"{body}\n\n[图片看板]", subtype="plain", charset="utf-8")
    msg.add_alternative(
        f"""\
<html><body>
  <p>{body}</p>
  <p><img src="cid:channel-dashboard-png" style="max-width:100%;height:auto;display:block;" /></p>
</body></html>
""",
        subtype="html",
        charset="utf-8",
    )
    html_part = msg.get_payload()[1]
    html_part.add_related(
        png_path.read_bytes(),
        maintype="image",
        subtype="png",
        cid="<channel-dashboard-png>",
        filename=png_path.name,
        disposition="inline",
    )
    return msg


def smtp_send(cfg: dict, msg: EmailMessage) -> None:
    with smtplib.SMTP_SSL(cfg["smtp_server"], int(cfg["smtp_port"]), timeout=60) as smtp:
        smtp.login(cfg["smtp_user"], cfg["smtp_password"])
        smtp.send_message(msg)


def parse_append_uid(response: list[bytes] | tuple | None) -> str | None:
    text = " ".join(
        item.decode("utf-8", "ignore") if isinstance(item, bytes) else str(item)
        for item in (response or [])
    )
    m = re.search(r"APPENDUID\s+\d+\s+(\d+)", text)
    return m.group(1) if m else None


def decode_mime(value: str | None) -> str:
    if not value:
        return ""
    return str(make_header(decode_header(value)))


def headers_match(raw: bytes, subject: str, recipient: str) -> bool:
    msg = email.message_from_bytes(raw)
    got_subject = decode_mime(msg.get("Subject"))
    got_to = decode_mime(msg.get("To")).lower()
    return got_subject == subject and recipient.lower() in got_to


def imap_connect(cfg: dict) -> imaplib.IMAP4_SSL:
    context = ssl._create_unverified_context()
    imap = imaplib.IMAP4_SSL(cfg["imap_server"], int(cfg["imap_port"]), ssl_context=context)
    imap.login(cfg["imap_user"], cfg["imap_password"])
    return imap


def imap_append_and_verify(cfg: dict, mailbox: str, msg: EmailMessage, subject: str, recipient: str) -> dict:
    raw = msg.as_bytes()
    with imap_connect(cfg) as imap:
        typ, data = imap.append(mailbox, None, imaplib.Time2Internaldate(time.time()), raw)
        if typ != "OK":
            raise RuntimeError(f"已发送箱写入失败: {typ} {data}")
        uid = parse_append_uid(data)

        typ, _ = imap.select(mailbox, readonly=True)
        if typ != "OK":
            raise RuntimeError(f"无法打开已发送箱校验: {mailbox}")

        if uid:
            typ, fetched = imap.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT TO DATE FROM MESSAGE-ID)])")
            if typ == "OK":
                for item in fetched:
                    if isinstance(item, tuple) and headers_match(item[1], subject, recipient):
                        return {"mailbox": mailbox, "uid": uid, "verified": True}

        typ, data = imap.search(None, "ALL")
        if typ != "OK" or not data or not data[0]:
            raise RuntimeError("已发送箱为空，无法反查邮件")
        ids = data[0].split()[-30:]
        for msg_id in reversed(ids):
            typ, fetched = imap.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (SUBJECT TO DATE FROM MESSAGE-ID)])")
            if typ != "OK":
                continue
            for item in fetched:
                if isinstance(item, tuple) and headers_match(item[1], subject, recipient):
                    return {"mailbox": mailbox, "message_id": msg_id.decode(), "verified": True}

    raise RuntimeError("SMTP已接收，但未能在已发送箱反查到同主题/同收件人的邮件")


def main() -> int:
    parser = argparse.ArgumentParser(description="Send and verify the daily dashboard email.")
    parser.add_argument("--smtp-config", required=True)
    parser.add_argument("--png", required=True)
    parser.add_argument("--recipient", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--log", default="")
    parser.add_argument("--sent-mailbox", default='"Sent Messages"')
    args = parser.parse_args()

    log_path = Path(args.log).expanduser() if args.log else None
    result = {
        "recipient": args.recipient,
        "subject": args.subject,
        "png": str(Path(args.png).expanduser()),
        "status": "prepared",
    }
    try:
        cfg = load_config(Path(args.smtp_config).expanduser())
        msg = build_message(cfg, args.recipient, args.subject, args.body, Path(args.png).expanduser())
        log_event(log_path, {**result, "status": "prepared", "sender": cfg["sender_email"]})

        smtp_send(cfg, msg)
        result["status"] = "smtp_accepted"
        log_event(log_path, {**result, "sender": cfg["sender_email"]})

        verified = imap_append_and_verify(cfg, args.sent_mailbox, msg, args.subject, args.recipient)
        result.update(verified)
        result["status"] = "verified_sent_visible"
        log_event(log_path, {**result, "sender": cfg["sender_email"]})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        if result["status"] == "smtp_accepted":
            result["status"] = "partial_smtp_accepted_but_sent_folder_unverified"
        else:
            result["status"] = "failed"
        result["error"] = str(exc)
        log_event(log_path, result)
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
