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

- **收不到邮件**：检查 Secrets/环境变量是否填全、授权码是否正确（QQ 邮箱需开启 SMTP 并使用授权码）。
- **首次运行就发邮件**：首次无 `cache.json`，当前抓到的标题都会视为“新增”，属正常；之后仅新增才会触发邮件。
- **想换 SMTP**：设置环境变量或 Secrets：`SMTP_HOST`、`SMTP_PORT`（如 465 需在代码中改用 SMTP_SSL，当前为 587 + STARTTLS）。

如需调整监控频率，只需修改 `.github/workflows/monitor.yml` 中的 `cron` 表达式。
