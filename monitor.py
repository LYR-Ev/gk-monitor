#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国家公务员局 2026 国考公告监控脚本

- 访问官方公开专题页面，抓取公告标题
- 与本地 cache.json 对比，仅在有新增时发送邮件通知
- 单次运行，无无限循环，适配 GitHub Actions
"""

import json
import os
import smtplib
import ssl
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# 配置（均通过常量/环境变量，不写死敏感信息）
# ---------------------------------------------------------------------------

# 国家公务员局 2026 国考专题公开页面（仅访问此公开页）
TARGET_URL = "http://bm.scs.gov.cn/kl2026"

# 请求超时（秒）
REQUEST_TIMEOUT = 30

# 缓存文件路径（与脚本同目录）
CACHE_FILE = Path(__file__).resolve().parent / "cache.json"

# 环境变量：邮箱配置（必须由外部设置，禁止在代码中写死账号密码）
ENV_EMAIL_USER = "EMAIL_USER"
ENV_EMAIL_PASS = "EMAIL_PASS"
ENV_EMAIL_TO = "EMAIL_TO"

# 兼容 HTTP/HTTPS 的 User-Agent，表明用途且不伪装
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def load_cache() -> list[str]:
    """从本地 cache.json 读取已见过的公告标题列表。"""
    if not CACHE_FILE.exists():
        return []
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("titles", []) if isinstance(data, dict) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_cache(titles: list[str]) -> None:
    """将当前所有公告标题写入 cache.json。"""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"titles": titles}, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"保存缓存失败: {e}", file=sys.stderr)


def fetch_page(url: str) -> str:
    """
    请求公开页面 HTML。
    使用 User-Agent 与超时，不绕过任何登录/验证码/安全机制。
    """
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def parse_announcement_titles(html: str) -> list[str]:
    """
    从专题页 HTML 中解析公告标题（仅标题文本）。
    针对常见列表结构：链接文本、列表项等。
    """
    soup = BeautifulSoup(html, "html.parser")
    titles: list[str] = []

    # 常见选择器：公告列表链接、列表项中的链接
    for link in soup.select("a"):
        text = (link.get_text() or "").strip()
        if not text or len(text) < 2:
            continue
        # 过滤明显非公告的链接（如“首页”“打印”等）
        if any(skip in text for skip in ("首页", "打印", "登录", "注册", "©", "ICP")):
            continue
        # 保留像公告的标题：含“公告”“通知”“说明”等，或长度在合理范围
        if "公告" in text or "通知" in text or "说明" in text or (10 <= len(text) <= 200):
            titles.append(text)

    # 去重并保持顺序
    seen = set()
    unique = []
    for t in titles:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def get_new_titles(current: list[str], cached: list[str]) -> list[str]:
    """对比当前标题与缓存，返回新增的标题列表。"""
    cached_set = set(cached)
    return [t for t in current if t not in cached_set]


def check_environment() -> None:
    """
    自检：是否在虚拟环境中运行、邮箱环境变量是否已配置。
    仅打印状态，不暴露敏感信息，不强制退出（便于 CI 或只做抓取不发邮件）。
    """
    in_venv = (
        getattr(sys, "prefix", None) != getattr(sys, "base_prefix", None)
        or os.environ.get("VIRTUAL_ENV")
    )
    if in_venv:
        print("环境自检: 当前在虚拟环境中运行 ✓")
    else:
        print("环境自检: 未检测到虚拟环境（建议在 venv 中运行）", file=sys.stderr)

    user = os.environ.get(ENV_EMAIL_USER)
    pass_ = os.environ.get(ENV_EMAIL_PASS)
    to_ = os.environ.get(ENV_EMAIL_TO)
    email_ok = bool(user and pass_ and to_)
    if email_ok:
        print("环境自检: 邮箱环境变量已配置（有新增时将发邮件）✓")
    else:
        missing = [
            n
            for n, v in [
                (ENV_EMAIL_USER, user),
                (ENV_EMAIL_PASS, pass_),
                (ENV_EMAIL_TO, to_),
            ]
            if not v
        ]
        print(f"环境自检: 以下邮箱变量未设置，将不会发邮件: {', '.join(missing)}")


def send_email(new_titles: list[str]) -> None:
    """
    使用 SMTP 发送通知邮件。
    邮箱账号、密码、收件人均从环境变量读取，禁止写死。
    可选环境变量：SMTP_HOST（默认 smtp.qq.com）、SMTP_PORT（默认 587）。
    """
    user = os.environ.get(ENV_EMAIL_USER)
    password = os.environ.get(ENV_EMAIL_PASS)
    to_addr = os.environ.get(ENV_EMAIL_TO)
    smtp_host = os.environ.get("SMTP_HOST", "smtp.qq.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    if not all((user, password, to_addr)):
        print("未配置邮箱环境变量 EMAIL_USER / EMAIL_PASS / EMAIL_TO，跳过发送邮件。")
        return

    subject = "【2026国考】发现新增公告"
    body = "以下为本次新发现的公告标题：\n\n" + "\n".join(f"- {t}" for t in new_titles)
    body += f"\n\n共 {len(new_titles)} 条。请登录专题页查看：{TARGET_URL}"

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port, timeout=REQUEST_TIMEOUT) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.sendmail(user, [to_addr], msg.as_string())
        print("邮件已发送。")
    except smtplib.SMTPAuthenticationError as e:
        print(f"SMTP 认证失败，请检查 EMAIL_USER/EMAIL_PASS: {e}", file=sys.stderr)
    except Exception as e:
        print(f"发送邮件失败: {e}", file=sys.stderr)


def main() -> None:
    """单次运行：抓取 → 对比缓存 → 有新增则发邮件 → 更新缓存。"""
    check_environment()
    print("开始监控 2026 国考公告...")
    cached = load_cache()

    try:
        html = fetch_page(TARGET_URL)
    except requests.RequestException as e:
        print(f"请求页面失败: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        current_titles = parse_announcement_titles(html)
    except Exception as e:
        print(f"解析页面失败: {e}", file=sys.stderr)
        sys.exit(1)

    new_titles = get_new_titles(current_titles, cached)
    if new_titles:
        print(f"发现 {len(new_titles)} 条新增公告，发送通知。")
        send_email(new_titles)
        save_cache(current_titles)
    else:
        print("无新增公告。")
        # 若有新抓取的标题与缓存不同（例如页面改版），也更新缓存
        if current_titles:
            save_cache(current_titles)

    print("本次运行结束。")


if __name__ == "__main__":
    main()
