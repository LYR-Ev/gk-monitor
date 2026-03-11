# 国家公务员局 2026 国考公告监控

在本地或 GitHub Actions 中定时访问国家公务员局 2026 国考专题公开页面，抓取公告标题，与本地 `cache.json` 对比，**仅在有新增公告时**发送邮件通知。单次运行、无无限循环，适合 6 小时一次的定时任务。

---

## 一、项目结构

```
gk-monitor/
├── monitor.py          # 监控主脚本
├── test_email.py       # 仅用于测试发信的脚本（可选运行）
├── requirements.txt    # Python 依赖
├── .gitignore
├── README.md
└── .github/
    └── workflows/
        └── monitor.yml # 每 6 小时 + 手动触发的 workflow
```

---

## 二、环境与运行（本地）

### 1. 使用虚拟环境（必须）

代码要求在 **Python 虚拟环境** 中运行，不修改系统环境变量、不使用全局安装。

**Windows（PowerShell）：**

```powershell
# 进入项目目录
cd D:\source\gk-monitor

# 创建虚拟环境（推荐 .venv）
python -m venv .venv

# 激活虚拟环境
.\.venv\Scripts\Activate.ps1

# 安装依赖（仅在虚拟环境中）
pip install -r requirements.txt
```

**Windows（CMD）：**

```cmd
cd D:\source\gk-monitor
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

**Linux / macOS：**

```bash
cd /path/to/gk-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置邮箱（环境变量）

**禁止在代码中写死邮箱账号密码。** 必须通过环境变量传入：

| 变量名       | 说明           | 示例（勿写真实密码到文档） |
|-------------|----------------|----------------------------|
| `EMAIL_USER`| 发件邮箱       | `your@qq.com`              |
| `EMAIL_PASS`| 邮箱授权码/密码| 在邮箱服务商处获取         |
| `EMAIL_TO`  | 收件邮箱       | `receiver@example.com`     |

可选（默认 QQ 邮箱）：

- `SMTP_HOST`：SMTP 服务器，默认 `smtp.qq.com`
- `SMTP_PORT`：端口，默认 `587`

**Windows（PowerShell）单次运行示例：**

```powershell
$env:EMAIL_USER = "your@qq.com"
$env:EMAIL_PASS = "你的授权码"
$env:EMAIL_TO = "receiver@example.com"
python monitor.py
```

**Linux / macOS：**

```bash
export EMAIL_USER="your@qq.com"
export EMAIL_PASS="你的授权码"
export EMAIL_TO="receiver@example.com"
python monitor.py
```

不配置上述三个变量时，脚本仍会正常抓取与对比，但**不会发邮件**，只打印“未配置邮箱环境变量...”。

#### 测试发信（验证能否成功收邮件）

项目内提供了 **`test_email.py`**，用于在不跑完整监控的前提下，单独验证邮箱配置是否正确、能否成功发信。

**步骤：**

1. **设置环境变量**（与上面相同，三个必填）  
   - PowerShell 示例（请替换为你的邮箱和授权码）：
     ```powershell
     $env:EMAIL_USER = "your@qq.com"
     $env:EMAIL_PASS = "你的授权码"
     $env:EMAIL_TO   = "your@qq.com"   # 收件人，可填自己
     ```
   - Linux/macOS：
     ```bash
     export EMAIL_USER="your@qq.com"
     export EMAIL_PASS="你的授权码"
     export EMAIL_TO="your@qq.com"
     ```

2. **运行测试脚本**（在项目目录、已激活虚拟环境下）：
   ```bash
   python test_email.py
   ```

3. **看结果**  
   - 若输出 **「测试邮件已发送。请到收件箱（及垃圾箱）查看。」**：说明配置正确，`monitor.py` 在发现新增公告时也能正常发信。  
   - 若报 **SMTP 认证失败**：请检查发件邮箱与授权码；QQ/163 需在邮箱设置里开启 SMTP 并使用「授权码」/「授权密码」，不能使用登录密码。

**常见邮箱 SMTP（可选，不设则默认 QQ）：**

| 邮箱     | SMTP_HOST      | SMTP_PORT | 说明 |
|----------|----------------|-----------|------|
| QQ 邮箱  | smtp.qq.com    | 587       | 默认，需授权码 |
| 163 邮箱 | smtp.163.com   | 587       | 需授权密码     |
| 126 邮箱 | smtp.126.com   | 587       | 需授权密码     |
| 企业邮箱 | 按服务商说明   | 多为 587 或 465 | 若为 465 需在代码中用 SMTP_SSL |

若使用 163/126，可先设置：  
`$env:SMTP_HOST = "smtp.163.com"` 再运行 `python test_email.py`。

#### 如何确认已激活虚拟环境并配置好环境变量

- **看命令行提示**：激活虚拟环境后，提示符前通常会出现 `(.venv)` 或 `(.venv) PS ...`，说明当前 shell 在虚拟环境中。
- **看 Python 路径**：在项目目录下执行 `python -c "import sys; print(sys.prefix)"`，若输出路径包含项目下的 `.venv`（或 `venv`），说明用的是虚拟环境里的 Python。
- **看环境变量**：  
  - PowerShell：`echo $env:EMAIL_USER`、`echo $env:EMAIL_TO`（不显示密码）。  
  - CMD：`echo %EMAIL_USER%`、`echo %EMAIL_TO%`。  
  - Linux/macOS：`echo $EMAIL_USER`、`echo $EMAIL_TO`。  
  有输出且不为空即表示已配置。
- **直接运行脚本**：执行 `python monitor.py` 时，脚本开头会做一次**环境自检**：
  - 若看到 `环境自检: 当前在虚拟环境中运行 ✓`，说明虚拟环境正常。
  - 若看到 `环境自检: 邮箱环境变量已配置（有新增时将发邮件）✓`，说明可以正常发邮件。
  - 若提示“未检测到虚拟环境”或“以下邮箱变量未设置...”，按上面步骤检查激活与配置即可。

### 3. 单次运行

```bash
# 确保已激活虚拟环境并配置好环境变量
python monitor.py
```

- 只访问公开页面：`http://bm.scs.gov.cn/kl2026`
- 使用 User-Agent 与超时，不绕过登录、验证码或安全机制
- 仅抓取公告标题，与同目录下 `cache.json` 对比；有新增时先发邮件，**仅在发送成功后**更新缓存

---

## 三、GitHub 上传与配置

### 1. 初始化 Git 并上传

在项目根目录执行（按需修改远程地址）：

```bash
git init
git add .
git commit -m "feat: 2026国考公告监控"
git branch -M main
git remote add origin https://github.com/你的用户名/gk-monitor.git
git push -u origin main
```

若仓库已存在且仅需推送：

```bash
git add .
git commit -m "feat: 2026国考公告监控"
git push
```

### 2. 配置 GitHub Actions 用到的 Secrets

邮箱信息通过 **Secrets** 传入，不写进代码与仓库。

1. 打开仓库：`https://github.com/你的用户名/gk-monitor`
2. 进入 **Settings → Secrets and variables → Actions**
3. 点击 **New repository secret**，先添加必填三项：

| Name         | Value           | 说明     |
|-------------|-----------------|----------|
| `EMAIL_USER`| 发件邮箱        | 必填     |
| `EMAIL_PASS`| 邮箱授权码/密码 | 必填     |
| `EMAIL_TO`  | 收件邮箱        | 必填     |

4. **可选项**（非 QQ 邮箱时再补）：  
   若使用 **QQ 邮箱**，可不添加下面两项，workflow 会使用默认 `smtp.qq.com:587`。  
   若使用 **163 / 126 / 企业邮箱** 等，再点 **New repository secret** 补两条：

| Name        | Value           | 说明 |
|-------------|-----------------|------|
| `SMTP_HOST` | 如 `smtp.163.com` | 可选，不填则用 `smtp.qq.com` |
| `SMTP_PORT` | 如 `587`         | 可选，不填则用 `587` |

5. **监控的页面不对、一直收不到「发现新增公告」时**，可配置 **公告列表真实页面** 的 URL：  
   默认脚本抓的是专题入口页（可能需在浏览器里再点一次才到公告列表），若入口页没有公告列表的 HTML，就永远解析不到新公告。  
   **获取方法**：浏览器打开邮件里的链接 → **再点一次**进入能看到「招考公告/通知公告」列表的那一页 → 复制**地址栏完整 URL**。  
   在 Secrets 里 **New repository secret** → Name 填 `MONITOR_URL`，Secret 填刚复制的 URL（如 `http://www.scs.gov.cn/...` 或 `http://bm.scs.gov.cn/...`）→ 保存。  
   配置后脚本会**直接抓该页面**，不再走入口+跳转，才有机会解析到公告标题并发出「发现新增公告」邮件。

**操作步骤**：在 **Actions** 的 Secrets 页 → 点 **New repository secret** → **Name** 填 `SMTP_HOST`，**Secret** 填你的 SMTP 服务器（如 `smtp.163.com`）→ 保存；再新建一个，Name 填 `SMTP_PORT`，Secret 填 `587`（或服务商要求的端口）→ 保存。

保存后，workflow 中通过 `secrets.EMAIL_USER` 等使用，未设置的 `SMTP_HOST` / `SMTP_PORT` 在脚本中会使用默认值，无需在 YAML 里写明文。

### 3. 定时与手动运行

- **定时**：每 6 小时自动运行（cron: `0 */6 * * *`，UTC），约对应北京时间 8:00、14:00、20:00、02:00。
- **手动**：仓库页 **Actions → 选择「2026国考公告监控」→ Run workflow**。

运行使用 **Python 3.11**，在 Actions 中创建虚拟环境并执行 `monitor.py`；`cache.json` 通过 `actions/cache` 在多次运行间持久化。

#### GitHub 云端运行：不依赖你电脑开关机

- Workflow 使用 **`runs-on: ubuntu-latest`**，即在 **GitHub 提供的云端虚拟机** 上执行，和你本机是否开机、是否联网无关。
- 只要仓库在 GitHub 上、Actions 已启用，到点就会在云端跑监控并（有新增时）发邮件，**电脑可以一直关机**。
- **建议**：在仓库 **Actions** 页确认该 workflow 未被禁用（若列表里显示 “Enable workflow” 则点一次启用）。
- **注意**：若仓库超过约 60 天没有任何提交或 PR 等“活动”，GitHub 可能自动禁用定时任务；届时到 **Actions → 该 workflow → Enable workflow** 重新启用即可，或在这之前随便做一次提交/PR 保持活跃。

---

## 四、依赖说明

- **requests**：发 HTTP 请求，带超时与 User-Agent
- **beautifulsoup4**：解析专题页 HTML，提取公告标题

邮件使用标准库 `smtplib` + `ssl`，无需额外包。

---

## 五、安全与合规

- 不写死邮箱账号密码，仅通过环境变量 / GitHub Secrets 读取
- 仅访问公开专题页，不绕过任何登录、验证码或安全机制
- 低频访问（建议 6 小时），单次运行无 `while True` 循环
- 仅抓取公告标题，用于本地对比与通知

---

## 六、文件说明

| 文件 | 说明 |
|------|------|
| `monitor.py` | 抓取专题页、解析标题、读/写 `cache.json`、对比并可选发邮件 |
| `requirements.txt` | `requests`、`beautifulsoup4` 及版本约束 |
| `.gitignore` | 忽略 `venv`、`__pycache__`、`.env`、`cache.json`（可选）等 |
| `.github/workflows/monitor.yml` | 每 6 小时 + 手动触发，Python 3.11，使用 Secrets 与 cache |

---

## 七、常见问题

### 手动运行 workflow 后没收到邮件

按下面顺序排查：

**1. 看这次运行的日志（最重要）**

- 打开仓库 **Actions** → 点进**最近一次**「2026国考公告监控」运行（如 #2、#3）
- 点下面的 **monitor** 这一项（绿色勾那一行）
- 在日志里搜索或顺次看：
  - 若出现 **「环境自检: 以下邮箱变量未设置」** → 说明 GitHub Secrets 没配全，收不到邮件是正常的。请到 **Settings → Secrets and variables → Actions** 补全 `EMAIL_USER`、`EMAIL_PASS`、`EMAIL_TO`。
  - 若出现 **「未配置邮箱环境变量 EMAIL_USER / EMAIL_PASS / EMAIL_TO，跳过发送邮件」** → 同上，Secrets 未配置或未生效（例如刚加的 Secrets 要重新跑一次 workflow）。
  - 若出现 **「SMTP 认证失败」** → 发件邮箱或授权码错误。QQ 邮箱必须用「授权码」而不是登录密码；163/126 用「授权密码」。可在本地用 `python test_email.py` 先验证。
  - 若出现 **「邮件已发送。」** → 脚本侧已发信，请到**收件箱、垃圾邮件、订阅邮件**里找主题带「2026国考」的邮件。

**2. 确认 Secrets 已填且生效**

- **Settings → Secrets and variables → Actions** 里必须有：`EMAIL_USER`、`EMAIL_PASS`、`EMAIL_TO`（Name 必须一致，区分大小写）。
- 修改 Secrets 后，需要**再点一次 Run workflow** 才会用新值；历史那次运行用的还是旧配置。

**3. 检查垃圾箱**

- 发信方是 GitHub 云端 IP，部分邮箱会把首封信进垃圾箱。请查「垃圾邮件」「订阅/推广」等文件夹。

**4. 发件邮箱限制（QQ/163 等）**

- 从 GitHub 海外服务器发信，个别邮箱会拦截或限制。若日志里已是「邮件已发送」但始终收不到，可尝试：
  - 换一个邮箱（如 Gmail、Outlook）做发件/收件测试；
  - 或在 QQ 邮箱网页版「设置 → 账户」里查看是否有「异地登录」「SMTP 拒绝」等安全提示，必要时临时放宽后再试一次 Run workflow。

---

### 网站有新公告但邮件显示「无新增」— 原因与解决办法

**可能原因：**

| 原因 | 说明 |
|------|------|
| **1. 抓错页面（最常见）** | 未配置 `MONITOR_URL` 时，脚本抓的是专题**入口页**（如 bm.scs.gov.cn/kl2026 或 gkIndex.html）。公告公示列表往往在「再点一次」后的**子页面**，入口页的 HTML 里没有列表内容，解析结果一直是 0 条或很少，和缓存一比就没有“新增”。 |
| **2. 列表由前端 JS 加载** | 很多政府站用 JavaScript 请求接口再渲染列表，首屏 HTML 里根本没有公告条目。脚本只请求一次 HTML、不执行 JS，所以拿不到动态加载的内容。 |
| **3. MONITOR_URL 配错** | 若配的是「公告公示」的入口而不是**真正展示列表的那一页**（或该页仍是 JS 渲染），同样解析不到新公告。 |
| **4. 解析规则过严** | 脚本只保留含「公告/通知/招考/公示」等关键词或长度 8～150 的链接文本，若新公告标题不符合会被过滤（已放宽并加入「公示」）。 |

**解决办法：**

1. **先看 Actions 日志里「本次共解析到 N 条」**  
   若 **N = 0**：说明当前抓到的页面里没有解析到任何公告链接，多半是**抓错页**或**页面是 JS 渲染**。  
   若 **N > 0**：下面会打印前 10 条标题，可核对是否包含「公告公示」里的条目；若没有，说明 MONITOR_URL 不对或需放宽解析。

2. **配置 MONITOR_URL 为「公告列表」真实页面**  
   浏览器打开官网 → 点进「公告公示」/「招考公告」直到**能看到昨天新增的那条**的列表页 → **复制地址栏完整 URL** → 在 GitHub **Secrets** 里添加 `MONITOR_URL` = 该 URL，或填到 `monitor.py` 的 `DEFAULT_MONITOR_URL`。  
   保存后重新跑一次 workflow，看日志里「本次共解析到」是否大于 0 且列表中是否出现新公告。

3. **若该列表页是 JS 渲染（配置了正确 URL 仍解析到 0 条）**  
   - **办法 A**：浏览器 F12 → Network → 刷新列表页，找 XHR/Fetch 里返回列表数据的**接口 URL**（多为 JSON）。若该接口无需登录即可访问，可在脚本里增加「请求该接口并解析 JSON」的逻辑（需改代码或后续提供配置项）。  
   - **办法 B**：使用带浏览器的方案（如 Playwright）在服务器上打开页面、等 JS 执行完再抓 HTML，依赖和配置较重，可作备选。

4. **确认后删除或更新缓存（可选）**  
   若之前一直抓错页，cache 里可能是空或旧数据。配置对 MONITOR_URL 后，第一次运行可能会把当前所有条目当「新增」发一封邮件，属正常；之后就会按真实新增对比。

---

- **首次运行就发邮件**：首次无 `cache.json`，当前抓到的标题都会视为“新增”，属正常；之后会按「有新增 / 无新增」各发对应邮件。
- **一直只有「无新增」、从没收到「发现新增公告」**：多半是监控的页面不对（抓的是入口/跳转页，公告在“再点一次”后的页面）。请按上面「配置 Secrets」第 5 步，配置 **MONITOR_URL** 为「再点一次」后那页的完整地址。
- **想换 SMTP**：设置环境变量或 Secrets：`SMTP_HOST`、`SMTP_PORT`（如 465 需在代码中改用 SMTP_SSL，当前为 587 + STARTTLS）。

如需调整监控频率，只需修改 `.github/workflows/monitor.yml` 中的 `cron` 表达式。
