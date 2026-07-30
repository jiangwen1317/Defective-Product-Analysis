# AGENTS.md — 项目代理约束（权威来源）

本文件是随仓库交付的**权威项目约束**，适用于所有编码代理（Claude Code、Qoder 等）
与人工开发者。个人性配置（身份设定、个人偏好）不在本文件内，保留在被 git 忽略的
`CLAUDE.md` / `IDENTITY.md` / `.claude/settings.json` 中。

仓库包含三个子项目：

| 目录 | 说明 |
|------|------|
| `upper computer/` | PyQt5 上位机：机械臂/3720 测试仪网关与 UI |
| `database-analysis/` | EMMC 日志解析、SQLite 存储与 RMA 报告 |
| `Log-Download/` | Playwright 日志下载自动化工具 |

---

## 一、命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 模块/文件名 | snake_case | `query_engine.py` |
| 类 | PascalCase | `RmaReportGenerator` |
| 函数/变量/常量 | snake_case | `get_defect_stats()`, `MAX_RETRY` |
| 私有成员 | `_snake_case` | `_validate_schema()` |

**禁用**：单字母变量（循环 `i/j/k` 除外）、中文拼音命名。

## 二、函数设计

```python
def func_name(param: type, param2: type = default) -> return_type:
    """一句话描述功能。

    Args:
        param: 参数说明。
        param2: 可选参数说明。

    Returns:
        返回值说明。

    Raises:
        ValueError: 参数校验失败时。
    """
```

**原则**：
- 公开函数必须有类型注解和 docstring
- 每个函数不超过 50 行
- 优先单一职责

## 三、类型注解

```python
from typing import TypeAlias, Literal, Optional

DefectLevel: TypeAlias = Literal["P0", "P1", "P2", "P3"]

def find(id: str) -> Optional[Defect]: ...  # ✅ Optional[X]

def process(data: list[Defect]) -> dict[str, int]: ...  # ✅ 具体类型
```

**禁用**：`Any`、`Dict` 等过于宽泛的类型。

## 四、异常处理

- **不要静默捕获异常**：除非明确知道如何处理，否则传播
- **保留原始异常**：`raise XxxError(...) from e`
- **不要用异常控制流程**：正常逻辑用条件判断

```python
# ✅ 异常链
try:
    conn.execute(sql)
except sqlite3.Error as e:
    raise DatabaseError(f"Query failed", cause=e) from e

# ❌ 静默捕获
try:
    do_something()
except:
    pass
```

## 五、导入规范

```python
# 标准库 → 第三方 → 本地（相对导入）
import os
from datetime import datetime
from typing import Any

import pytest

from .database import get_connection
```

## 六、数据库操作

```python
# ✅ 使用上下文管理器
with get_connection(db_path) as conn:
    conn.execute("SELECT * FROM defects WHERE level = ?", (level,))

# ❌ 字符串拼接（SQL 注入风险）
conn.execute(f"SELECT * FROM defects WHERE level = '{level}'")
```

## 七、GUI 开发（PyQt5）— 线程模型

**所有 UI 更新必须在主线程执行。**

跨线程通信使用 `pyqtSignal`（跨线程 emit 自动排队到主线程执行，
是 Qt 官方保证线程安全的机制）：

```python
class MainWindow(QMainWindow):
    # 类属性定义信号
    _sig_data = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        # 接线需先于回调可能触发的时机，槽在主线程执行
        self._sig_data.connect(self._update_ui_safe)

    # ✅ 正确：工作线程回调只 emit，不直接碰控件
    def on_data_received(self, data: str) -> None:
        self._sig_data.emit(data)

# ❌ 错误：直接在工作线程更新 UI
def on_data_received(self, data: str) -> None:
    self._label.setText(data)  # 可能导致崩溃

# ❌ 错误：不要用 QTimer.singleShot 从工作线程调度到主线程
# （非标准跨线程路径，历史上已统一替换为 pyqtSignal）
```

窗口销毁时：
- 停止所有定时器
- 断开所有回调连接
- 清理子组件

## 七.1 适配器开发规范（upper computer/adapters/）

适配器处理底层通信，需遵循：

```python
class MyAdapter:
    def __init__(self, ...):
        # 状态变量必须有锁保护
        self._lock = threading.Lock()
        self._connected = False
        self._buffer = ""

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    def _on_connected_internal(self) -> None:
        """内部连接处理，必须调用回调"""
        with self._lock:
            self._connected = True
        if self._on_connected:
            self._on_connected(self)  # 触发回调，由上层处理线程安全
```

重连机制：
- 使用独立线程 `_reconnect_thread` 执行重连循环
- 使用 `_reconnect_lock` 防止重复启动重连线程
- `_stop_reconnect` Event 控制停止

### 适配器继承体系与新增适配器契约

```
BaseArmAdapter (抽象基类)
├── ArmAdapter (TCP Server/Client)
└── SerialArmAdapter (串口)

TC3720TcpAdapter (独立实现)
TC3720Status (状态枚举，tc3720_adapter.py)
```

新增适配器时：
1. 继承对应基类
2. 实现抽象方法：`_do_connect`, `_do_disconnect`, `_read_available`, `_write_data`
   （`_read_available` 超时无数据返回 None，连接断开必须抛 ConnectionError，
   否则断线永远检测不到）
3. 在 `adapters/__init__.py` 导出

## 七.2 项目配置规范（upper computer/config.json）

配置文件位于 `upper computer/config.json`，验证规则：

```python
# 端口号范围验证
if not (1 <= arm_port <= 65535):
    raise ValueError(f"端口必须是 1-65535，当前值: {arm_port}")

# 超时必须为正数
if test_timeout <= 0:
    raise ValueError(f"超时必须是正数，当前值: {test_timeout}")

# IP 地址使用 socket 验证
import socket
try:
    socket.inet_aton(ip)
except OSError:
    raise ValueError(f"无效的 IP 地址: {ip}")
```

## 八、协议解析规范

- 数据包必须有校验和/CRC
- 版本号必须显式声明
- 解析失败时记录原始十六进制数据
- 使用缓冲区处理分片数据
- 非协议数据（如配置信息）应忽略并记录 DEBUG 级别日志

## 九、日志规范

| 级别 | 使用场景 |
|------|----------|
| DEBUG | 调试信息，生产环境关闭 |
| INFO | 业务节点（如"完成处理 N 条数据"） |
| WARNING | 可恢复异常（如"缓存未命中"） |
| ERROR | 操作失败需关注 |

**禁止**：记录密码、Token 等敏感信息。

## 十、测试规范

```python
class TestArmProtocol:
    """按被测模块命名测试类。"""

    def test_parse_start_test_valid_input(self):
        """测试名称描述预期行为。"""
        ...
```

- 测试文件放在 `tests/` 目录，与源码结构对应
- 使用 `pytest` 框架，测试函数以 `test_` 开头
- 线程安全测试：验证 `_start_reconnect` 不会创建多个线程
- 协议测试：验证指令解析、构建的边界条件

### 十.1 无真实设备的测试

模拟器类 TC3720Adapter 已在死代码清理中删除（tc3720_adapter.py 仅保留
 TC3720Status 枚举）。需要模拟设备行为时：

- 单元测试：用 unittest.mock 或自建假适配器
  （参考 tests/test_p0_concurrency_fixes.py 的 _FakeArmAdapter）
- 集成测试：用真实 socket + 内核分配临时端口（port=0，
  参考 tests/test_disconnect_fixes.py 的 Server 模式断线检测用例）

## 十一、重构准则

### 核心要求（无风险重构）
- **保持行为一致**：重构后代码必须与原代码产生完全相同的输出和副作用
- **小步前进**：每次只做一个小的改动，验证后再进行下一步
- **有测试保障**：确保测试覆盖充分，重构前先运行测试确认通过

### 允许的重构
- 提取重复代码为独立函数（命名清晰表达职责，保持单一职责）
- 简化条件表达式（提前返回减少嵌套、合并重复判断、
  `if x: return True` → `return bool(x)`、复杂条件提取为布尔变量/函数）
- 消除冗余代码（未使用的变量/导入/函数、重复的逻辑分支）
- 变量重命名（`d` → `defect_record`，遵循 snake_case）
- 简化数据结构操作（列表推导式替代简单 for 循环、`dict.get()` 处理默认值、
  `with` 语句管理资源）

### 禁止的重构
- ❌ 改变函数入参/返回值类型（输入输出契约）
- ❌ 修改公开 API 签名或算法核心逻辑
- ❌ 删除看似"无用"但实际影响行为的代码（如副作用）
- ❌ 改变异常类型或抛出时机
- ❌ 在不确定的情况下"优化"性能

### 重构验证
- [ ] 所有测试通过
- [ ] 边界条件处理不变
- [ ] 异常处理逻辑不变
- [ ] 副作用（日志、状态修改）不变
- [ ] 代码可读性提升

## 十二、网关与设备管理（upper computer/router/）

### PassthroughGateway（信号路由网关）

核心职责：
- 解析机械臂指令（@START_TEST）
- 管理多 DUT 测试状态
- 收集并组装测试结果

回调设计（线程安全）：
```python
self._on_state_changed = on_state_changed      # 网关状态变化
self._on_arm_connected = on_arm_connected      # 机械臂连接状态
self._on_dut_status_changed = on_dut_status_changed  # 单个 DUT 状态
self._on_test_result = on_test_result          # 测试结果
self._on_error = on_error                      # 错误回调
```

回调在**工作线程**中触发，上层（如 UI）需要通过 `pyqtSignal` 转发到主线程。

### DeviceManager（多设备管理器）

管理 8 个 3720 测试仪连接：
```python
# 初始化所有设备
for dut_index in range(1, DeviceManager.DUT_COUNT + 1):
    self._init_device(dut_index)

# 并发启动测试
results = self._device_manager.start_test([1, 3, 5])  # 测试 DUT 1,3,5
```

## 十三、提交前机械检查

提交前必须在仓库根运行检查入口，失败则禁止提交：

```bat
check.bat
```

包含三个环节：

1. **ruff 静态检查**：规则配置在根级 `pyproject.toml`，三个子项目共享，
   机械化本文件中的可自动规则：公开函数类型注解（ANN001/ANN201）、
   禁用 `Any`（ANN401）、函数长度上限（PLR0915，语句数 ≤ 50）。
2. **豁免只减不增断言**：`tools/check_exemption_baseline.py` 统计
   `pyproject.toml` 存量基线豁免的（文件, 规则码）对数，超过记录的基线
   即失败；收紧豁免后应同步下调脚本中的 `BASELINE_PAIRS` 并更新
   `pyproject.toml` 豁免段的违规计数快照。
3. **pytest 套件**：依次运行 `upper computer`、`database-analysis`、
   `Log-Download` 三个子项目的测试。

约束：

- 开发依赖声明在根级 `requirements-dev.txt`
- 新代码不得新增违规；`pyproject.toml` 中的存量基线豁免只减不增，
  修复存量违规后应同步删除对应豁免条目
- 禁止为绕过检查随意添加 `# noqa` 或扩大豁免范围

### 机械触发点（pre-commit hook）

检查由版本化的 `githooks/pre-commit` 在每次 `git commit` 时强制触发：
hook 调用仓库根 `check.bat`，任一环节失败即以非零码拦截提交，
并向 `.git/check-audit.log` 追加一条审计记录（时间、HEAD、退出码）。

克隆仓库后需一次性启用（在仓库根执行）：

```bat
git config core.hooksPath githooks
```

约束：

- hook 只负责触发与审计，不得在其中增删或跳过 `check.bat` 的检查环节
- 禁止使用 `git commit --no-verify` 绕过检查
- `githooks/` 下的 sh 脚本必须保持 LF 行尾（由 `.gitattributes` 固定）

## 十四、分批修复循环

当一次任务包含 2 个及以上同类修复项（如批量修复 ruff 违规、收紧
`pyproject.toml` 存量豁免、批量缺陷修复），预计需要多轮「修改→验证」
往返时，必须按本节循环执行，禁止一次性大改后再整体验证。

### 有序步骤

1. **切批**：列出全部待修项，按子项目或规则码分组切批；
   一批的改动必须可在单次提交内完整审查。
2. **修一批**：只改当前批次范围内的内容，遵循第十一节重构准则。
3. **聚焦检查**：`.venv\Scripts\python.exe -m ruff check <改动路径>`；
   涉及行为的改动加跑对应子项目测试：
   `.venv\Scripts\python.exe -m pytest "<子项目>" -q`。
4. **豁免收紧联动**：若本批删除了豁免条目，同步下调
   `tools/check_exemption_baseline.py` 的 `BASELINE_PAIRS` 与
   `pyproject.toml` 快照，并运行该脚本确认通过。
5. **留痕**：每批通过后立即提交（pre-commit hook 自动运行全量
   `check.bat` 并向 `.git/check-audit.log` 追加审计记录）。
6. **推进**：回到第 2 步处理下一批。
7. **收尾**：全部批次完成后，在仓库根运行一次完整 `check.bat`
   确认整体通过。

### 验证器

- 批内：第 3 步的聚焦 ruff / pytest 命令
- 批间：pre-commit 强制的全量 `check.bat`
- 收尾：仓库根全量 `check.bat`

### 停止规则

- 同一批聚焦检查连续 2 次失败且原因不明 → 停止该批，向用户报告
  失败输出；禁止通过添加 `# noqa` 或扩大豁免绕过
- 修复引发计划外的公开 API / 行为变化 → 停止并向用户确认
  （第十一节禁止项）
- 全部批次完成且 `check.bat` 通过 → 循环结束

