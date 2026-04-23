# 国家公务员局 2026 国考公告监控（整页截图 + 视觉对比版）

在本地或 GitHub Actions 中定时打开国家公务员局 2026 国考专题页面，**用无头浏览器（Playwright）等页面 JS 渲染完成**后：

1. 提取整页的公告条目（标题、日期、链接）
2. 对页面做 **full page 全页截图**
3. 与上次运行的截图做**像素级视觉对比**，生成**高亮差异图**并算出变化率（仿 [Visualping](https://visualping.io/) 的视觉比对方式）
4. 与本地 `cache.json` 对比，检测**新增 / 删除**的公告
5. 支持**关键词检测**（`KEYWORDS` 环境变量，命中时邮件顶部会高亮提醒）
6. **每次运行都发送一封 HTML 邮件**，不论有没有变化。邮件里会：
   - 一眼看到变化统计：**页面条目 / 新增 / 删除 / 视觉变化率 / 耗时**
   - 列出新增、删除的公告条目（带链接）
   - 并排展示 **上次截图 · 本次截图 · 差异高亮图** 三栏

单次运行、无无限循环，适合每 6 小时跑一次的定时任务。

---

## 一、三条核心需求与实现

| 需求 | 实现方式 |
|------|----------|
| ① 能监控到页面变化，有新公告时清楚列出 | 渲染完成后提取所有 `<a>` 条目，按 `(title, href)` 作主键与 `cache.json` 比对，新增用绿色、删除用红色在邮件里列出 |
| ② 每 6 小时监控一次 + **无论是否变化都发邮件**（带截图 + 新公告列表） | GitHub Actions cron `0 */6 * * *`；脚本在流程末尾**无条件调用 `send_email_report()`**，邮件里一定包含本次截图和条目变化情况 |
| ③ 仿 Visualping 做提升 | 像素差异对比 + 红框高亮变化区域 + 变化百分比 + 三栏图片对比 + 关键词命中提醒 |

---

## 二、项目结构

```
gk-monitor/
├── monitor.py            # 监控主脚本（Playwright + 视觉对比 + 每次都发信）
├── test_email.py         # 发信测试脚本
├── requirements.txt      # Python 依赖（playwright + Pillow）
├── .gitignore
├── README.md
└── .github/
    └── workflows/
        └── monitor.yml   # 每 6 小时 + 手动触发的 workflow
```

运行过程中会在项目目录生成：

| 文件              | 作用                                                                  |
|-------------------|-----------------------------------------------------------------------|
| `cache.json`      | 上次抓到的公告条目快照，用于检测新增 / 删除                            |
| `page.png`        | 本次整页截图（会内嵌到邮件里）                                         |
| `page_prev.png`   | 上次运行保存下来的截图，作为下次视觉对比的基准                         |
| `page_diff.png`   | 本次与上次截图的像素差异高亮图（首次运行没有）                         |

---

## 三、本地运行

### 1. 创建虚拟环境并安装依赖

**Windows (PowerShell)：**

```powershell
cd D:\source\gk-monitor
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
```

**Linux / macOS：**

```bash
cd /path/to/gk-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install --with-deps chromium
```

### 2. 配置环境变量

**禁止在代码里写死邮箱账号密码。** 必须通过环境变量传入：

| 变量名       | 必填 | 说明             | 示例                     |
|--------------|:---:|------------------|--------------------------|
| `EMAIL_USER` | ✅  | 发件邮箱          | `your@qq.com`            |
| `EMAIL_PASS` | ✅  | 邮箱授权码/密码   | 到邮箱服务商后台获取      |
| `EMAIL_TO`   | ✅  | 收件邮箱          | `receiver@example.com`   |
| `SMTP_HOST`  |     | SMTP 服务器       | 默认 `smtp.qq.com`       |
| `SMTP_PORT`  |     | 端口；`465` 自动走 SSL，其余走 STARTTLS | 默认 `587` |
| `MONITOR_URL`|     | 要监控的页面 URL  | 默认 `http://bm.scs.gov.cn/kl2026` |
| `KEYWORDS`   |     | 关键词列表，逗号分隔；命中时邮件顶部会高亮提醒 | 如 `报名,职位表,大纲` |

**Windows (PowerShell) 示例：**

```powershell
$env:EMAIL_USER = "your@qq.com"
$env:EMAIL_PASS = "你的授权码"
$env:EMAIL_TO   = "receiver@example.com"
$env:KEYWORDS   = "报名,职位表,大纲,笔试"
python monitor.py
```

**Linux / macOS：**

```bash
export EMAIL_USER="your@qq.com"
export EMAIL_PASS="你的授权码"
export EMAIL_TO="receiver@example.com"
export KEYWORDS="报名,职位表,大纲,笔试"
python monitor.py
```

不配置邮箱变量时脚本仍会抓页面和对比，但**不会发邮件**（只打印提示）。

### 3. 单次运行

```bash
python monitor.py
```

脚本行为：

- 打开 `MONITOR_URL`（默认 `http://bm.scs.gov.cn/kl2026`），等 JS 渲染完成
- 解析页面中所有公告条目（标题 + 最近一个日期 + 链接）
- 生成 `page.png` 整页截图
- 如果存在 `page_prev.png`，做**像素级视觉对比**，生成 `page_diff.png` 并计算变化率
- 与 `cache.json` 对比新增 / 删除；同时对条目做关键词匹配
- **无论是否有变化，每次都发送一份完整报告邮件**（首次运行会标记为「初始化」）
- 写回 `cache.json`，并把本次截图拷贝为 `page_prev.png` 留作下次基准

### 4. 验证能否收邮件（可选）

项目内提供 `test_email.py`，用于只验证发信通道：

```bash
python monitor.py       # 先跑一次，生成 page.png
python test_email.py    # 再发一封测试邮件（如有 page.png 会附上内嵌截图）
```

---

## 四、GitHub Actions（云端定时运行）

### 1. 上传代码

```bash
git add .
git commit -m "feat: 视觉对比 + 每次运行都发邮件（仿 Visualping）"
git push
```

### 2. 配置 Secrets

仓库 → **Settings → Secrets and variables → Actions → New repository secret**：

| Name         | 必填 | Value                                   |
|--------------|:---:|-----------------------------------------|
| `EMAIL_USER` | ✅  | 发件邮箱                                  |
| `EMAIL_PASS` | ✅  | 邮箱授权码/密码                           |
| `EMAIL_TO`   | ✅  | 收件邮箱                                  |
| `SMTP_HOST`  |     | 如 `smtp.163.com`（默认 `smtp.qq.com`） |
| `SMTP_PORT`  |     | 如 `587` 或 `465`（默认 `587`）         |
| `MONITOR_URL`|     | 想监控的完整 URL                        |
| `KEYWORDS`   |     | 关键词列表（逗号分隔），命中时高亮提醒    |

### 3. 定时与手动运行

- **定时**：每 6 小时自动运行（cron `0 */6 * * *` UTC，约对应北京时间 8:00 / 14:00 / 20:00 / 02:00）
- **手动**：仓库 **Actions → 2026国考公告监控 → Run workflow**

Workflow 做的事情：

1. 安装 **fonts-noto-cjk**，让截图里的汉字正确显示
2. 创建 venv，`pip install -r requirements.txt`（含 Pillow 做视觉对比）
3. `playwright install --with-deps chromium` 安装浏览器
4. 从 `actions/cache` 恢复 **`cache.json` + `page_prev.png`**（关键：没有上次截图就没法做视觉对比）
5. 运行 `monitor.py`；跑完再保存这两份缓存
6. 把 `page.png`、`page_prev.png`、`page_diff.png` 作为 artifact 上传（保留 14 天）

---

## 五、邮件长什么样

每封邮件都包含四个区块：

1. **顶部关键词高亮条**（仅命中时出现）
   > 🔔 关键词命中提醒：`报名 · 2 条`  `职位表 · 1 条`

2. **统计条**
   > 页面条目 / 新增 / 删除 / 视觉变化率 / 本次耗时 / 检测时间

3. **变化列表**
   - 🟢 新增 N 条公告（带链接 + 日期）
   - 🔴 删除 N 条公告
   - 若都没有：显示「📭 本次未检测到公告条目变化；附上本次截图供参考」

4. **页面快照三栏**
   > 上次截图 · 本次截图 · 视觉差异高亮图（红框圈出变化区域）

首次运行（没 `cache.json` 也没 `page_prev.png`）时：

- 不会把当前条目全部当「新增」轰炸
- 发一封标题为 **【网页监控·初始化】** 的邮件确认通道可用
- 之后每次运行都是完整报告

---

## 六、工作原理

### 解析规则

在页面渲染完成后遍历所有 `<a>` 标签：

- 文本长度 6–200 字符
- 排除导航/功能类链接（"首页 / 登录 / 下载 app / 版权 / ICP" 等）
- 向上 5 层查找最近的日期，形如 `2026-04-20` / `2026/04/20` / `04-20` / `2026年4月20日`

每个条目用 `(title, href)` 作为唯一键；`current − cached` 为新增，`cached − current` 为删除。

### 视觉对比（Visualping 风格）

1. 把上次截图 `page_prev.png` 和本次截图 `page.png` 补齐到相同尺寸
2. 像素级求差 `ImageChops.difference`
3. 用阈值 `VISUAL_DIFF_THRESHOLD=30` 做二值化，过滤字体抗锯齿等噪声
4. 用 `MaxFilter` 膨胀一下，让小变化连成块
5. 统计变化像素占比 → `change_ratio`
6. 在本次截图上叠加半透明红色遮罩 + 外接红框 → 生成 `page_diff.png`

小于 `VISUAL_DIFF_NOISE_FLOOR=0.1%` 的变化率会被视为"几乎无视觉变化"——邮件里仍会显示，但不强调。

### 关键词检测

- 支持多个关键词，用 `,`、`，`、`;`、`；` 或换行分隔
- 对本次抓到的每条公告标题做**不区分大小写**的子串匹配
- 命中时邮件主题变为 **【关键词命中】xxx**，并在顶部显示关键词命中条数

---

## 七、安全与合规

- 邮箱凭据仅从环境变量 / GitHub Secrets 读取，不落仓库
- 仅访问公开专题页，使用普通 UA，不绕过任何登录 / 验证码 / 安全机制
- 低频访问（6 小时一次），单次运行无 `while True` 循环
- 抓到的公告标题 / 日期 / 链接仅用于本地对比与个人通知

---

## 八、常见问题

### 手动跑了 workflow 却没收到邮件

1. 打开 **Actions → 最近那次运行 → monitor**，搜关键字：
   - `环境自检: 以下邮箱变量未设置` → 去 Secrets 里补齐 `EMAIL_USER / EMAIL_PASS / EMAIL_TO`
   - `SMTP 认证失败` → 发件邮箱授权码错误。QQ 用「授权码」不是登录密码；163/126 用「授权密码」
   - `邮件已发送。` → 脚本侧成功，优先去**收件箱、垃圾邮件、订阅推广**文件夹里找
2. 改完 Secrets 后**必须再点一次 Run workflow**
3. 云端 IP 可能被部分邮箱拦截，可先在本地跑 `python test_email.py` 验证通道

### 邮件里第一次没有"上次截图"和"差异图"

正常。首次运行（云端或本地）还没有 `page_prev.png`，所以只能展示本次截图。**从第二次运行起**会出现上次截图 + 差异高亮图三栏对比。

### 视觉变化率总是偏高 / 偏低

- 调大 `monitor.py` 里的 `VISUAL_DIFF_THRESHOLD`（默认 30）可以过滤更多字体抗锯齿噪声
- 调小 `VISUAL_DIFF_NOISE_FLOOR`（默认 0.001，即 0.1%）让"几乎无变化"的阈值更敏感

### 想更换要监控的页面

- 在 Secrets 里加 `MONITOR_URL`，填新 URL 即可，无需改代码
- 本地测试：`$env:MONITOR_URL = "..."` 然后 `python monitor.py`
