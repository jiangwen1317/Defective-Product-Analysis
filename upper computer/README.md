# 机械臂中转网关 v2.0

主动触发模式中转网关，实现机械臂与 3720 芯片测试仪之间的信号透传与多 DUT 并发测试。

> 开发约束见仓库根 [AGENTS.md](../AGENTS.md)，提交前须在仓库根运行检查入口 [check.bat](../check.bat)。

## 核心特性

- **主动触发模式**：上位机发送 `@TEST_DONE` 触发机械臂，支持选板测试
- **多 DUT 并发**：支持 8 个 DUT 同时测试，状态独立监控
- **threading 架构**：使用 threading + socket 实现，与 PyQt5 原生集成
- **多种通信模式**：支持 TCP Server、TCP Client、串口三种机械臂连接方式
- **自动重连**：设备断线自动重连，无需人工干预
- **实时状态监控**：UI 实时显示设备连接状态、测试进度、错误码

## 项目结构

```
upper computer/
├── main.py                      # 程序入口
├── config.py                    # 配置管理
├── config.json                  # 配置文件
├── requirements.txt             # 依赖清单
│
├── protocol/                    # 协议层
│   └── arm_protocol.py          # 机械臂通讯协议处理器
│
├── adapters/                    # 适配器层
│   ├── base_arm_adapter.py      # 机械臂适配器基类
│   ├── arm_adapter.py           # 机械臂 TCP 适配器
│   ├── serial_arm_adapter.py    # 机械臂串口适配器
│   ├── tc3720_adapter.py        # 3720 状态枚举（TC3720Status）
│   └── tc3720_tcp_adapter.py    # 3720 测试仪 TCP 适配器
│
├── router/                      # 路由层
│   ├── gateway.py               # 核心中转网关
│   └── device_manager.py        # 多设备管理器
│
├── ui/                          # UI 层
│   ├── main_window.py           # 主窗口（PyQt5）
│   ├── components.py            # 通用组件库
│   └── styles.py                # 样式系统
│
├── tests/                       # 测试
│   ├── test_arm_protocol.py     # 协议测试
│   ├── test_base_arm_adapter.py # 适配器测试
│   ├── test_device_manager.py   # 设备管理测试
│   ├── test_gateway.py          # 网关测试
│   ├── test_thread_safety.py    # 线程安全测试
│   ├── test_p0_concurrency_fixes.py  # P0 并发缺陷回归
│   ├── test_p1_fixes.py         # P1 缺陷回归
│   ├── test_p1_stage3_fixes.py  # 阶段三 P1 缺陷回归
│   └── test_disconnect_fixes.py # 断线检测与配置模板回归
│
└── docs/
    └── 机械臂测试通信协议规范.md  # 通信协议文档
```

## 业务流程

### 主动触发模式（v2.0 新增）

```
┌──────────┐  1. @TEST_DONE (选板)   ┌──────────┐  2. @START_TEST  ┌──────────┐
│  上位机   │ ───────────────────►   │   机械臂   │ ──────────────►  │  3720    │
│  (UI)    │                        │           │                  │  测试仪   │
└──────────┘                        └──────────┘                   └──────────┘
     ▲                                    │                              │
     │                                    │                              │
     │  6. @TEST_DONE (结果)              │  5. ErrorCode                 │
     │────────────────────────────────────┼──────────────────────────────│
     │                                    │                              │
```

**完整流程**：
1. 用户在 UI 选择要测试的板子，点击"触发测试"
2. 上位机发送 `@TEST_DONE 00 0001 0001 ...+`（0001=测试，0000=跳过）
3. 机械臂收到后发送 `@START_TEST 00 10100000+`
4. 网关解析 Bitmask，通知对应 DUT 的 3720 测试仪
5. 3720 测试完成返回 ErrorCode
6. 网关收集所有结果，发送 `@TEST_DONE` 给机械臂

### 被动监听模式（兼容）

传统模式：机械臂主动发送 `@START_TEST`，网关自动转发至 3720。

## 架构说明

### 为什么选择 threading 而非 asyncio？

| 考量 | asyncio | threading | 本项目适合度 |
|------|---------|-----------|------------|
| 单连接场景 | 无优势 | 足够 | **threading 胜** |
| 与 PyQt5 集成 | 复杂（事件循环冲突） | 简单（线程隔离） | **threading 胜** |
| 学习曲线 | 陡峭 | 平缓 | **threading 胜** |
| 代码可读性 | 较复杂 | 直观 | **threading 胜** |
| 高并发能力 | 强 | 一般 | 不需要 |

**结论**：本项目是单连接、串行流程的上位机应用，threading 架构更简单、更易维护。

### 线程模型

```
┌─────────────────────────────────────────────────────────┐
│                     MainThread (GUI)                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │
│  │ MainWindow  │  │ QTimer 100ms│  │ UI Components   │  │
│  └──────┬──────┘  └─────────────┘  └─────────────────┘  │
│         │                                                  │
│         │ pyqtSignal.emit() → 排队到主线程执行             │
└─────────┼─────────────────────────────────────────────────┘
          │ 回调线程安全
┌─────────▼─────────────────────────────────────────────────┐
│                    WorkerThreads                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│  │ArmAdapter   │  │TC3720Adapter│  │ReconnectLoop│       │
│  │(Receive)    │  │(Receive)    │  │             │       │
│  └─────────────┘  └─────────────┘  └─────────────┘       │
└─────────────────────────────────────────────────────────┘
```

## 配置说明

配置文件：`config.json`（可从 `config_serial_example.json` 串口模板或
`config_full.json` 全量模板复制后修改，缺失字段使用代码内置默认值）

```json
{
    "gateway": {
        "arm_mode": "serial",          // 通信模式: tcp_server | tcp_client | serial（必填）
        "arm_host": "0.0.0.0",         // TCP Server 监听地址
        "arm_port": 8080,              // TCP Server 监听端口
        "arm_target_host": "",         // TCP Client 目标地址
        "arm_target_port": 0,          // TCP Client 目标端口
        "arm_reconnect_interval": 5.0, // 重连间隔（秒）
        "arm_serial_port": "COM3",     // 串口名称（串口模式必填）
        "arm_serial_baudrate": 115200, // 波特率（串口模式必填）
        "test_timeout": 30.0           // 测试超时时间（秒）
    },
    "devices": {                      // 多 DUT 配置（IP 为空的 DUT 会被跳过）
        "dut1": {"ip": "192.168.1.101", "port": 9090, "name": "Board-1"},
        "dut2": {"ip": "192.168.1.102", "port": 9090, "name": "Board-2"}
    },
    "ui": {
        "window_width": 1200,
        "window_height": 800,
        "log_max_lines": 5000,
        "theme": "dark"
    }
}
```

## 安装与运行

```bash
# 安装依赖
pip install -r requirements.txt

# 运行
python main.py
```

## 依赖清单

```
PyQt5>=5.15.0      # GUI 框架
pyserial>=3.5      # 串口通信
```

## 协议格式

详见 [docs/机械臂测试通信协议规范.md](docs/机械臂测试通信协议规范.md)

### 核心指令

| 指令 | 方向 | 格式 | 说明 |
|------|------|------|------|
| START_TEST | 机械臂→网关 | `@START_TEST <Group> <Bitmask>+` | 启动测试 |
| TEST_DONE | 双向 | `@TEST_DONE <Group> <EC1>...<EC8>+` | 测试完成/触发 |

### Bitmask 说明

8位二进制字符串，从左至右对应 DUT #1 至 DUT #8：
- `1` = 测试该 DUT
- `0` = 跳过该 DUT

示例：`10100000` = 测试 DUT #1 和 #3

### ErrorCode 说明

| 错误码 | 含义 |
|--------|------|
| 0000 | 测试通过 |
| 非0000 | 测试失败（具体含义见 3720 设备文档） |
| EEEE | 未知错误/超时 |

## 版本历史

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v1.0 | - | 被动响应模式，纯透传 |
| v2.0 | - | 主动触发模式，支持选板测试，多 DUT 并发 |
