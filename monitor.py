#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026 国考公告监控（整页变化 + 截图版）

- 使用 Playwright 无头浏览器打开目标网页，等待 JS 渲染完成
- 提取页面内所有可见公告条目（标题、日期、链接）
- 对整页进行全页截图
- 与本地 cache.json 对比，检测新增 / 删除的公告
- 发现变化时发送 HTML 邮件，列出变化并内嵌页面截图
- 单次运行，无无限循环，适配 GitHub Actions
"""

import hashlib
import html as _html
import json
import os
import re
import smtplib
import ssl
import sys
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

TARGET_URL_DEFAULT = "http://bm.scs.gov.cn/kl2026"
ENV_MONITOR_URL = "MONITOR_URL"
ENV_EMAIL_USER = "EMAIL_USER"
ENV_EMAIL_PASS = "EMAIL_PASS"
ENV_EMAIL_TO = "EMAIL_TO"

NAV_TIMEOUT_MS = 60_000
SETTLE_TIMEOUT_MS = 3_000

CACHE_FILE = Path(__file__).resolve().parent / "cache.json"
SCREENSHOT_FILE = Path(__file__).resolve().parent / "page.png"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

NOISE_KEYWORDS = (
    "首页", "上一页", "下一页", "末页", "尾页", "登录", "注册", "打印",
    "下载app", "ios下载", "android下载", "icp", "copyright", "版权所有",
    "网站地图", "联系我们", "关于我们", "微信公众号",
)


# ---------------------------------------------------------------------------
# 缓存
# ---------------------------------------------------------------------------

def load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {"items": [], "page_title": ""}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"items": [], "page_title": ""}
        items = data.get("items", [])
        if not isinstance(items, list):
            items = []
        return {
            "items": items,
            "page_title": data.get("page_title", ""),
        }
    except (json.JSONDecodeError, OSError):
        return {"items": [], "page_title": ""}


def save_cache(items: list[dict], page_title: str) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"items": items, "page_title": page_title},
                f, ensure_ascii=False, indent=2,
            )
    except OSError as e:
        print(f"保存缓存失败: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 环境自检
# ---------------------------------------------------------------------------

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
    pw = os.environ.get(ENV_EMAIL_PASS)
    to_ = os.environ.get(ENV_EMAIL_TO)
    if user and pw and to_:
        print("环境自检: 邮箱环境变量已配置（检测到变化时将发邮件）✓")
    else:
        missing = [
            n for n, v in [
                (ENV_EMAIL_USER, user),
                (ENV_EMAIL_PASS, pw),
                (ENV_EMAIL_TO, to_),
            ] if not v
        ]
        print(f"环境自检: 以下邮箱变量未设置，将不会发邮件: {', '.join(missing)}")


# ---------------------------------------------------------------------------
# 页面抓取 + 截图
# ---------------------------------------------------------------------------

# 在浏览器里执行的脚本：收集所有"像公告条目"的 <a> 的文本、href、最近的日期
_JS_COLLECT_ITEMS = r"""
() => {
  const dateRe = /(20\d{2}[\-\/\.年]\s*\d{1,2}[\-\/\.月]\s*\d{1,2}日?)|(\d{1,2}[\-\/\.]\d{1,2})/;
  const results = [];
  const seen = new Set();
  const links = Array.from(document.querySelectorAll('a'));
  for (const a of links) {
    const rect = a.getBoundingClientRect();
    const style = window.getComputedStyle(a);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    const text = ((a.innerText || a.textContent || '')
      .replace(/\s+/g, ' ')).trim();
    if (!text) continue;
    if (text.length < 6 || text.length > 200) continue;
    const href = a.href || '';
    const key = text + '|' + href;
    if (seen.has(key)) continue;
    seen.add(key);
    // 向上找最近 4 层的父节点，看是否有日期
    let dateText = '';
    let node = a;
    for (let depth = 0; depth < 5 && node; depth++) {
      // 先看兄弟节点
      const sib = node.parentElement
        ? Array.from(node.parentElement.children).map(
            c => (c.innerText || c.textContent || '')
          ).join(' ')
        : '';
      const tm = sib.match(dateRe);
      if (tm) { dateText = tm[0]; break; }
      node = node.parentElement;
    }
    results.push({ text, href, date: dateText });
  }
  return results;
}
"""


def capture_page(url: str) -> tuple[bytes, list[dict], str]:
    """
    打开目标页面，等待渲染完成，返回:
      - full_page 截图 (PNG bytes)
      - 公告条目列表 [{id, title, date, href}]
      - 页面 <title>
    """
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            context = browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 900},
                locale="zh-CN",
            )
            page = context.new_page()
            # 某些政府站是 http 明文，设置长一点的导航超时
            page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            try:
                page.wait_for_load_state("networkidle", timeout=20_000)
            except PlaywrightError:
                pass
            # 多等 2 秒给前端框架渲染列表
            page.wait_for_timeout(SETTLE_TIMEOUT_MS)

            page_title = (page.title() or "").strip()

            items_raw = page.evaluate(_JS_COLLECT_ITEMS)
            screenshot_bytes = page.screenshot(full_page=True, type="png")
        finally:
            browser.close()

    # 去噪 + 去重
    seen_keys: set[tuple[str, str]] = set()
    items: list[dict] = []
    for it in items_raw or []:
        text = (it.get("text") or "").strip()
        href = (it.get("href") or "").strip()
        date = (it.get("date") or "").strip()
        if not text:
            continue
        low = text.lower()
        if any(k.lower() in low for k in NOISE_KEYWORDS):
            continue
        key = (text, href)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        iid = href or f"txt:{hashlib.md5(text.encode('utf-8')).hexdigest()[:10]}"
        items.append({"id": iid, "title": text, "date": date, "href": href})
    return screenshot_bytes, items, page_title


# ---------------------------------------------------------------------------
# 对比
# ---------------------------------------------------------------------------

def _item_key(x: dict) -> str:
    """以标题+链接作为唯一标识。链接里去掉随机 query 能更稳健，但多数政府站链接稳定，此处直接用。"""
    return ((x.get("title") or "").strip()
            + "||" + (x.get("href") or "").strip())


def diff_items(current: list[dict], cached: list[dict]) -> tuple[list[dict], list[dict]]:
    cached_keys = {_item_key(x) for x in cached}
    current_keys = {_item_key(x) for x in current}
    added = [x for x in current if _item_key(x) not in cached_keys]
    removed = [x for x in cached if _item_key(x) not in current_keys]
    return added, removed


# ---------------------------------------------------------------------------
# 发送邮件（HTML + 内嵌截图）
# ---------------------------------------------------------------------------

def _render_change_list(items: list[dict], color: str, prefix: str) -> str:
    if not items:
        return ""
    rows = []
    for it in items:
        t = _html.escape(it.get("title") or "")
        date = _html.escape(it.get("date") or "")
        href = it.get("href") or ""
        if href.startswith(("http://", "https://")):
            safe_href = _html.escape(href, quote=True)
            link_html = (
                f'<a href="{safe_href}" '
                f'style="color:#1a73e8;text-decoration:none;">{t}</a>'
            )
        else:
            link_html = t
        rows.append(
            '<li style="margin:6px 0;color:#222;line-height:1.5;">'
            f'<span style="color:{color};font-weight:600;">{prefix}</span> '
            f'{link_html}'
            + (f' <span style="color:#888;font-size:12px;">（{date}）</span>' if date else '')
            + '</li>'
        )
    return '<ul style="padding-left:20px;margin:8px 0;">' + "".join(rows) + '</ul>'


def build_email(
    page_title: str,
    added: list[dict],
    removed: list[dict],
    url: str,
    user: str,
    to_addr: str,
    screenshot_bytes: bytes,
    is_first_run: bool = False,
) -> MIMEMultipart:
    title = page_title or "目标网页"

    if is_first_run:
        subject = f"【网页监控·初始化】{title}"
        header_hint = "Initial snapshot captured for"
    elif added or removed:
        subject = f"【网页变化提醒】{title}"
        header_hint = "We detected a change on"
    else:
        subject = f"【网页无变化】{title}"
        header_hint = "No change detected on"

    # 文本版
    plain_lines = [f"检测到网页变化：{title}", f"链接：{url}", ""]
    if added:
        plain_lines.append(f"新增 {len(added)} 条：")
        for it in added:
            line = f"  + {it['title']}"
            if it.get("date"):
                line += f"（{it['date']}）"
            plain_lines.append(line)
        plain_lines.append("")
    if removed:
        plain_lines.append(f"删除 {len(removed)} 条：")
        for it in removed:
            line = f"  - {it['title']}"
            if it.get("date"):
                line += f"（{it['date']}）"
            plain_lines.append(line)
        plain_lines.append("")
    if not added and not removed:
        if is_first_run:
            plain_lines.append("首次运行，已初始化缓存。此后若发现变化会再次发信。")
        else:
            plain_lines.append("本次检查未发现变化。")
    plain_body = "\n".join(plain_lines)

    # HTML 版
    change_html_parts: list[str] = []
    if added:
        change_html_parts.append(
            f'<p style="margin:12px 0 4px;color:#0a7f3f;font-weight:600;font-size:14px;">'
            f'新增 {len(added)} 条公告</p>'
            + _render_change_list(added, "#0a7f3f", "新增")
        )
    if removed:
        change_html_parts.append(
            f'<p style="margin:12px 0 4px;color:#c53030;font-weight:600;font-size:14px;">'
            f'删除 {len(removed)} 条公告</p>'
            + _render_change_list(removed, "#c53030", "删除")
        )
    if not change_html_parts:
        if is_first_run:
            change_html_parts.append(
                '<p style="color:#444;margin:8px 0;">首次运行，已初始化缓存。此后若发现变化会再次发信。</p>'
            )
        else:
            change_html_parts.append(
                '<p style="color:#444;margin:8px 0;">本次检查未发现变化。</p>'
            )
    change_html = "".join(change_html_parts)

    safe_title = _html.escape(title)
    safe_url = _html.escape(url, quote=True)
    safe_hint = _html.escape(header_hint)

    html_body = f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:16px;background:#f5f7fb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,'PingFang SC','Microsoft YaHei',sans-serif;color:#222;">
    <div style="max-width:680px;margin:0 auto;background:#fff;border-radius:12px;padding:20px 24px;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
      <p style="color:#6b7280;font-size:13px;margin:0;text-align:center;">{safe_hint}</p>
      <h2 style="color:#1a56db;margin:4px 0 16px;font-size:18px;text-align:center;">{safe_title}</h2>
      <div style="background:#eff6ff;border-radius:8px;padding:12px 16px;font-size:14px;line-height:1.6;">
        {change_html}
      </div>
      <p style="margin:16px 0 8px;color:#6b7280;font-size:12px;">
        链接：<a href="{safe_url}" style="color:#1a73e8;">{safe_url}</a>
      </p>
      <p style="margin:0 0 12px;color:#9ca3af;font-size:12px;">以下为本次抓取时页面的完整截图：</p>
      <div style="border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
        <img src="cid:page_screenshot" alt="页面截图"
             style="display:block;width:100%;max-width:640px;height:auto;" />
      </div>
    </div>
  </body>
</html>
"""

    # multipart/related 包装，使内嵌图片能通过 CID 引用
    msg_root = MIMEMultipart("related")
    msg_root["Subject"] = subject
    msg_root["From"] = user
    msg_root["To"] = to_addr

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(plain_body, "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg_root.attach(alt)

    img = MIMEImage(screenshot_bytes, _subtype="png")
    img.add_header("Content-ID", "<page_screenshot>")
    img.add_header("Content-Disposition", "inline", filename="page.png")
    msg_root.attach(img)
    return msg_root


def send_email_with_screenshot(
    page_title: str,
    added: list[dict],
    removed: list[dict],
    screenshot_bytes: bytes,
    url: str,
    is_first_run: bool = False,
) -> bool:
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

    msg = build_email(
        page_title=page_title,
        added=added,
        removed=removed,
        url=url,
        user=user,
        to_addr=to_addr,
        screenshot_bytes=screenshot_bytes,
        is_first_run=is_first_run,
    )

    try:
        context = ssl.create_default_context()
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=60) as server:
                server.login(user, password)
                server.sendmail(user, [to_addr], msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=60) as server:
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


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    check_environment()
    url = (os.environ.get(ENV_MONITOR_URL) or "").strip() or TARGET_URL_DEFAULT
    print(f"开始监控：{url}")

    try:
        screenshot_bytes, items, page_title = capture_page(url)
    except PlaywrightError as e:
        print(f"打开页面或渲染失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 同时把截图落盘，方便 workflow 上传 artifact 或本地调试
    try:
        SCREENSHOT_FILE.write_bytes(screenshot_bytes)
        print(f"页面截图已保存到 {SCREENSHOT_FILE.name}（{len(screenshot_bytes)//1024} KB）")
    except OSError as e:
        print(f"截图保存失败（不影响后续发信）: {e}", file=sys.stderr)

    print(f"页面标题：{page_title}")
    print(f"本次共解析到 {len(items)} 条条目。")
    for i, it in enumerate(items[:10], 1):
        tail = f"  ({it['date']})" if it['date'] else ""
        print(f"  [{i}] {it['title'][:60]}{'…' if len(it['title']) > 60 else ''}{tail}")
    if len(items) > 10:
        print(f"  … 共 {len(items)} 条")

    cache = load_cache()
    cached_items = cache.get("items", []) or []
    is_first_run = not cached_items

    added, removed = diff_items(items, cached_items)

    if is_first_run:
        print("首次运行，未检测到历史缓存。将初始化缓存并发送一封初始化邮件，便于确认通道可用。")
        if send_email_with_screenshot(page_title, [], [], screenshot_bytes, url, is_first_run=True):
            save_cache(items, page_title)
        else:
            # 邮件没发出去也先把缓存存下来，避免下次又当首次运行把一堆条目当新增
            save_cache(items, page_title)
        print("本次运行结束。")
        return

    if added or removed:
        print(f"检测到变化：新增 {len(added)} 条，删除 {len(removed)} 条。")
        for it in added[:20]:
            print(f"  + {it['title']}")
        for it in removed[:20]:
            print(f"  - {it['title']}")
        if send_email_with_screenshot(page_title, added, removed, screenshot_bytes, url):
            save_cache(items, page_title)
        else:
            print("邮件发送失败，本次不更新缓存。", file=sys.stderr)
    else:
        print("本次未检测到变化，不发邮件。")
        # 覆盖写一次（让缓存文件保留最新 page_title 等辅助字段）
        save_cache(items, page_title)

    print("本次运行结束。")


if __name__ == "__main__":
    main()
