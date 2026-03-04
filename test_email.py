#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仅用于验证“能否成功发邮件”的测试脚本。

- 不写死任何账号密码，从环境变量读取（与 monitor.py 一致）
- 发送一封固定内容的测试邮件，确认 SMTP 与收件正常
- 运行前请设置：EMAIL_USER、EMAIL_PASS、EMAIL_TO（可选 SMTP_HOST、SMTP_PORT）
"""

import os
import smtplib
import ssl
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# 与 monitor.py 保持一致
ENV_EMAIL_USER = "EMAIL_USER"
ENV_EMAIL_PASS = "EMAIL_PASS"
ENV_EMAIL_TO = "EMAIL_TO"
SMTP_TIMEOUT = 30


def main() -> None:
    user = os.environ.get(ENV_EMAIL_USER)
    password = os.environ.get(ENV_EMAIL_PASS)
    to_addr = os.environ.get(ENV_EMAIL_TO)
    smtp_host = os.environ.get("SMTP_HOST", "smtp.qq.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    if not user or not password or not to_addr:
        print("请先设置环境变量后再运行本脚本：", file=sys.stderr)
        print("  EMAIL_USER  发件邮箱（如 your@qq.com）", file=sys.stderr)
        print("  EMAIL_PASS  邮箱授权码/密码（QQ 邮箱需在设置里开启 SMTP 并获取授权码）", file=sys.stderr)
        print("  EMAIL_TO    收件邮箱（可填自己，用于收测试信）", file=sys.stderr)
        print("", file=sys.stderr)
        print("示例（PowerShell，请替换为真实值）：", file=sys.stderr)
        print('  $env:EMAIL_USER = "your@qq.com"', file=sys.stderr)
        print('  $env:EMAIL_PASS = "你的授权码"', file=sys.stderr)
        print('  $env:EMAIL_TO   = "your@qq.com"', file=sys.stderr)
        print("  python test_email.py", file=sys.stderr)
        sys.exit(1)

    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    subject = "【2026国考】发信测试"
    body = (
        "这是一封测试邮件。\n\n"
        "如果你收到此邮件，说明 EMAIL_USER / EMAIL_PASS / EMAIL_TO 配置正确，"
        "monitor.py 在发现新增公告时也能正常发信。\n\n"
        "本邮件由 test_email.py 发送，仅用于验证发信功能。"
    )
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port, timeout=SMTP_TIMEOUT) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.sendmail(user, [to_addr], msg.as_string())
        print("测试邮件已发送。请到收件箱（及垃圾箱）查看。")
    except smtplib.SMTPAuthenticationError as e:
        print(f"SMTP 认证失败，请检查 EMAIL_USER / EMAIL_PASS：{e}", file=sys.stderr)
        print("QQ 邮箱：设置 → 账户 → POP3/IMAP/SMTP → 开启 SMTP，使用「授权码」而非登录密码。", file=sys.stderr)
        print("163 邮箱：设置 → POP3/SMTP/IMAP → 开启 SMTP，使用「授权密码」。", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"发送失败：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
