#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仅用于验证"能否成功发邮件"的测试脚本。

- 不写死任何账号密码，从环境变量读取（与 monitor.py 一致）
- 发送一封 HTML 测试邮件；若同目录存在 page.png 则作为内嵌截图附上，
  用于确认"带截图的监控邮件"也能正常送达
- 运行前请设置：EMAIL_USER、EMAIL_PASS、EMAIL_TO（可选 SMTP_HOST、SMTP_PORT）
"""

import os
import smtplib
import ssl
import sys
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ENV_EMAIL_USER = "EMAIL_USER"
ENV_EMAIL_PASS = "EMAIL_PASS"
ENV_EMAIL_TO = "EMAIL_TO"
SMTP_TIMEOUT = 30

SCREENSHOT_FILE = Path(__file__).resolve().parent / "page.png"


def build_test_message(user: str, to_addr: str) -> MIMEMultipart:
    subject = "【网页监控·发信测试】带内嵌截图"
    plain_body = (
        "这是一封测试邮件。\n\n"
        "如果你收到并看到下方截图，说明 EMAIL_USER / EMAIL_PASS / EMAIL_TO 配置正确，"
        "monitor.py 在检测到网页变化时也能正常发出含截图的通知邮件。\n\n"
        "本邮件由 test_email.py 发送，仅用于验证发信功能。"
    )

    has_image = SCREENSHOT_FILE.exists()
    img_html = (
        '<div style="margin-top:16px;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">'
        '<img src="cid:page_screenshot" alt="页面截图" '
        'style="display:block;width:100%;max-width:640px;height:auto;" />'
        '</div>'
    ) if has_image else (
        '<p style="color:#9ca3af;font-size:12px;">未检测到 page.png，未附截图。'
        '可先运行一次 <code>python monitor.py</code> 生成截图后再次测试。</p>'
    )

    html_body = f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:16px;background:#f5f7fb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,'PingFang SC','Microsoft YaHei',sans-serif;color:#222;">
    <div style="max-width:680px;margin:0 auto;background:#fff;border-radius:12px;padding:20px 24px;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
      <h2 style="color:#1a56db;margin:0 0 12px;font-size:18px;">网页监控发信测试</h2>
      <p style="color:#222;line-height:1.6;font-size:14px;margin:0 0 12px;">
        如果你收到此邮件，说明 SMTP 配置正确。<br/>
        若同时看到下方页面截图，则"带截图的变化通知邮件"也能正常送达。
      </p>
      {img_html}
    </div>
  </body>
</html>
"""

    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(plain_body, "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    if has_image:
        img_bytes = SCREENSHOT_FILE.read_bytes()
        img = MIMEImage(img_bytes, _subtype="png")
        img.add_header("Content-ID", "<page_screenshot>")
        img.add_header("Content-Disposition", "inline", filename="page.png")
        msg.attach(img)
    return msg


def main() -> None:
    user = os.environ.get(ENV_EMAIL_USER)
    password = os.environ.get(ENV_EMAIL_PASS)
    to_addr = os.environ.get(ENV_EMAIL_TO)
    smtp_host = os.environ.get("SMTP_HOST", "smtp.qq.com")
    try:
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    except ValueError:
        smtp_port = 587

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

    msg = build_test_message(user, to_addr)

    try:
        context = ssl.create_default_context()
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=SMTP_TIMEOUT) as server:
                server.login(user, password)
                server.sendmail(user, [to_addr], msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=SMTP_TIMEOUT) as server:
                server.starttls(context=context)
                server.login(user, password)
                server.sendmail(user, [to_addr], msg.as_string())
        if SCREENSHOT_FILE.exists():
            print("测试邮件（含内嵌截图）已发送。请到收件箱（及垃圾箱）查看。")
        else:
            print("测试邮件已发送（未附截图，因为未找到 page.png）。")
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
