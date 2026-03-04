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
import re
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
# 该页可能返回 302 或页面内 JS 跳转，脚本会尝试跟随一次跳转并合并解析
TARGET_URL = "http://bm.scs.gov.cn/kl2026"
# 若主站返回的跳转目标（用于合并抓取，增加可解析内容）
REDIRECT_FALLBACK_URL = "http://www.scs.gov.cn/gkIndex.html"

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

ANNOUNCEMENT_KEYWORDS = (
    "公告",
    "通知",
    "招考",
    "报考",
    "职位",
    "调剂",
    "笔试",
    "面试",
    "资格",
    "体检",
    "录用",
    "成绩",
    "中央机关",
    "国考",
)

NOISE_KEYWORDS = (
    "首页",
    "上一页",
    "下一页",
    "末页",
    "尾页",
    "登录",
    "注册",
    "打印",
    "下载",
    "app",
    "ios",
    "android",
    "copyright",
    "icp",
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


def fetch_page_maybe_follow_redirect() -> str:
    """
    先请求 TARGET_URL；若返回内容很少且包含 location.href 跳转，
    则解析出目标 URL 再请求一次，将两段 HTML 合并返回供解析。
    仍只访问公开页面，不绕过任何安全机制。
    """
    html_main = fetch_page(TARGET_URL)
    if len(html_main) < 2000 and "location.href" in html_main:
        match = re.search(r'location\.href\s*=\s*["\']([^"\']+)["\']', html_main)
        if match:
            redirect_url = match.group(1).strip()
            if redirect_url.startswith("http"):
                try:
                    html_redirect = fetch_page(redirect_url)
                    return html_main + "\n" + html_redirect
                except requests.RequestException:
                    pass
        try:
            html_fallback = fetch_page(REDIRECT_FALLBACK_URL)
            return html_main + "\n" + html_fallback
        except requests.RequestException:
            pass
    return html_main


def parse_announcement_titles(html: str) -> list[str]:
    """
    从专题页 HTML 中解析公告标题（仅标题文本）。
    针对常见列表结构：链接文本、列表项等。
    """
    soup = BeautifulSoup(html, "html.parser")

    def normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def looks_like_announcement(text: str, href: str) -> bool:
        text_lower = text.lower()
        href_lower = href.lower()
        if len(text) < 6 or len(text) > 120:
            return False
        if href_lower.startswith("javascript:"):
            return False
        if any(k in text_lower for k in NOISE_KEYWORDS):
            return False
        has_keyword = any(k in text for k in ANNOUNCEMENT_KEYWORDS)
        has_date = bool(re.search(r"20\d{2}[./-年]\d{1,2}", text))
        return has_keyword or has_date

    titles: list[str] = []
    for link in soup.select("a"):
        text = normalize_text(link.get_text() or "")
        href = (link.get("href") or "").strip()
        if looks_like_announcement(text, href):
            titles.append(text)

    # 兜底：若严格规则匹配过少，使用较宽松策略避免漏抓
    if len(titles) < 3:
        for link in soup.select("a"):
            text = normalize_text(link.get_text() or "")
            if not text:
                continue
            if any(k in text.lower() for k in NOISE_KEYWORDS):
                continue
            if 10 <= len(text) <= 120:
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


def send_email(new_titles: list[str]) -> bool:
    """
    使用 SMTP 发送通知邮件。
    邮箱账号、密码、收件人均从环境变量读取，禁止写死。
    可选环境变量：SMTP_HOST（默认 smtp.qq.com）、SMTP_PORT（默认 587）。
    """
    user = os.environ.get(ENV_EMAIL_USER)
    password = os.environ.get(ENV_EMAIL_PASS)
    to_addr = os.environ.get(ENV_EMAIL_TO)
    smtp_host = os.environ.get("SMTP_HOST") or "smtp.qq.com"
    smtp_port_raw = os.environ.get("SMTP_PORT")
    try:
        smtp_port = int(smtp_port_raw) if smtp_port_raw else 587
    except ValueError:
        print(
            f"SMTP_PORT={smtp_port_raw!r} 非法，回退到默认端口 587。",
            file=sys.stderr,
        )
        smtp_port = 587

    if not all((user, password, to_addr)):
        print("未配置邮箱环境变量 EMAIL_USER / EMAIL_PASS / EMAIL_TO，跳过发送邮件。")
        return False

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
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"SMTP 认证失败，请检查 EMAIL_USER/EMAIL_PASS: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"发送邮件失败: {e}", file=sys.stderr)
        return False


def main() -> None:
    """单次运行：抓取 → 对比缓存 → 有新增则发邮件 → 更新缓存。"""
    check_environment()
    print("开始监控 2026 国考公告...")
    cached = load_cache()

    try:
        html = fetch_page_maybe_follow_redirect()
    except requests.RequestException as e:
        print(f"请求页面失败: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        current_titles = parse_announcement_titles(html)
    except Exception as e:
        print(f"解析页面失败: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"本次共解析到 {len(current_titles)} 条公告/链接标题。")
    new_titles = get_new_titles(current_titles, cached)
    if new_titles:
        print(f"发现 {len(new_titles)} 条新增公告，发送通知。")
        email_sent = send_email(new_titles)
        if email_sent:
            save_cache(current_titles)
        else:
            print("邮件发送失败，本次不更新缓存，保留新增以便下次重试。", file=sys.stderr)
    else:
        print("无新增公告。")

    print("本次运行结束。")


if __name__ == "__main__":
    main()
