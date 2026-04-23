# 国家公务员局 2026 国考公告监控（整页截图版）

在本地或 GitHub Actions 中定时打开国家公务员局 2026 国考专题页面，**用无头浏览器（Playwright）等页面 JS 渲染完成**后：

1. 提取整页的公告条目（标题、日期、链接）
2. 对页面做 **full page 全页截图**
3. 与本地 `cache.json` 对比，检测**新增 / 删除**的公告
4. 如检测到变化，发送一封 HTML 邮件，**列出新增条目并把页面截图内嵌在邮件里**

单次运行、无无限循环，适合每 6 小时跑一次的定时任务。

---

## 一、项目结构

```
gk-monitor/
├── monitor.py            # 监控主脚本（Playwright + 全页截图 + 变化对比 + 发信）
├── test_email.py         # 发信测试脚本（HTML + 内嵌截图）
├── requirements.txt      # Python 依赖（playwright）
├── .gitignore
├── README.md
└── .github/
    └── workflows/
        └── monitor.yml   # 每 6 小时 + 手动触发的 workflow
```

运行过程中会在项目目录生成：

| 文件          | 作用                                                        |
|---------------|-------------------------------------------------------------|
| `cache.json`  | 上次抓到的公告条目快照，用于和本次对比，检测新增 / 删除     |
| `page.png`    | 本次抓到的整页截图（发信用的那张，落盘只是方便排查 / 调试） |

---

## 二、本地运行

### 1. 创建并激活虚拟环境

**Windows（PowerShell）：**

```powershell
cd D:\source\gk-monitor
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

**Linux / macOS：**

```bash
cd /path/to/gk-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. 安装 Playwright 浏览器（仅 Chromium 即可）

> 首次在本机跑必须做这步，否则启动时会报 `Executable doesn't exist`。

```bash
python -m playwright install chromium
```

Linux 上如果缺少系统依赖，加 `--with-deps`：

```bash
python -m playwright install --with-deps chromium
```

### 3. 配置邮箱（环境变量）

**禁止在代码中写死邮箱账号密码。** 必须通过环境变量传入：

| 变量名       | 说明            | 示例                     |
|--------------|-----------------|--------------------------|
| `EMAIL_USER` | 发件邮箱         | `your@qq.com`            |
| `EMAIL_PASS` | 邮箱授权码/密码  | 到邮箱服务商后台获取      |
| `EMAIL_TO`   | 收件邮箱         | `receiver@example.com`   |

可选：

| 变量名         | 说明                                    | 默认值        |
|----------------|-----------------------------------------|---------------|
| `SMTP_HOST`    | SMTP 服务器                             | `smtp.qq.com` |
| `SMTP_PORT`    | 端口；`465` 自动走 SSL，其余走 STARTTLS | `587`         |
| `MONITOR_URL`  | 要监控的页面 URL                        | `http://bm.scs.gov.cn/kl2026` |

**Windows（PowerShell）示例：**

```powershell
$env:EMAIL_USER = "your@qq.com"
$env:EMAIL_PASS = "你的授权码"
$env:EMAIL_TO   = "receiver@example.com"
python monitor.py
```

**Linux / macOS：**

```bash
export EMAIL_USER="your@qq.com"
export EMAIL_PASS="你的授权码"
export EMAIL_TO="receiver@example.com"
python monitor.py
```

不配置上述三个变量时，脚本仍会正常抓取与对比，但**不发邮件**（只打印提示）。

### 4. 单次运行

```bash
python monitor.py
```

脚本行为：

- 打开 `MONITOR_URL`（默认 `http://bm.scs.gov.cn/kl2026`），等 JS 渲染完成
- 解析页面中所有公告条目（标题 + 最近的一个日期 + 链接）
- 生成 `page.png` 整页截图
- 与 `cache.json` 对比：
  - **首次运行**（没有 `cache.json`）：不把当前全部条目当"新增"轰炸，而是发一封 **【网页监控·初始化】** 邮件，带截图确认通道可用，然后写 `cache.json`。
  - 之后：只在**检测到新增 / 删除时**发 **【网页变化提醒】** 邮件，邮件里列出新增 / 删除条目并内嵌整页截图；无变化时不发邮件。
- **仅在邮件发送成功时更新 cache.json**（首次运行例外，首次无论是否发出都写入缓存，避免下次又误判为首次）。

### 5. 验证能否收邮件（可选）

项目内提供 `test_email.py`，用于验证发信通道是否正确。它也会把同目录下的 `page.png`（如果有）作为内嵌图片一起发出：

```bash
# 先跑一次 monitor.py 生成 page.png（即使页面无变化，也会在本地落盘截图）
python monitor.py

# 再发测试邮件
python test_email.py
```

如果收件箱里能看到邮件且能显示截图，说明所有链路都通了。

---

## 三、GitHub Actions（云端定时运行）

### 1. 上传代码

```bash
git add .
git commit -m "feat: 2026国考整页监控 + 截图邮件"
git push
```

### 2. 配置 Secrets

仓库 → **Settings → Secrets and variables → Actions → New repository secret**，至少添加：

| Name         | Value           | 必填 |
|--------------|-----------------|------|
| `EMAIL_USER` | 发件邮箱         | ✅   |
| `EMAIL_PASS` | 邮箱授权码/密码  | ✅   |
| `EMAIL_TO`   | 收件邮箱         | ✅   |

可选：

| Name         | Value                                   |
|--------------|-----------------------------------------|
| `SMTP_HOST`  | 如 `smtp.163.com`（默认 `smtp.qq.com`） |
| `SMTP_PORT`  | 如 `587` 或 `465`（默认 `587`）         |
| `MONITOR_URL`| 想监控的完整 URL（默认是 `kl2026` 入口页） |

### 3. 定时与手动运行

- **定时**：每 6 小时自动运行（cron `0 */6 * * *`，UTC），约对应北京时间 8:00 / 14:00 / 20:00 / 02:00
- **手动**：仓库 **Actions → 2026国考公告监控 → Run workflow**

Workflow 在 `ubuntu-latest` 云端虚机上运行，**本地电脑可以一直关机**。

Workflow 做了几件事：

1. 安装 **fonts-noto-cjk**，让截图里的汉字能正确显示
2. 创建 venv、`pip install -r requirements.txt`
3. `playwright install --with-deps chromium` 安装浏览器及其系统依赖
4. 从 `actions/cache` 恢复 `cache.json`，跑完再保存
5. 每次运行都把 `page.png` 作为 artifact 上传，方便回看（保留 14 天）

---

## 四、工作原理

### 解析规则

脚本在页面渲染完成后，遍历页面中所有的 `<a>` 标签：

- 文本长度 6–200 字符
- 排除导航/功能类链接（"首页 / 登录 / 下载 app / 版权 / ICP" 等）
- 向上 5 层查找最近的日期，形如 `2026-04-20` / `2026/04/20` / `04-20` / `2026年4月20日`

每个条目用 `(title, href)` 作为唯一标识：

- `current − cached` → **新增**
- `cached − current` → **删除**

### 邮件内容

收到的邮件长这样：

- 标题：`【网页变化提醒】中央机关及其直属机构2026年度考试录用公务员专题`
- 正文（HTML）：
  - 顶部 `We detected a change on 中央机关及其直属机构2026年度考试录用公务员专题`
  - 列出所有**新增**条目（绿色 "新增"）和**删除**条目（红色 "删除"）
  - 末尾内嵌**全页截图**

纯文本备用版本同样列出所有新增 / 删除的标题与日期。

---

## 五、安全与合规

- 邮箱凭据仅从环境变量 / GitHub Secrets 读取，不落仓库
- 仅访问公开专题页，使用普通 UA，不绕过任何登录 / 验证码 / 安全机制
- 低频访问（建议 6 小时），单次运行无 `while True` 循环
- 抓到的公告标题 / 日期 / 链接仅用于本地对比与个人通知

---

## 六、常见问题

### 手动跑了 workflow 却没收到邮件

1. 打开 **Actions → 最近那次运行 → monitor**，搜关键字：
   - `环境自检: 以下邮箱变量未设置` → 去 Secrets 里补齐 `EMAIL_USER / EMAIL_PASS / EMAIL_TO`
   - `SMTP 认证失败` → 发件邮箱授权码错误。QQ 要用「授权码」不是登录密码；163/126 要用「授权密码」
   - `邮件已发送。` → 脚本侧成功，优先去**收件箱、垃圾邮件、订阅推广**文件夹里找
2. 修改 Secrets 后**必须再点一次 Run workflow**，旧次运行用的是旧值
3. 云端 IP 可能被部分邮箱拦截，可先在本地跑 `python test_email.py` 验证通道

### 邮件里截图不显示 / 显示为附件

- 大多数邮箱客户端（QQ / 163 / Outlook / Gmail 网页版）都能正常显示内嵌 CID 图片
- 部分客户端可能出于安全策略把内嵌图片降级为附件，这是客户端行为，不影响内容已送达

### 日志里「本次共解析到 0 条」或远少于预期

- 网站结构可能调整过，`<a>` 选择器抓不到；先看 Actions 里上传的 **page-screenshot-*** artifact，确认浏览器实际渲染出的画面是否正常
- 如果画面是对的但解析少，说明过滤过严，可放宽 `monitor.py` 里的 `NOISE_KEYWORDS` 或在脚本里针对具体 DOM 结构写更精确的选择器
- 如果画面就是白屏，多半是 `networkidle` 等到的不够，适当调大 `SETTLE_TIMEOUT_MS`

### 首次运行会不会把所有条目当新增发出来

**不会。** 首次运行（没有 `cache.json`）只发一封 **【网页监控·初始化】** 邮件，确认通道可用；之后的对比才会列出新增 / 删除。

### 想更换要监控的页面

- 在 Secrets 里加 `MONITOR_URL`，填新 URL 即可，无需改代码
- 本地测试：`$env:MONITOR_URL = "..."` 然后 `python monitor.py`
