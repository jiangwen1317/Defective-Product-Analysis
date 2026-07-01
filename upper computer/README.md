# 机械臂中转网关 v3.0

纯被动响应式全自动中转网关，实现机械臂与 3720 芯片测试仪之间的信号透传。

## 核心特性

- **零人工干预**：仅响应机械臂发来的 `START_TEST` 请求，自动完成全套中转流程
- **threading 架构**：使用 threading + socket 实现，与 PyQt5 原生集成
- **分层解耦设计**：设备适配层、信号路由层、UI 层严格分离
- **毫秒级日志**：完整记录每次信号收发内容、耗时、异常详情

## 项目结构

```
upper computer/
├── main.py                    # 程序入口
├── config.py                  # 配置管理（支持热加载）
├── config.json                # 配置文件
├── requirements.txt           # 依赖清单
├── protocol/
│   ├── __init__.py
│   └── arm_protocol.py        # 机械臂通讯协议处理器
├── adapters/                  # 设备适配层
│   ├── __init__.py
│   ├── arm_adapter.py         # 机械臂适配器（TCP Server, threading）
│   └── tc3720_adapter.py      # 3720 适配器（模拟器, threading）
├── router/                    # 信号路由层
│   ├── __init__.py
│   └── gateway.py             # 核心中转网关（threading）
└── ui/                        # UI 层
    ├── __init__.py
    └── main_window.py         # 主窗口（PyQt5 + threading）
```

## 业务流程

```
┌─────────────┐     @START_TEST      ┌─────────────┐
│   机械臂    │ ─────────────────►   │   网关      │
│  (TCP Client)                       │             │
└─────────────┘                       │             │
                                      │  @START_TEST → 自动转发
                                      │             │
                                      │             │
                                      │             │  等待结果...
                                      │             │
┌─────────────┐     @TEST_DONE       │             │
│   机械臂    │ ◄─────────────────   │             │
│             │                      │             │
└─────────────┘                       └─────────────┘
       ▲                                    │
       │                                    ▼
       │                          ┌─────────────────┐
       │                          │  3720 测试仪    │
       │                          │  (模拟/TBD)     │
       │                          └─────────────────┘
```

**完整流程**：
1. **空闲监听**：网关等待机械臂连接
2. **收到 START_TEST**：机械臂发送 `@START_TEST <Group> <Bitmask>+`
3. **自动转发 3720**：网关立即转发测试请求
4. **等待结果**：监听 3720 测试完成信号
5. **自动回传**：收到结果后自动发送 `@TEST_DONE <Group> <EC1>...<EC8>+`
6. **重置空闲**：回到待命状态，支持连续作业

## 架构演进说明

### v1 → v3 架构变更说明

| 版本 | 并发模型 | GUI 框架 | 说明 |
|------|---------|---------|------|
| v1 | asyncio | customtkinter | 初始版本，人工操作模式 |
| v2 | asyncio | PyQt5 | 需求变更，事件驱动模式 |
| **v3** | **threading** | **PyQt5** | **优化：与 PyQt5 原生集成，消除事件循环冲突** |

### 为什么选择 threading 而非 asyncio？

| 考量 | asyncio | threading | 本项目适合度 |
|------|---------|-----------|------------|
| 单连接场景 | 无优势 | 足够 | **threading 胜** |
| 与 PyQt5 集成 | 复杂（事件循环冲突） | 简单（线程隔离） | **threading 胜** |
| 学习曲线 | 陡峭 | 平缓 | **threading 胜** |
| 代码可读性 | 较复杂 | 直观 | **threading 胜** |
| 高并发能力 | 强 | 一般 | 不需要 |

**结论**：本项目是单连接、串行流程的上位机应用，threading 架构更简单、更易维护。

### 为什么保持 PyQt5 而非 customtkinter？

| 考量 | PyQt5 | customtkinter | 本项目适合度 |
|------|-------|---------------|------------|
| 实时状态更新 | 信号/槽原生支持 | `after()` 轮询 | **PyQt5 胜** |
| 线程安全机制 | 原生信号跨线程 | 需额外处理 | **PyQt5 胜** |
| 数据库分析项目 | - | 已使用 | 技术栈不统一（但可接受） |

**结论**：上位机需要实时监控和状态更新，PyQt5 的信号槽机制更适合。

## 配置说明

配置文件：`config.json`

```json
{
    "gateway": {
        "arm_host": "0.0.0.0",      // 机械臂监听地址
        "arm_port": 8080,            // 机械臂监听端口
        "tc3720_mode": "simulator",  // 3720 模式：simulator/tcp/serial/io
        "tc3720_host": "192.168.1.101",
        "tc3720_port": 9090,
        "test_timeout": 30.0,        // 测试超时时间（秒）
        "enable_debug": false        // 调试面板（生产环境为 false）
    },
    "ui": {
        "window_width": 1000,
        "window_height": 700,
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

## 协议格式

### 机械臂指令

| 指令 | 方向 | 格式 | 说明 |
|------|------|------|------|
| START_TEST | Client → Server | `@START_TEST <Group> <Bitmask>+` | 启动测试 |
| TEST_DONE | Server → Client | `@TEST_DONE <Group> <EC1>...<EC8>+` | 测试完成 |

**参数说明**：
- `Group`：2位十六进制数（如 `00`、`FF`）
- `Bitmask`：8位二进制字符串，从左至右对应 DUT #1 至 DUT #8
- `EC1~EC8`：8个4位十六进制错误码，`0000` 表示通过

### 3720 适配器

当前阶段使用模拟器（`simulator`）模式。真实设备通信协议待确认后实现。

## 扩展说明

### 添加新的 3720 通信模式

1. 在 `adapters/tc3720_adapter.py` 中实现对应的通信方法
2. 在 `router/gateway.py` 的 `_forward_to_3720` 中调用新方法
3. 更新 `config.json` 中的 `tc3720_mode` 配置

### 更换机械臂协议

机械臂适配器 `adapters/arm_adapter.py` 负责协议解析，如协议有变更：
1. 修改 `protocol/arm_protocol.py` 中的编解码逻辑
2. 更新 `adapters/arm_adapter.py` 中的帧处理逻辑

## 错误码说明

| 错误码 | 含义 |
|--------|------|
| E001 | 机械臂通信超时 |
| E002 | 3720 测试超时 |
| E003 | 机械臂断连 |
| E004 | 3720 设备错误 |
| E005 | 协议解析错误 |
| EEEE | 未知错误 |
