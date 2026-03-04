#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国家公务员局 2026 国考公告监控脚本

- 访问官方公开专题页面，抓取公告标题
- 与本地 cache.json 对比，有新增或无新增均可发邮件通知
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

TARGET_URL = "http://bm.scs.gov.cn/kl2026"
REDIRECT_FALLBACK_URL = "http://www.scs.gov.cn/gkIndex.html"
ENV_MONITOR_URL = "MONITOR_URL"
# 若不想在 GitHub Secrets 里配 MONITOR_URL，可把公告列表页的完整 URL 填在下面，否则留空 ""
DEFAULT_MONITOR_URL = ""

REQUEST_TIMEOUT = 30
CACHE_FILE = Path(__file__).resolve().parent / "cache.json"
ENV_EMAIL_USER = "EMAIL_USER"
ENV_EMAIL_PASS = "EMAIL_PASS"
ENV_EMAIL_TO = "EMAIL_TO"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

ANNOUNCEMENT_KEYWORDS = (
    "公告", "通知", "招考", "报考", "职位", "调剂", "笔试", "面试",
    "资格", "体检", "录用", "成绩", "中央机关", "国考",
)
NOISE_KEYWORDS = (
    "首页", "上一页", "下一页", "末页", "尾页", "登录", "注册", "打印",
    "下载", "app", "ios", "android", "copyright", "icp",
)


def load_cache() -> list[str]:
    if not CACHE_FILE.exists():
        return []
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("titles", []) if isinstance(data, dict) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_cache(titles: list[str]) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"titles": titles}, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"保存缓存失败: {e}", file=sys.stderr)


def fetch_page(url: str) -> str:
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def fetch_page_maybe_follow_redirect() -> str:
    direct_url = (os.environ.get(ENV_MONITOR_URL) or "").strip() or (DEFAULT_MONITOR_URL or "").strip()
    if direct_url and direct_url.startswith("http"):
        return fetch_page(direct_url)
    html_main = fetch_page(TARGET_URL)
    if len(html_main) < 2000 and "location.href" in html_main:
        match = re.search(r'location\.href\s*=\s*["\']([^"\']+)["\']', html_main)
        if match:
            redirect_url = match.group(1).strip()
            if redirect_url.startswith("http"):
                try:
                    return html_main + "\n" + fetch_page(redirect_url)
                except requests.RequestException:
                    pass
        try:
            return html_main + "\n" + fetch_page(REDIRECT_FALLBACK_URL)
        except requests.RequestException:
            pass
    return html_main


def parse_announcement_titles(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")

    def normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    titles: list[str] = []
    for link in soup.select("a"):
        text = normalize_text(link.get_text() or "")
        if not text or len(text) < 2:
            continue
        if any(k in text for k in NOISE_KEYWORDS):
            continue
        if any(k in text for k in ANNOUNCEMENT_KEYWORDS) or (10 <= len(text) <= 120):
            titles.append(text)
    seen = set()
    return [t for t in titles if t not in seen and not seen.add(t)]


def get_new_titles(current: list[str], cached: list[str]) -> list[str]:
    cached_set = set(cached)
    return [t for t in current if t not in cached_set]


def check_environment() -> None:
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
    if user and pass_ and to_:
        print("环境自检: 邮箱环境变量已配置（有新增时将发邮件）✓")
    else:
        missing = [n for n, v in [(ENV_EMAIL_USER, user), (ENV_EMAIL_PASS, pass_), (ENV_EMAIL_TO, to_)] if not v]
        print(f"环境自检: 以下邮箱变量未设置，将不会发邮件: {', '.join(missing)}")


def send_email(new_titles: list[str]) -> bool:
    user = os.environ.get(ENV_EMAIL_USER)
    password = os.environ.get(ENV_EMAIL_PASS)
    to_addr = os.environ.get(ENV_EMAIL_TO)
    smtp_host = os.environ.get("SMTP_HOST") or "smtp.qq.com"
    try:
        smtp_port = int(os.environ.get("SMTP_PORT") or "587")
    except ValueError:
        smtp_port = 587
    if not all((user, password, to_addr)):
        print("未配置邮箱环境变量 EMAIL_USER / EMAIL_PASS / EMAIL_TO，跳过发送邮件。")
        return False
    link_url = (os.environ.get(ENV_MONITOR_URL) or "").strip() or (DEFAULT_MONITOR_URL or "").strip() or TARGET_URL
    if new_titles:
        subject = "【2026国考】发现新增公告"
        body = "以下为本次新发现的公告标题：\n\n" + "\n".join(f"- {t}" for t in new_titles) + f"\n\n共 {len(new_titles)} 条。请登录专题页查看：{link_url}"
    else:
        subject = "【2026国考】本次检查：无新增公告"
        body = "本次检查未发现新增公告。\n\n请登录专题页查看：" + link_url
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
        if send_email(new_titles):
            save_cache(current_titles)
        else:
            print("邮件发送失败，本次不更新缓存。", file=sys.stderr)
    else:
        print("无新增公告，发送「无新增」通知邮件。")
        send_email([])
        if current_titles:
            save_cache(current_titles)
    print("本次运行结束。")


if __name__ == "__main__":
    main()
