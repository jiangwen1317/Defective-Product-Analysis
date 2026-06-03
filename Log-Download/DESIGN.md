# LVTS 日志定时下载器 — 设计方案文档

## 1. 项目概述

### 1.1 项目背景

LVTS（Log Verification Test System）是一个内部日志验证测试系统，用户需要定期从该系统下载任务日志文件用于缺陷产品分析。手动操作浏览器逐个下载效率低下且容易遗漏，因此需要一个自动化工具来完成这一重复性工作。

### 1.2 核心目标

- 自动登录 LVTS 服务器并完成身份验证
- 扫描任务列表，识别所有包含可下载日志的任务
- 自动触发下载操作并保存文件到指定目录
- 通过去重机制避免重复下载已处理的任务
- 支持定时循环执行，实现无人值守运行

### 1.3 使用场景约束

| 约束项 | 说明 |
|--------|------|
| 浏览器结构 | 已固定，不会改变 |
| 使用人数 | 仅个人使用，无多用户场景 |
| 安全要求 | 明文密码存储可接受 |
| 运行环境 | Windows 系统，本地执行 |

---

## 2. 技术选型

### 2.1 自动化引擎：Playwright

**选择理由：**

| 对比维度 | Playwright | Selenium | Requests + BeautifulSoup |
|----------|-----------|----------|--------------------------|
| 页面交互能力 | 完整浏览器控制 | 完整浏览器控制 | 仅 HTTP 请求 |
| 右键菜单支持 | 原生 `button="right"` | 需 Actions 链 | 不支持 |
| 文件下载拦截 | 原生 `expect_download()` | 配置复杂 | 不适用 |
| 等待机制 | 自动等待 + 丰富 API | 显式等待较繁琐 | 不适用 |
| 无头模式 | 开箱即用 | 需额外配置 | 不适用 |
| 安装复杂度 | `pip install` + `playwright install` | `pip install` + WebDriver | 仅 `pip install` |

**关键决策点：** LVTS 系统的日志下载依赖浏览器右键上下文菜单（iView Dropdown 组件），这要求自动化工具必须具备完整的浏览器 GUI 交互能力。纯 HTTP 方案（Requests）无法模拟右键菜单行为，因此必须选择浏览器自动化工具。Playwright 在 API 设计、等待机制、下载拦截方面优于 Selenium。

### 2.2 浏览器引擎：Chromium（Chrome 通道）

```python
self.browser = self.playwright.chromium.launch(
    headless=headless,
    channel="chrome",           # 使用系统安装的 Chrome
    args=["--no-sandbox", "--disable-dev-shm-usage"],
)
```

**选择理由：**
- 使用系统已安装的 Chrome 浏览器（`channel="chrome"`），避免 Playwright 自带 Chromium 的二进制下载
- `--no-sandbox`：在 Windows 本地环境中避免沙箱权限问题
- `--disable-dev-shm-usage`：防止共享内存不足导致的浏览器崩溃

### 2.3 编程语言：Python 3

- 团队已熟悉 Python 生态
- Playwright Python 绑定功能完整
- 标准库（`json`、`logging`、`os`、`re`、`argparse`）即可满足所有辅助需求，无额外依赖

### 2.4 依赖管理

**requirements.txt：**
```
playwright>=1.40.0
```

仅一个外部依赖，保持最小化。版本号 `>=1.40.0` 确保 `expect_download()`、`locator()` 等核心 API 可用。

---

## 3. 程序整体架构

### 3.1 模块结构

```
log_downloader.py
├── LoginStatus          # 登录状态枚举
├── Selectors            # UI 选择器常量集合
├── Timeout              # 超时时间常量集合
├── LogDownloader        # 核心下载器类
│   ├── 配置管理         # _load_config, _validate_config
│   ├── 日志设置         # _setup_logging
│   ├── 浏览器生命周期   # _init_browser, _close_browser
│   ├── 身份验证         # login, _wait_for_login_success
│   ├── 页面导航         # navigate_to_task_list, _is_task_list_page
│   ├── 任务扫描         # scan_downloadable_tasks, _extract_task_id, _extract_task_name
│   ├── 任务下载         # download_task_log, _find_task_row
│   ├── UI 交互辅助      # _close_modals, _handle_confirm_dialog
│   ├── 文件处理         # verify_file_integrity, _get_unique_filepath, _sanitize_filename
│   ├── 去重管理         # load_downloaded_tasks, save_downloaded_task, _extract_task_id_from_filename
│   ├── 过滤与重试       # filter_pending_tasks, _download_with_retry
│   ├── 调度执行         # run_single_cycle, run_scheduler
│   └── 调试支持         # _save_screenshot
└── main()               # 命令行入口函数
```

### 3.2 类职责说明

#### LoginStatus — 登录状态枚举

```python
class LoginStatus:
    SUCCESS = "success"    # 登录成功
    FAILED = "failed"      # 登录失败
    TIMEOUT = "timeout"    # 等待超时
    UNKNOWN = "unknown"    # 未知状态
```

使用字符串常量而非 `enum.Enum`，原因是项目规模小、无需严格枚举约束，字符串常量足够清晰且零依赖。

#### Selectors — UI 选择器常量

集中管理所有 Playwright CSS 选择器，按功能分组：

| 分组 | 常量名 | 用途 |
|------|--------|------|
| 任务表格 | `TABLE_ROWS` | 定位任务列表中的所有行 |
| 下载按钮 | `DOWNLOAD_BUTTON` | 识别行内的下载按钮 |
| 登录表单 | `USERNAME_INPUT`、`PASSWORD_INPUT`、`LOGIN_BUTTON` | 定位登录表单元素 |
| 登录验证 | `LOGIN_SUCCESS` | 登录成功后的页面特征元素 |
| 页面验证 | `TASK_LIST_PAGE` | 任务列表页面的特征元素 |
| 右键菜单 | `DOWNLOAD_MENU` | iView Dropdown 中的"下载日志"菜单项 |
| 对话框 | `CONFIRM_BUTTON` | 确认对话框的确定按钮 |

**设计意图：** 将选择器从业务逻辑中抽离为常量，当页面结构变化时只需修改一处。选择器以列表形式存储，按优先级从高到低排列，遍历时找到第一个匹配即停止。

#### Timeout — 超时时间常量

```python
class Timeout:
    FORM_WAIT = 10_000      # 等待表单加载（10 秒）
    LOGIN_WAIT = 15_000     # 等待登录成功（15 秒）
    NETWORK_IDLE = 10_000   # 等待网络空闲（10 秒）
    MENU_RENDER = 3_000     # 等待菜单渲染（3 秒）
    DOWNLOAD_WAIT = 60_000  # 等待下载完成（60 秒）
    UI_RENDER = 500         # UI 渲染等待（0.5 秒）
    CHECKBOX_UPDATE = 300   # 复选框更新等待（0.3 秒）
```

所有超时值统一管理，单位为毫秒，与 Playwright API 保持一致。

#### LogDownloader — 核心下载器

程序的主类，封装了完整的下载流程。以下按功能模块逐一说明。

---

## 4. 核心功能实现详解

### 4.1 配置管理

#### 配置文件结构（config.json）

```json
{
  "lvts_server": {
    "url": "http://10.2.3.145/taskList/1/4654",
    "username": "jiongwen.jiang",
    "password": "JIOng1378#"
  },
  "download": {
    "directory": "D:/BackupFiles/jiongwen.jiang/Desktop/CESHI"
  }
}
```

#### 加载流程

```
_load_config(config_path)
    │
    ├── 1. 检查文件是否存在 → FileNotFoundError
    ├── 2. 解析 JSON → ValueError（格式错误）
    └── 3. _validate_config() 验证必需字段
            │
            ├── lvts_server.url        （必需）
            ├── lvts_server.username   （必需）
            ├── lvts_server.password   （必需）
            └── download.directory     （必需）
```

**设计决策：**
- 采用「加载 + 验证」两步模式，先确保文件可读，再确保内容完整
- 必需字段缺失时抛出 `ValueError` 并列出所有缺失字段（而非遇到第一个就报错），方便用户一次性修复
- 支持相对路径和绝对路径：相对路径以脚本所在目录为基准解析

### 4.2 浏览器生命周期管理

#### 初始化流程（`_init_browser`）

```
_init_browser(headless)
    │
    ├── 1. sync_playwright().start()    → 启动 Playwright 进程
    ├── 2. chromium.launch()            → 启动 Chrome 浏览器
    ├── 3. browser.new_context()        → 创建浏览器上下文
    │       ├── accept_downloads=True   → 启用文件下载拦截
    │       └── viewport=1920x1080      → 固定窗口大小
    ├── 4. context.set_default_timeout(60000) → 全局超时 60 秒
    └── 5. context.new_page()           → 创建页面实例
```

**关键设计：**
- `accept_downloads=True`：这是 Playwright 拦截文件下载的前提条件。未设置时，`expect_download()` 无法捕获下载事件
- 固定 viewport 为 1920×1080：确保页面元素布局一致，避免因窗口大小不同导致选择器失效
- 全局默认超时 60 秒：为网络慢的情况提供兜底保护

#### 关闭流程（`_close_browser`）

```
_close_browser()
    │
    ├── 1. browser.close()    → 关闭浏览器（try/except 防止异常）
    ├── 2. playwright.stop()  → 停止 Playwright 进程
    └── 3. 重置所有引用为 None → 释放内存，确保下次初始化干净
```

**设计决策：** 浏览器和 Playwright 的关闭分别包裹在独立的 try/except 中，确保一个失败不影响另一个。这在 `finally` 块中调用，保证异常情况下也能释放资源。

### 4.3 登录认证流程

#### 登录主流程（`login`）

```
login()
    │
    ├── 1. page.goto(url, wait_until="networkidle")
    │       └── 等待页面完全加载（无网络请求 500ms）
    │
    ├── 2. page.wait_for_selector("input", timeout=10s)
    │       └── 确保登录表单已渲染
    │
    ├── 3. 填写用户名
    │       └── locator(CSS选择器列表) → count() > 0 → first.fill()
    │
    ├── 4. 填写密码
    │       └── locator('input[type="password"]') → first.fill()
    │
    ├── 5. 点击登录按钮
    │       └── 遍历选择器列表 → 找到第一个存在的按钮 → click()
    │
    └── 6. _wait_for_login_success()
            └── 多策略验证登录结果
```

#### 登录成功验证策略（`_wait_for_login_success`）

这是整个登录流程中最复杂的部分，采用**四层递进验证**策略：

```
_wait_for_login_success(timeout=15000)
    │
    │  总超时限制 = timeout × 1.5 = 22.5 秒
    │
    ├── 步骤 1: 等待登录按钮消失（必要条件）
    │       └── login_button.wait_for(state="hidden")
    │       └── 如果按钮仍可见 → 返回 FAILED
    │
    ├── 步骤 2: 遍历成功特征选择器（充分条件）
    │       └── 对每个选择器：
    │           ├── count() == 0 → 跳过（元素不存在）
    │           └── count() > 0 → wait_for(state="visible")
    │               ├── 成功 → 返回 SUCCESS
    │               └── 超时 → 检查下一个选择器
    │
    ├── 步骤 3: URL 检测
    │       └── 检查 URL 是否包含 /login, /signin, /enter
    │       └── 不含这些 → 视为离开登录页 → 返回 SUCCESS
    │
    └── 步骤 4: 快速扫描（不再等待，只检查当前状态）
            └── 遍历成功特征选择器
            └── count() > 0 && is_visible() → 返回 SUCCESS
            └── 都不满足 → 返回 TIMEOUT
```

**设计意图：**
- **步骤 1（必要条件）**：登录按钮消失是登录成功的最基本信号。如果按钮仍在，说明登录大概率失败
- **步骤 2（充分条件）**：遍历多种页面特征元素（表格行、用户信息、侧边栏等），任一出现即可确认成功
- **步骤 3（URL 检测）**：某些系统登录成功后会跳转 URL，可作为辅助判断
- **步骤 4（快速扫描）**：不再等待，只检查元素是否已经存在且可见，捕获步骤 2 等待期间可能已渲染完成的元素

**超时管理：** 每个步骤都检查已用时间，确保不超过总超时限制（22.5 秒），避免无限等待。

### 4.4 页面导航验证（`navigate_to_task_list`）

```
navigate_to_task_list()
    │
    ├── 1. wait_for_load_state("networkidle", timeout=10s)
    │       └── 等待页面网络请求稳定
    │
    ├── 2. wait_for_timeout(500ms)
    │       └── 给 UI 渲染留出短暂时间
    │
    └── 3. _is_task_list_page() 验证
            ├── 检测到特征元素 → 返回 True
            └── 未检测到 → 记录 error 日志 + 截图 → 返回 False
```

**说明：** 由于 LVTS 系统登录后 URL 已经是任务列表页面，此方法的核心价值是等待页面完全加载并验证页面内容，而非执行实际的页面跳转。

### 4.5 任务扫描逻辑

#### 扫描流程（`scan_downloadable_tasks`）

```
scan_downloadable_tasks()
    │
    ├── 1. 查找所有任务行
    │       └── 遍历 Selectors.TABLE_ROWS（按优先级）
    │       └── 第一个匹配的选择器 → 获取所有行
    │
    └── 2. 逐行分析
            └── 对每一行：
                ├── 遍历 Selectors.DOWNLOAD_BUTTON
                │   └── count() > 0 && is_visible() → 有下载按钮
                │
                ├── 有下载按钮 → 提取任务信息
                │   ├── _extract_task_id(row)     → 任务 ID
                │   └── _extract_task_name(row)   → 任务名称
                │
                └── 无下载按钮 → 跳过该行
```

#### 任务 ID 提取策略（`_extract_task_id`）

```
_extract_task_id(row, row_index)
    │
    ├── 1. 尝试 td:nth-child(2)（第二列）
    │       └── 内容为纯数字 → 作为任务 ID
    │
    ├── 2. 尝试 td:nth-child(1)（第一列）
    │       └── 内容为纯数字 → 作为任务 ID
    │
    └── 3. 兜底方案
            └── 返回 "task_row_{row_index}"
```

**设计依据：** 根据 LVTS 实际页面结构，任务 ID 位于表格第二列（第一列通常是复选框列）。`isdigit()` 验证确保提取的是数字 ID 而非其他文本。

#### 任务名称提取策略（`_extract_task_name`）

与 ID 提取类似，按优先级尝试第三列和第四列，提取非空文本作为任务名称。所有提取失败时以任务 ID 作为名称。

### 4.6 下载流程详解

#### 单任务下载流程（`download_task_log`）

这是整个程序最核心也最复杂的方法，包含四个有序步骤：

```
download_task_log(task)
    │
    ├── 步骤 0: 定位行元素
    │       └── _find_task_row(task_id)
    │           └── 遍历所有行 → 比较 td:nth-child(2) 的文本
    │           └── 匹配 → 返回行元素
    │           └── 未找到 → 截图 + 返回 False
    │
    ├── 步骤 1: 关闭弹窗（_close_modals）
    │       └── 目的：确保右键菜单不被弹窗遮挡
    │
    ├── 步骤 2: 勾选复选框
    │       └── 方案 A: input[type='checkbox'] → click()
    │       └── 方案 B: 点击 td:first-child（后备）
    │       └── 等待 300ms 让 UI 更新
    │
    ├── 步骤 3: 右键点击
    │       └── row.click(button="right")
    │       └── 等待菜单出现（wait_for visible, 3s）
    │       └── 失败 → 固定等待 1s 作为后备
    │       └── 截图记录当前状态
    │
    └── 步骤 4: 选择"下载日志"菜单
            └── locator(DOWNLOAD_MENU) → is_visible()
            │
            ├── expect_download(timeout=60s) as download_info:
            │       └── 点击菜单项
            │       └── 等待浏览器下载事件
            │
            ├── 捕获下载事件
            │       ├── 获取原始文件名 download.suggested_filename
            │       ├── 保留原始扩展名（如 .zip）
            │       ├── 生成新文件名: {task_id}_{timestamp}{original_ext}
            │       ├── 检查文件名唯一性（_get_unique_filepath）
            │       └── download.save_as(new_file_path)
            │
            ├── 处理确认对话框（_handle_confirm_dialog）
            │
            └── 验证文件完整性（verify_file_integrity）
                    ├── 文件存在？
                    └── 文件大小 > 0？
```

### 4.7 用户界面交互设计

#### 4.7.1 右键菜单操作

LVTS 系统使用 iView UI 框架的 Dropdown 组件实现右键菜单。操作流程：

1. **右键点击行元素**：`row.click(button="right")` 触发浏览器 contextmenu 事件
2. **iView Dropdown 渲染**：框架在 `.v-transfer-dom` 容器中动态创建下拉菜单 DOM
3. **菜单项定位**：使用选择器 `li.ivu-dropdown-item:has-text("下载日志")` 精确定位目标菜单项
4. **点击菜单项**：触发下载操作

**关键技术约束：**
- iView 的 Dropdown 组件将菜单渲染到 `body` 级别的 `.v-transfer-dom` 容器中，而非行元素内部
- 因此菜单选择器必须在 `self.page` 级别查找，而非 `row` 级别
- `_close_modals` 方法**绝不能删除** `.v-transfer-dom` 节点，只能隐藏 `.ivu-modal-wrap` 和 `.ivu-modal-mask`

#### 4.7.2 复选框操作

```python
# 方案 A：直接操作 checkbox
checkbox_locator = row.locator("input[type='checkbox']")
if not checkbox_locator.first.is_checked():
    checkbox_locator.first.click()

# 方案 B：点击首列单元格（后备）
first_cell_locator = row.locator("td:first-child")
first_cell_locator.first.click()
```

**设计决策：** 提供两种勾选方案，因为某些 UI 框架将原生 checkbox 隐藏，通过外层元素（如 `<td>`）代理点击事件。先尝试直接操作 checkbox，失败时回退到点击首列。

#### 4.7.3 弹窗清理（`_close_modals`）

```javascript
// 通过 JavaScript 隐藏弹窗遮罩
document.querySelectorAll('.ivu-modal-wrap, .ivu-modal-mask')
    .forEach(el => { el.style.display = 'none'; });
```

加上 `Escape` 键作为补充。

**安全约束：**
- 仅使用 `style.display = 'none'` 隐藏，**不删除 DOM 节点**
- 明确排除 `.v-transfer-dom`，保护 iView Dropdown 渲染容器
- 这确保了右键菜单在弹窗清理后仍能正常渲染

### 4.8 文件处理策略

#### 4.8.1 文件命名规则

```
原始文件名: server_generated_name.zip
        ↓
提取扩展名: .zip（保留原始格式）
        ↓
新文件名:   {task_id}_{YYYYMMDD}_{HHMMSS}.zip
        ↓
清理非法字符: _sanitize_filename()
        ↓
唯一性检查:   _get_unique_filepath()
        ↓
最终路径:     D:/BackupFiles/.../316235_20260602_140934.zip
```

**命名示例：**
- `316235_20260602_140934.zip` — 任务 316235，2026-06-02 14:09:34 下载
- `task_row_5_20260602_140934.zip` — 无法提取 ID 时的后备命名

#### 4.8.2 扩展名保留策略

```python
_, original_ext = os.path.splitext(original_filename)
new_filename = f"{safe_task_id}_{timestamp}{original_ext}"
```

**设计决策：** 必须保留服务端返回的原始文件扩展名（通常为 `.zip`），而非强制改为 `.log`。这确保了文件格式与内容一致。

#### 4.8.3 文件名冲突处理

```python
def _get_unique_filepath(self, filename: str) -> str:
    file_path = os.path.join(self.download_dir, filename)
    if not os.path.exists(file_path):
        return file_path
    # 冲突时追加 _1, _2, ... 后缀
    base, ext = os.path.splitext(filename)
    counter = 1
    while os.path.exists(file_path):
        file_path = os.path.join(self.download_dir, f"{base}_{counter}{ext}")
        counter += 1
    return file_path
```

#### 4.8.4 Windows 非法字符清理

```python
def _sanitize_filename(self, filename: str) -> str:
    # 替换 <>:"/\|?* 为下划线
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # 移除控制字符
    sanitized = re.sub(r'[\x00-\x1f\x7f]', '', sanitized)
    # 限制长度 200 字符（Windows 路径上限 260）
    if len(sanitized) > 200:
        sanitized = sanitized[:200]
    return sanitized
```

#### 4.8.5 文件完整性验证

```python
def verify_file_integrity(self, file_path: str) -> bool:
    # 验证：文件存在 + 大小 > 0
    if not os.path.exists(file_path): return False
    if os.path.getsize(file_path) == 0: return False
    return True
```

轻量级验证，仅检查文件是否存在且非空。对于本工具的场景（内网下载、Playwright 拦截），这已足够可靠。

### 4.9 去重机制

#### 双层去重策略

```
load_downloaded_tasks()
    │
    ├── 层 1: 从 downloaded_tasks.txt 读取
    │       └── 每行一个任务 ID
    │       └── 快速、可靠，程序自身维护
    │
    └── 层 2: 扫描下载目录文件
            └── 通过正则从文件名提取任务 ID
            └── 补充记录文件中遗漏的（如手动放入的文件）
```

#### 文件名解析正则

```python
# 主正则：匹配 {任意前缀}_{8位日期}_{6位时间}.{扩展名}
r"^(.+?)_\d{8}_\d{6}\."

# 示例：
# "316235_20260602_140934.zip" → "316235"
# "task_row_5_20260602_140934.zip" → "task_row_5"
```

非贪婪匹配 `(.+?)` 确保提取时间戳之前的最小前缀部分，配合 `\d{8}_\d{6}\.` 精确定位时间戳位置。

#### 过滤流程

```python
def filter_pending_tasks(self, tasks):
    downloaded = self.load_downloaded_tasks()   # 获取已下载 ID 集合
    pending = [t for t in tasks if t["id"] not in downloaded]  # O(1) 集合查找
    return pending
```

使用 `set` 数据结构存储已下载 ID，确保过滤操作的时间复杂度为 O(n)。

### 4.10 重试机制

```
_download_with_retry(task, max_retries=3)
    │
    ├── 尝试 1: download_task_log(task)
    │       ├── 成功 → 返回 True
    │       └── 失败 → 等待 30 秒
    │
    ├── 尝试 2: download_task_log(task)
    │       ├── 成功 → 返回 True
    │       └── 失败 → 等待 30 秒
    │
    └── 尝试 3: download_task_log(task)
            ├── 成功 → 返回 True
            └── 失败 → 返回 False（最终失败）
```

**配置参数：**
- 最大重试次数：3 次
- 重试间隔：30 秒（固定，不采用指数退避，因为内网环境网络状况相对稳定）

### 4.11 调度执行

#### 单次执行模式（`run_single_cycle`）

```
run_single_cycle()
    │
    ├── 1. _init_browser()          → 启动浏览器
    ├── 2. login()                  → 登录 LVTS
    ├── 3. navigate_to_task_list()  → 验证任务列表页面
    ├── 4. scan_downloadable_tasks() → 扫描所有可下载任务
    ├── 5. filter_pending_tasks()   → 过滤已下载任务
    │
    ├── 6. 逐个下载
    │       └── 对每个待下载任务：
    │           ├── _download_with_retry(task)
    │           ├── 成功 → save_downloaded_task() + 计数 +1
    │           └── 失败 → 计数 failed +1
    │
    └── 7. _close_browser()         → 关闭浏览器（finally）
    
    返回: {total, downloaded, skipped, failed}
```

**资源管理：** `_close_browser()` 在 `finally` 块中调用，确保无论正常完成还是异常中断，浏览器资源都能被释放。

#### 定时调度模式（`run_scheduler`）

```
run_scheduler(interval_hours=1)
    │
    └── while True:
            ├── cycle_count += 1
            ├── start_time = now
            │
            ├── run_single_cycle()     → 执行一次完整下载
            │
            ├── elapsed = now - start_time
            ├── wait_time = interval - elapsed
            │
            ├── wait_time > 0:
            │       └── sleep(wait_time) → 精确等待到下次执行时间
            │
            └── wait_time <= 0:
                    └── 立即开始下次执行（不补偿跳过的时间）
```

**时间计算：** 调度器从周期开始时刻计算间隔，而非从周期结束时刻。这意味着如果执行间隔设置为 1 小时，执行耗时 10 分钟，则等待 50 分钟后开始下一周期。如果执行耗时超过 1 小时，则立即开始下一周期。

---

## 5. 错误处理体系

### 5.1 分层异常捕获

程序采用三层异常捕获策略：

| 层级 | 范围 | 处理方式 |
|------|------|----------|
| 方法级 | 单个操作步骤 | 捕获异常 → 记录日志 → 返回 False/空值 |
| 周期级 | `run_single_cycle` | 捕获异常 → 记录日志 → 继续关闭浏览器 |
| 全局级 | `main()` | 捕获异常 → 打印错误 → 退出程序 |

### 5.2 截图诊断

在以下关键失败点自动保存截图：

| 触发场景 | 截图命名 | 用途 |
|----------|----------|------|
| 登录失败 | `login_failed_{status}.png` | 分析登录失败原因 |
| 登录异常 | `login_error.png` | 捕获意外异常 |
| 任务列表验证失败 | `task_list_verify.png` | 检查页面状态 |
| 行元素未找到 | `row_not_found_{id}.png` | 排查 DOM 变化 |
| 右键点击失败 | `right_click_failed_{id}.png` | 分析交互问题 |
| 菜单项未找到 | `no_download_menu_{id}.png` | 检查菜单渲染 |
| 下载异常 | `download_error_{id}.png` | 捕获下载失败 |
| 扫描异常 | `scan_tasks_error.png` | 分析扫描问题 |

截图保存到脚本所在目录，命名中的非法字符通过 `_sanitize_filename` 清理。

### 5.3 容错设计清单

| 场景 | 容错措施 |
|------|----------|
| 配置文件不存在 | 抛出 FileNotFoundError + 明确提示 |
| 配置文件 JSON 格式错误 | 抛出 ValueError + 解析错误详情 |
| 必需配置字段缺失 | 列出所有缺失字段（非遇到第一个就停） |
| 用户名输入框未找到 | 记录 error 日志 + 返回 False |
| 登录按钮未找到 | 遍历多个选择器 + 全找不到则记录错误 |
| 弹窗遮挡右键菜单 | `_close_modals` 自动清理 |
| 复选框无法直接操作 | 回退到点击首列单元格 |
| 右键菜单渲染超时 | 回退到固定等待 1 秒 |
| 下载文件名冲突 | 自动追加数字后缀 |
| 下载记录文件读取失败 | 降级为仅扫描目录 |
| 浏览器关闭异常 | try/except 保护 + 强制重置引用 |

---

## 6. 日志记录与调试

### 6.1 日志配置

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),  # 文件记录
        logging.StreamHandler(),                            # 控制台输出
    ],
)
```

**双通道输出：**
- 文件日志：持久化到 `log_downloader.log`，用于事后分析
- 控制台日志：实时输出，用于运行监控

### 6.2 日志级别使用规范

| 级别 | 用途 | 示例 |
|------|------|------|
| INFO | 正常流程节点 | "登录成功"、"找到 5 个可下载任务" |
| WARNING | 非致命异常 | "勾选复选框失败"、"跳过 3 个已下载任务" |
| ERROR | 操作失败 | "登录失败"、"任务下载最终失败" |
| DEBUG | 详细调试信息 | "检测到成功特征: .el-table"、"文件验证通过" |

### 6.3 调试支持

#### `--visible` 模式

```bash
python log_downloader.py --visible
```

将 `headless` 设为 `False`，浏览器窗口可见，方便观察自动化操作过程。配合截图文件，可以完整还原每次执行时的页面状态。

#### 截图文件分析

每次执行会在脚本目录生成多个 `.png` 截图文件，命名规则为 `{事件描述}_{任务ID}.png`。通过查看截图可以判断：
- 页面是否正确加载
- 右键菜单是否正常弹出
- 下载按钮是否存在
- 弹窗是否遮挡了操作目标

---

## 7. 命令行接口设计

### 7.1 参数说明

```
python log_downloader.py [-c CONFIG] [--once] [--visible] [--interval HOURS]
```

| 参数 | 短形式 | 类型 | 默认值 | 说明 |
|------|--------|------|--------|------|
| `--config` | `-c` | 字符串 | `config.json` | 配置文件路径 |
| `--once` | — | 标志 | False | 单次执行后退出 |
| `--visible` | — | 标志 | False | 显示浏览器窗口 |
| `--interval` | — | 浮点数 | 1.0 | 定时执行间隔（小时） |

### 7.2 运行模式

**单次模式：**
```bash
python log_downloader.py --once
```
执行一次完整的扫描-下载周期，打印结果统计后退出。适用于手动触发或外部调度器（如 Windows 任务计划程序）集成。

**定时模式：**
```bash
python log_downloader.py                    # 默认 1 小时间隔
python log_downloader.py --interval 2       # 2 小时间隔
python log_downloader.py --interval 0.5     # 30 分钟间隔
```
内置循环调度器，持续运行直到 `Ctrl+C` 中断。

### 7.3 批量启动支持

项目包含 `run_download_task.bat` 批处理文件，用于 Windows 环境一键启动：

```bat
# 典型内容（推测）
cd /d "D:\Defective-Product-Analysis\Log-Download"
python log_downloader.py --once
```

---

## 8. 数据流图

### 8.1 完整执行周期数据流

```
config.json ──────────┐
                      ▼
                ┌──────────┐
                │ 初始化   │  读取配置、设置路径、配置日志
                └────┬─────┘
                     ▼
                ┌──────────┐
                │ 浏览器   │  启动 Chrome、创建上下文
                └────┬─────┘
                     ▼
                ┌──────────┐
                │ 登录     │  goto → fill → click → 验证
                └────┬─────┘
                     ▼
                ┌──────────┐
                │ 导航验证 │  等待网络空闲、验证页面
                └────┬─────┘
                     ▼
                ┌──────────┐
                │ 扫描任务 │  遍历行 → 检查下载按钮 → 提取 ID/名称
                └────┬─────┘
                     ▼
                ┌──────────┐
                │ 去重过滤 │  比对 downloaded_tasks.txt + 目录扫描
                └────┬─────┘
                     ▼
             ┌──────────────┐
             │ 逐任务下载   │◄──── 循环
             │              │
             │ ┌──────────┐ │
             │ │ 关闭弹窗 │ │
             │ │ 勾选复选框│ │
             │ │ 右键点击  │ │
             │ │ 选择菜单  │ │
             │ │ 捕获下载  │ │
             │ │ 保存文件  │ │
             │ │ 验证完整性│ │
             │ └──────────┘ │
             │              │
             │ 失败 → 重试  │（最多 3 次，间隔 30 秒）
             └──────┬───────┘
                    ▼
             ┌──────────────┐
             │ 更新记录     │  写入 downloaded_tasks.txt
             └──────┬───────┘
                    ▼
             ┌──────────────┐
             │ 关闭浏览器   │  释放资源
             └──────┬───────┘
                    ▼
             ┌──────────────┐
             │ 等待/退出     │  定时模式等待下次 / 单次模式退出
             └──────────────┘
```

### 8.2 文件交互关系

```
config.json ──读取──→ LogDownloader
                          │
                          ├──写入──→ log_downloader.log（运行日志）
                          │
                          ├──读取──→ downloaded_tasks.txt（已下载记录）
                          ├──写入──→ downloaded_tasks.txt（追加新记录）
                          │
                          ├──写入──→ {下载目录}/*.zip（日志文件）
                          │
                          └──写入──→ *.png（调试截图）
```

---

## 9. Playwright 元素定位策略

### 9.1 定位模式

程序统一遵循以下 Playwright 元素操作模式：

```python
# 1. 创建 locator
locator = self.page.locator(selector)

# 2. 检查元素是否存在
if locator.count() > 0:
    # 3. 操作第一个匹配元素
    locator.first.click()
```

**禁止操作：** 对已调用 `.first()` 的 locator 执行 `.count()` 判断。必须先在原始 locator 上检查 `count() > 0`，再通过 `.first` 访问。

### 9.2 多选择器降级策略

对于可能因页面版本不同而变化的元素，采用「选择器列表 + 逐个尝试」策略：

```python
SELECTORS = ["selector_1", "selector_2", "selector_3"]

for selector in SELECTORS:
    locator = self.page.locator(selector)
    if locator.count() > 0:
        # 找到匹配，使用此选择器
        break
```

选择器按优先级从高到低排列，特异性强的在前，通用兜底的在后。

### 9.3 等待策略优先级

| 优先级 | 方法 | 适用场景 |
|--------|------|----------|
| 1 | `locator.wait_for(state="visible")` | 等待元素出现 |
| 2 | `locator.wait_for(state="hidden")` | 等待元素消失 |
| 3 | `page.wait_for_load_state("networkidle")` | 等待页面稳定 |
| 4 | `page.wait_for_selector()` | 等待选择器匹配 |
| 5 | `page.wait_for_timeout()` | 固定等待（仅用于 UI 微延迟） |

**原则：** 优先使用 Playwright 原生等待 API，仅在必要时（如 UI 微延迟 300-500ms）使用固定等待。

---

## 10. 性能设计

### 10.1 资源管理

| 资源 | 管理方式 |
|------|----------|
| 浏览器实例 | 每个周期创建/销毁，避免长时间运行的内存泄漏 |
| Playwright 进程 | 随浏览器一起管理，`finally` 块确保释放 |
| 脚本目录路径 | `__init__` 中缓存为 `self._script_dir`，避免重复计算 |
| 配置数据 | `__init__` 中一次性加载，拆分为 `lvts_config` 和 `download_config` |

### 10.2 执行效率

| 优化点 | 实现 |
|--------|------|
| 去重过滤 | 使用 `set` 数据结构，查找复杂度 O(1) |
| 选择器匹配 | 找到第一个匹配立即 `break`，避免不必要的遍历 |
| 下载目录创建 | `os.makedirs(exist_ok=True)`，无冗余检查 |
| 下载记录追加 | 使用 `open("a")` 追加写入，无需读取全量 |

### 10.3 超时控制

所有等待操作都有明确的超时限制，避免程序因页面异常而永久挂起：

- 表单加载：10 秒
- 登录验证：22.5 秒（15 × 1.5）
- 网络空闲：10 秒
- 菜单渲染：3 秒
- 文件下载：60 秒
- 全局默认：60 秒

---

## 11. 项目文件清单

```
Log-Download/
├── log_downloader.py      # 主程序（1178 行）
├── config.json            # 运行配置（服务器地址、凭据、下载路径）
├── requirements.txt       # Python 依赖（playwright>=1.40.0）
├── run_download_task.bat  # Windows 批处理启动脚本
├── downloaded_tasks.txt   # 运行时生成 — 已下载任务 ID 记录
├── log_downloader.log     # 运行时生成 — 运行日志
├── downloads/             # 默认下载目录（可配置覆盖）
│   └── *.zip              # 下载的日志文件
└── *.png                  # 调试截图（运行时生成）
```
