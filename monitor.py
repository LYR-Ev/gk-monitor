#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026 国考公告监控（整页变化 + 视觉对比版，仿 Visualping）

功能：
- 使用 Playwright 无头浏览器打开目标网页，等待 JS 渲染完成
- 提取页面内所有可见公告条目（标题、日期、链接）
- 对整页进行全页截图
- 与上一次运行的截图做像素级视觉对比，生成高亮差异图，并算出变化率
- 与本地 cache.json 对比，检测新增 / 删除的公告
- 支持关键词检测：命中时在邮件顶部高亮提醒
- 每次运行无论是否有变化都会发一封 HTML 邮件，邮件里内嵌：
    * 本次截图（新）
    * 上次截图（旧，若有）
    * 视觉差异高亮图（若有差异）
    * 新增 / 删除 公告列表
- 单次运行，无无限循环，适配 GitHub Actions
"""

import hashlib
import html as _html
import io
import json
import os
import re
import shutil
import smtplib
import ssl
import sys
import time
from datetime import datetime, timezone, timedelta
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter
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
ENV_KEYWORDS = "KEYWORDS"  # 逗号分隔的关键词，命中则在邮件顶部高亮提醒

NAV_TIMEOUT_MS = 60_000
SETTLE_TIMEOUT_MS = 3_000

# 视觉差异检测参数（像素通道差异阈值，0-255；越小越灵敏）
VISUAL_DIFF_THRESHOLD = 30
# 差异率低于此值则认为是"几乎无视觉变化"（0.0 ~ 1.0）
VISUAL_DIFF_NOISE_FLOOR = 0.001  # 0.1%

CACHE_FILE = Path(__file__).resolve().parent / "cache.json"
SCREENSHOT_FILE = Path(__file__).resolve().parent / "page.png"
PREV_SCREENSHOT_FILE = Path(__file__).resolve().parent / "page_prev.png"
DIFF_SCREENSHOT_FILE = Path(__file__).resolve().parent / "page_diff.png"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

NOISE_KEYWORDS = (
    "首页", "上一页", "下一页", "末页", "尾页", "登录", "注册", "打印",
    "下载app", "ios下载", "android下载", "icp", "copyright", "版权所有",
    "网站地图", "联系我们", "关于我们", "微信公众号",
)

BEIJING_TZ = timezone(timedelta(hours=8))


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
        print("环境自检: 邮箱环境变量已配置（每次运行都会发送邮件）✓")
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
    let dateText = '';
    let node = a;
    for (let depth = 0; depth < 5 && node; depth++) {
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
            page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            try:
                page.wait_for_load_state("networkidle", timeout=20_000)
            except PlaywrightError:
                pass
            page.wait_for_timeout(SETTLE_TIMEOUT_MS)

            page_title = (page.title() or "").strip()

            items_raw = page.evaluate(_JS_COLLECT_ITEMS)
            screenshot_bytes = page.screenshot(full_page=True, type="png")
        finally:
            browser.close()

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
# 视觉差异（Visualping 风格）
# ---------------------------------------------------------------------------

def _align_sizes(img_a: Image.Image, img_b: Image.Image) -> tuple[Image.Image, Image.Image]:
    """把两张图补齐到相同尺寸（取两者最大宽/高），多出的区域填充白色。"""
    w = max(img_a.width, img_b.width)
    h = max(img_a.height, img_b.height)

    def _pad(img: Image.Image) -> Image.Image:
        if img.width == w and img.height == h:
            return img
        canvas = Image.new("RGB", (w, h), (255, 255, 255))
        canvas.paste(img, (0, 0))
        return canvas

    return _pad(img_a), _pad(img_b)


def compute_visual_diff(
    prev_bytes: bytes | None,
    curr_bytes: bytes,
) -> tuple[bytes | None, float]:
    """
    基于像素差异生成一张"当前截图 + 红色半透明高亮差异区域"的图片。

    返回: (diff_png_bytes 或 None, change_ratio 0.0-1.0)
    - 若没有上次截图，返回 (None, 0.0)
    - 若差异率低于 VISUAL_DIFF_NOISE_FLOOR 视为无视觉变化，diff 仍会生成但 ratio 很小
    """
    if not prev_bytes:
        return None, 0.0

    try:
        prev_img = Image.open(io.BytesIO(prev_bytes)).convert("RGB")
        curr_img = Image.open(io.BytesIO(curr_bytes)).convert("RGB")
    except Exception as e:
        print(f"解析截图失败，跳过视觉对比: {e}", file=sys.stderr)
        return None, 0.0

    prev_img, curr_img = _align_sizes(prev_img, curr_img)

    # 逐像素差
    diff = ImageChops.difference(prev_img, curr_img).convert("L")
    # 阈值化：大于 VISUAL_DIFF_THRESHOLD 才算真正变化（避免抗锯齿/字体微抖动）
    mask = diff.point(lambda p: 255 if p > VISUAL_DIFF_THRESHOLD else 0)
    # 膨胀一点让块状变化更明显
    mask = mask.filter(ImageFilter.MaxFilter(5))

    bbox_pixels = sum(1 for p in mask.getdata() if p > 0)
    total_pixels = mask.width * mask.height
    change_ratio = bbox_pixels / total_pixels if total_pixels else 0.0

    # 生成高亮叠加图：当前截图 + 红色半透明覆盖变化区域 + 红框
    highlight = curr_img.copy().convert("RGBA")
    overlay = Image.new("RGBA", highlight.size, (255, 0, 0, 0))
    red_layer = Image.new("RGBA", highlight.size, (255, 0, 0, 96))
    overlay.paste(red_layer, (0, 0), mask)
    highlight = Image.alpha_composite(highlight, overlay)

    # 画出变化区域的外接矩形簇
    try:
        draw = ImageDraw.Draw(highlight)
        bbox = mask.getbbox()
        if bbox:
            draw.rectangle(bbox, outline=(220, 38, 38, 255), width=4)
    except Exception:
        pass

    out = io.BytesIO()
    highlight.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue(), change_ratio


# ---------------------------------------------------------------------------
# 对比
# ---------------------------------------------------------------------------

def _item_key(x: dict) -> str:
    """以标题+链接作为唯一标识。"""
    return ((x.get("title") or "").strip()
            + "||" + (x.get("href") or "").strip())


def diff_items(current: list[dict], cached: list[dict]) -> tuple[list[dict], list[dict]]:
    cached_keys = {_item_key(x) for x in cached}
    current_keys = {_item_key(x) for x in current}
    added = [x for x in current if _item_key(x) not in cached_keys]
    removed = [x for x in cached if _item_key(x) not in current_keys]
    return added, removed


# ---------------------------------------------------------------------------
# 关键词检测
# ---------------------------------------------------------------------------

def parse_keywords() -> list[str]:
    raw = (os.environ.get(ENV_KEYWORDS) or "").strip()
    if not raw:
        return []
    parts = re.split(r"[,，;；\n]+", raw)
    return [p.strip() for p in parts if p.strip()]


def match_keywords(items: list[dict], keywords: list[str]) -> list[tuple[str, list[dict]]]:
    """返回 [(keyword, [hit_item, ...]), ...]，只包含至少命中一条的关键词。"""
    if not keywords:
        return []
    result: list[tuple[str, list[dict]]] = []
    for kw in keywords:
        low = kw.lower()
        hits = [it for it in items if low in (it.get("title") or "").lower()]
        if hits:
            result.append((kw, hits))
    return result


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


def _render_kw_banner(kw_hits: list[tuple[str, list[dict]]]) -> str:
    if not kw_hits:
        return ""
    chips = []
    for kw, hits in kw_hits:
        chips.append(
            f'<span style="display:inline-block;margin:2px 6px 2px 0;padding:2px 10px;'
            f'background:#fff7ed;color:#c2410c;border:1px solid #fdba74;'
            f'border-radius:999px;font-size:12px;">'
            f'{_html.escape(kw)} · {len(hits)} 条</span>'
        )
    return (
        '<div style="margin:0 0 12px;padding:10px 14px;background:#fffbeb;'
        'border:1px solid #fcd34d;border-radius:8px;">'
        '<div style="color:#92400e;font-weight:600;font-size:14px;margin-bottom:4px;">'
        '🔔 关键词命中提醒</div>'
        f'<div>{"".join(chips)}</div>'
        '</div>'
    )


def _render_stats_bar(
    total_items: int,
    added: int,
    removed: int,
    change_ratio: float,
    elapsed_sec: float,
    run_time_str: str,
) -> str:
    def _stat(label: str, value: str, color: str) -> str:
        return (
            '<td style="padding:10px 6px;text-align:center;vertical-align:middle;">'
            f'<div style="font-size:20px;font-weight:700;color:{color};line-height:1.2;">{value}</div>'
            f'<div style="font-size:11px;color:#6b7280;margin-top:2px;">{label}</div>'
            '</td>'
        )

    ratio_pct = f"{change_ratio*100:.2f}%" if change_ratio > 0 else "0.00%"
    ratio_color = "#c53030" if change_ratio >= VISUAL_DIFF_NOISE_FLOOR else "#6b7280"

    return (
        '<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
        'style="width:100%;border-collapse:separate;border-spacing:0;'
        'background:#f8fafc;border-radius:10px;margin:8px 0 14px;">'
        '<tr>'
        + _stat("页面条目", str(total_items), "#1a56db")
        + _stat("新增", str(added), "#0a7f3f")
        + _stat("删除", str(removed), "#c53030")
        + _stat("视觉变化", ratio_pct, ratio_color)
        + _stat("本次耗时", f"{elapsed_sec:.1f}s", "#6b7280")
        + '</tr>'
        + f'<tr><td colspan="5" style="padding:0 10px 10px;text-align:center;'
          f'color:#9ca3af;font-size:11px;">检测时间（北京时间）：{run_time_str}</td></tr>'
        '</table>'
    )


def _render_image_gallery(
    has_prev: bool,
    has_diff: bool,
) -> str:
    """本次 / 上次 / 差异 三栏图片展示。若某张没有则省略。"""
    cols: list[str] = []

    def _cell(label: str, cid: str, tint: str) -> str:
        return (
            '<td style="padding:4px;vertical-align:top;width:33.33%;">'
            f'<div style="border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;background:#fff;">'
            f'<div style="padding:6px 10px;background:{tint};color:#fff;font-size:12px;font-weight:600;">{label}</div>'
            f'<img src="cid:{cid}" alt="{label}" style="display:block;width:100%;height:auto;" />'
            f'</div>'
            '</td>'
        )

    if has_prev:
        cols.append(_cell("上次截图", "page_prev", "#64748b"))
    cols.append(_cell("本次截图", "page_current", "#1a56db"))
    if has_diff:
        cols.append(_cell("视觉差异高亮", "page_diff", "#c53030"))

    return (
        '<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
        'style="width:100%;border-collapse:separate;border-spacing:0;">'
        f'<tr>{"".join(cols)}</tr>'
        '</table>'
    )


def build_email(
    page_title: str,
    added: list[dict],
    removed: list[dict],
    url: str,
    user: str,
    to_addr: str,
    screenshot_bytes: bytes,
    prev_screenshot_bytes: bytes | None,
    diff_screenshot_bytes: bytes | None,
    change_ratio: float,
    kw_hits: list[tuple[str, list[dict]]],
    total_items: int,
    elapsed_sec: float,
    is_first_run: bool = False,
) -> MIMEMultipart:
    title = page_title or "目标网页"

    has_diff = bool(diff_screenshot_bytes) and change_ratio >= VISUAL_DIFF_NOISE_FLOOR
    has_item_change = bool(added or removed)
    has_kw = bool(kw_hits)

    run_time_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")

    # 标题：优先显示关键词命中 > 有变化 > 初始化 > 无变化
    if is_first_run:
        subject = f"【网页监控·初始化】{title}"
        header_hint = "Initial snapshot captured for"
    elif has_kw:
        subject = f"【关键词命中】{title}"
        header_hint = "Keyword match on"
    elif has_item_change or has_diff:
        subject = f"【网页变化提醒】{title}"
        header_hint = "We detected a change on"
    else:
        subject = f"【网页巡检·无变化】{title}"
        header_hint = "No change detected on"

    # -------- 纯文本版 --------
    plain_lines = [
        f"网页监控报告：{title}",
        f"链接：{url}",
        f"检测时间（北京时间）：{run_time_str}",
        f"页面条目：{total_items} | 新增：{len(added)} | 删除：{len(removed)} | "
        f"视觉变化：{change_ratio*100:.2f}% | 耗时：{elapsed_sec:.1f}s",
        "",
    ]
    if kw_hits:
        plain_lines.append("关键词命中：")
        for kw, hits in kw_hits:
            plain_lines.append(f"  * {kw}: {len(hits)} 条")
            for h in hits[:5]:
                plain_lines.append(f"      - {h['title']}")
        plain_lines.append("")
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
    if not added and not removed and not is_first_run:
        plain_lines.append("本次检查未发现公告条目变化。")
    if is_first_run:
        plain_lines.append("首次运行，已初始化缓存。此后每次运行都会发送一封报告邮件。")
    plain_body = "\n".join(plain_lines)

    # -------- HTML 版 --------
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
                '<p style="color:#444;margin:8px 0;">首次运行，已初始化缓存。此后每次运行都会发一份完整报告。</p>'
            )
        else:
            change_html_parts.append(
                '<p style="color:#444;margin:8px 0;">📭 本次未检测到公告条目变化；附上本次截图供参考。</p>'
            )
    change_html = "".join(change_html_parts)

    safe_title = _html.escape(title)
    safe_url = _html.escape(url, quote=True)
    safe_hint = _html.escape(header_hint)

    kw_banner_html = _render_kw_banner(kw_hits)
    stats_bar_html = _render_stats_bar(
        total_items=total_items,
        added=len(added),
        removed=len(removed),
        change_ratio=change_ratio,
        elapsed_sec=elapsed_sec,
        run_time_str=run_time_str,
    )
    gallery_html = _render_image_gallery(
        has_prev=bool(prev_screenshot_bytes),
        has_diff=has_diff,
    )

    html_body = f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:16px;background:#f5f7fb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,'PingFang SC','Microsoft YaHei',sans-serif;color:#222;">
    <div style="max-width:960px;margin:0 auto;background:#fff;border-radius:12px;padding:20px 24px;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
      <p style="color:#6b7280;font-size:13px;margin:0;text-align:center;">{safe_hint}</p>
      <h2 style="color:#1a56db;margin:4px 0 8px;font-size:18px;text-align:center;">{safe_title}</h2>

      {kw_banner_html}
      {stats_bar_html}

      <div style="background:#eff6ff;border-radius:8px;padding:12px 16px;font-size:14px;line-height:1.6;">
        {change_html}
      </div>

      <p style="margin:18px 0 8px;color:#374151;font-size:13px;font-weight:600;">页面快照</p>
      {gallery_html}

      <p style="margin:16px 0 4px;color:#6b7280;font-size:12px;">
        链接：<a href="{safe_url}" style="color:#1a73e8;">{safe_url}</a>
      </p>
      <p style="margin:0;color:#9ca3af;font-size:11px;">
        本邮件由 gk-monitor 自动生成，仿 Visualping 风格；每次定时任务都会发送一份完整报告。
      </p>
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

    def _attach_image(img_bytes: bytes, cid: str, filename: str) -> None:
        img = MIMEImage(img_bytes, _subtype="png")
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=filename)
        msg_root.attach(img)

    _attach_image(screenshot_bytes, "page_current", "page.png")
    if prev_screenshot_bytes:
        _attach_image(prev_screenshot_bytes, "page_prev", "page_prev.png")
    if has_diff and diff_screenshot_bytes:
        _attach_image(diff_screenshot_bytes, "page_diff", "page_diff.png")

    return msg_root


def send_email_report(
    page_title: str,
    added: list[dict],
    removed: list[dict],
    screenshot_bytes: bytes,
    prev_screenshot_bytes: bytes | None,
    diff_screenshot_bytes: bytes | None,
    change_ratio: float,
    kw_hits: list[tuple[str, list[dict]]],
    total_items: int,
    elapsed_sec: float,
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
        prev_screenshot_bytes=prev_screenshot_bytes,
        diff_screenshot_bytes=diff_screenshot_bytes,
        change_ratio=change_ratio,
        kw_hits=kw_hits,
        total_items=total_items,
        elapsed_sec=elapsed_sec,
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

    t_start = time.perf_counter()

    # 读取上一次的截图（用于视觉对比）
    prev_screenshot_bytes: bytes | None = None
    if PREV_SCREENSHOT_FILE.exists():
        try:
            prev_screenshot_bytes = PREV_SCREENSHOT_FILE.read_bytes()
            print(f"发现上次截图 {PREV_SCREENSHOT_FILE.name}（{len(prev_screenshot_bytes)//1024} KB），将用于视觉对比。")
        except OSError as e:
            print(f"读取上次截图失败，跳过视觉对比: {e}", file=sys.stderr)

    try:
        screenshot_bytes, items, page_title = capture_page(url)
    except PlaywrightError as e:
        print(f"打开页面或渲染失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 本次截图落盘
    try:
        SCREENSHOT_FILE.write_bytes(screenshot_bytes)
        print(f"本次截图已保存到 {SCREENSHOT_FILE.name}（{len(screenshot_bytes)//1024} KB）")
    except OSError as e:
        print(f"截图保存失败（不影响后续发信）: {e}", file=sys.stderr)

    print(f"页面标题：{page_title}")
    print(f"本次共解析到 {len(items)} 条条目。")
    for i, it in enumerate(items[:10], 1):
        tail = f"  ({it['date']})" if it['date'] else ""
        print(f"  [{i}] {it['title'][:60]}{'…' if len(it['title']) > 60 else ''}{tail}")
    if len(items) > 10:
        print(f"  … 共 {len(items)} 条")

    # 视觉对比
    diff_screenshot_bytes, change_ratio = compute_visual_diff(
        prev_screenshot_bytes, screenshot_bytes,
    )
    if diff_screenshot_bytes:
        try:
            DIFF_SCREENSHOT_FILE.write_bytes(diff_screenshot_bytes)
            print(f"视觉差异图已保存到 {DIFF_SCREENSHOT_FILE.name}；变化率 {change_ratio*100:.2f}%。")
        except OSError as e:
            print(f"差异图保存失败（不影响发信）: {e}", file=sys.stderr)
    else:
        print("无上次截图，跳过视觉对比。")

    # 条目对比
    cache = load_cache()
    cached_items = cache.get("items", []) or []
    is_first_run = not cached_items
    added, removed = diff_items(items, cached_items)

    # 关键词检测
    keywords = parse_keywords()
    kw_hits = match_keywords(items, keywords) if keywords else []
    if kw_hits:
        print(f"关键词命中：{', '.join(f'{kw}({len(hits)})' for kw, hits in kw_hits)}")
    elif keywords:
        print(f"已配置关键词 {keywords}，本次未命中。")

    elapsed_sec = time.perf_counter() - t_start

    if is_first_run:
        print("首次运行：没有历史缓存；将初始化并发送一封报告邮件。")

    if added or removed:
        print(f"公告条目变化：新增 {len(added)} 条，删除 {len(removed)} 条。")
        for it in added[:20]:
            print(f"  + {it['title']}")
        for it in removed[:20]:
            print(f"  - {it['title']}")
    else:
        print("公告条目无变化。")

    # 无论是否有变化都发邮件（满足"每 6 小时都收到邮件"的需求）
    email_ok = send_email_report(
        page_title=page_title,
        added=added,
        removed=removed,
        screenshot_bytes=screenshot_bytes,
        prev_screenshot_bytes=prev_screenshot_bytes,
        diff_screenshot_bytes=diff_screenshot_bytes,
        change_ratio=change_ratio,
        kw_hits=kw_hits,
        total_items=len(items),
        elapsed_sec=elapsed_sec,
        url=url,
        is_first_run=is_first_run,
    )

    # 更新缓存（条目 + 当前截图 → 作为下次的 prev）
    # 即便邮件发送失败也更新：失败时不更新会导致下次把本次全部新增又当一次"新增"再次尝试发信，
    # 但在无变化也发邮件的模式下，这里更新是合理的——失败通常是临时性的 SMTP 问题。
    save_cache(items, page_title)
    try:
        shutil.copyfile(SCREENSHOT_FILE, PREV_SCREENSHOT_FILE)
        print(f"已把本次截图复制为 {PREV_SCREENSHOT_FILE.name}，作为下次视觉对比基准。")
    except OSError as e:
        print(f"复制截图为下次基准失败: {e}", file=sys.stderr)

    if not email_ok:
        print("注意：本次邮件未发出，请检查 SMTP 配置。", file=sys.stderr)

    print(f"本次运行结束（耗时 {elapsed_sec:.1f}s）。")


if __name__ == "__main__":
    main()
