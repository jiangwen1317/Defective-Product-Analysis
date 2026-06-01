# LVTS 日志定时下载器使用说明

## 快速开始

### 1. 安装依赖

```bash
cd D:\Defective-Product-Analysis\Log-Download
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置

编辑 `config.json` 文件,填入您的 LVTS 服务器信息:

```json
{
  "lvts_server": {
    "url": "http://YOUR_LVTS_URL/taskList/1/4654",
    "username": "your_username",
    "password": "your_password"
  },
  ...
}
```

**必填配置项:**
- `lvts_server.url`: LVTS 服务器地址 (任务列表页面 URL)
- `lvts_server.username`: 登录用户名
- `lvts_server.password`: 登录密码

**可选配置项:**
- `download.directory`: 下载目录 (默认: downloads)
- `scheduler.interval_hours`: 执行间隔小时数 (默认: 1)
- `scheduler.retry_count`: 重试次数 (默认: 3)
- `browser.headless`: 是否隐藏浏览器 (默认: true)

### 3. 运行

**定时模式 (后台运行):**
```bash
python log_downloader.py
```

**单次执行模式:**
```bash
python log_downloader.py --once
```

**显示浏览器窗口 (调试用):**
```bash
python log_downloader.py --visible
```

**自定义执行间隔 (2小时):**
```bash
python log_downloader.py --interval 2
```

## 操作流程

下载器自动执行以下操作:

1. **登录 LVTS 服务器** - 使用配置的用户名和密码
2. **验证任务列表页面** - 确认页面加载成功
3. **扫描可下载任务** - 查找所有任务行
4. **下载日志文件**:
   - 勾选任务行的复选框
   - 右键点击任务行弹出上下文菜单
   - 选择"下载日志"菜单项
   - 保存文件到下载目录
5. **去重处理** - 跳过已下载的任务

## 目录结构

```
Log-Download/
├── log_downloader.py          # 主脚本
├── config.json                # 配置文件
├── requirements.txt           # 依赖列表
├── run_download_task.bat      # Windows 任务脚本
├── downloaded_tasks.txt       # 下载记录 (自动生成)
├── log_downloader.log         # 日志文件 (自动生成)
└── downloads/                 # 下载目录 (自动创建)
    └── {task_id}_{timestamp}.log
```

## Windows 任务计划程序集成

### 方法 1: 使用批处理脚本

1. 打开 Windows 任务计划程序
2. 点击"创建基本任务"
3. 设置任务名称 (如: LVTS日志下载)
4. 设置触发器 (如: 每天 9:00,或每小时)
5. 操作选择"启动程序"
6. 浏览选择 `run_download_task.bat`
7. 完成创建

### 方法 2: 直接配置

1. 打开 Windows 任务计划程序
2. 创建任务
3. 触发器: 设置执行时间
4. 操作: 
   - 程序: `python`
   - 参数: `log_downloader.py --once --config config.json`
   - 起始于: `D:\Defective-Product-Analysis\Log-Download`

## 功能特性

### 自动去重

下载器使用双重去重机制:
1. **文件扫描**: 自动扫描下载目录中已存在的文件
2. **记录文件**: 维护 `downloaded_tasks.txt` 记录已下载任务 ID

### 重试机制

- 默认重试 3 次
- 每次重试间隔 30 秒
- 可在配置文件中调整重试参数

### 日志记录

- 日志文件: `log_downloader.log`
- 同时输出到控制台和文件
- 记录所有关键操作和错误信息

### 错误截图

登录失败或页面异常时自动保存截图:
- `login_failed.png`: 登录失败截图
- `login_error.png`: 登录错误截图
- `after_right_click_{task_id}.png`: 右键点击后截图
- `after_download_click_{task_id}.png`: 点击下载后截图
- `download_timeout_{task_id}.png`: 下载超时截图

## 常见问题

### Q: 第一次运行需要做什么?

A: 建议先使用 `--visible` 参数运行一次,观察浏览器操作流程,确认:
1. 登录是否正常
2. 是否正确识别任务
3. 下载是否成功

### Q: 下载器没有下载任何文件?

A: 检查以下几点:
1. 确认 LVTS 服务器 URL 和登录凭据正确
2. 确认任务列表页面有可下载的任务
3. 查看日志文件了解详细信息

### Q: 如何调整下载间隔?

A: 两种方法:
1. 修改 `config.json` 中的 `scheduler.interval_hours`
2. 运行时使用 `--interval` 参数覆盖配置

### Q: 如何清空下载记录重新下载?

A: 删除 `downloaded_tasks.txt` 文件,下载器会重新下载所有任务。

## 更新日志

### v1.0.0 (2026-06-01)
- 初始版本发布
- 支持自动登录、任务扫描、日志下载
- 右键菜单触发下载
- 双重去重机制
- 定时调度和单次执行模式
- 完善的错误处理和重试机制
