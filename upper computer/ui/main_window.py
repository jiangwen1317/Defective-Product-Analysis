"""
机械臂上位机 - 主窗口界面（PyQt5）。

专业级监控系统界面，采用两栏布局设计：
- 左侧面板（固定 380-480px）：测试控制、测试进度、通讯日志
- 右侧面板（弹性扩展）：设备连接、DUT状态、任务详情、历史统计

架构说明：
- Gateway 在独立线程运行
- 回调通过 pyqtSignal 安全传递到主线程（跨线程 emit 自动排队到主线程执行）
- 使用统一的样式系统
"""

import logging
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

# 将项目根目录添加到模块搜索路径
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from adapters import TC3720Status
from ui.components import (
    Card,
    ConnectionStatus,
    DutGridPanel,
    StatsPanel,
    TestProgressPanel,
)
from config import get_configured_dut_indices, get_gateway_config, get_ui_config, load_config
from router import ErrorCode, GatewayState, SignalGateway, TransferRecord
from ui.styles import (
    COLOR_ACCENT,
    COLOR_ACCENT_HOVER,
    COLOR_BG_PRIMARY,
    COLOR_BG_TERTIARY,
    COLOR_BORDER,
    COLOR_ERROR,
    COLOR_IDLE,
    COLOR_SUCCESS,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    FONT_MONO,
    FONT_SIZE_BASE,
    FONT_SIZE_SM,
    RADIUS_MD,
    RADIUS_SM,
    SPACING_LG,
    SPACING_MD,
    secondary_button_style,
    test_button_style,
)

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """机械臂上位机主窗口。

    采用两栏布局的专业级监控系统界面（左侧测试区 + 右侧状态区）。
    """

    # 跨线程通信信号：网关回调在工作线程触发，通过信号转发到主线程执行 UI 更新
    # （pyqtSignal.emit 是 Qt 官方保证线程安全的机制，跨线程连接自动排队）
    _sig_state_changed = pyqtSignal(object)   # GatewayState
    _sig_arm_connected = pyqtSignal(bool)
    _sig_dut_status = pyqtSignal(int, object)  # dut_index, TC3720Status
    _sig_record = pyqtSignal(object)           # TransferRecord
    _sig_error = pyqtSignal(object, str)       # ErrorCode, message
    _sig_test_started = pyqtSignal(str, str, object)    # group, bitmask, dut_indices
    _sig_dut_result = pyqtSignal(int, str)              # dut_index, error_code
    _sig_test_finished = pyqtSignal(str, object, float)  # group, results, duration
    _sig_service_done = pyqtSignal(bool, bool, str)     # is_start, ok, message

    def __init__(self) -> None:
        """初始化主窗口。"""
        super().__init__()

        # 配置加载
        self._config = load_config()
        self._ui_config = get_ui_config(self._config)
        self._gateway_config = get_gateway_config(self._config)

        # 网关实例
        self._gateway: SignalGateway | None = None

        # 统计数据（按测试会话统计：全部 0000 记成功，否则记失败）
        self._stats = {"total": 0, "success": 0, "failed": 0}

        # 启停服务在后台线程执行，执行期间禁止重入
        self._service_busy = False

        # 日志（使用 deque 自动限制长度）
        self._log_buffer: deque[str] = deque(maxlen=self._ui_config.get("log_max_lines", 5000))

        # UI 控件引用（初始化为 None，便于安全检查）
        self._arm_connection: ConnectionStatus | None = None
        self._alarm_card: Card | None = None
        self._task_group_label: QLabel | None = None

        # 跨线程信号接线（需先于网关初始化，确保回调触发时槽已就绪）
        self._sig_state_changed.connect(self._update_flow_display_safe)
        self._sig_arm_connected.connect(self._update_arm_display_safe)
        self._sig_dut_status.connect(self._update_dut_display_safe)
        self._sig_record.connect(self._update_transfer_display_safe)
        self._sig_error.connect(self._update_error_display_safe)
        self._sig_test_started.connect(self._update_test_started_safe)
        self._sig_dut_result.connect(self._update_dut_result_safe)
        self._sig_test_finished.connect(self._update_test_finished_safe)
        self._sig_service_done.connect(self._on_service_done_safe)

        # 窗口初始化
        self._init_ui()
        self._init_gateway()

    def _init_ui(self) -> None:
        """初始化界面布局。"""
        self.setWindowTitle("机械臂中转网关 v2.0")
        self.setGeometry(
            100, 100,
            self._ui_config.get("window_width", 1200),
            self._ui_config.get("window_height", 800),
        )

        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 标题栏
        main_layout.addWidget(self._create_header())

        # 内容区域 - 两栏布局（响应式）
        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(SPACING_LG, SPACING_MD, SPACING_LG, SPACING_LG)
        content_layout.setSpacing(SPACING_LG)

        # 左侧主测试区（最小380px，最大480px，窗口大时自动扩展）
        left_panel = self._create_left_panel()
        left_panel.setMinimumWidth(380)
        left_panel.setMaximumWidth(480)
        # 使用 Preferred + Expanding 策略，让左侧在范围内弹性
        left_policy = left_panel.sizePolicy()
        left_policy.setHorizontalPolicy(QSizePolicy.Preferred)
        left_policy.setHorizontalStretch(0)  # 不参与弹性拉伸
        left_panel.setSizePolicy(left_policy)

        # 右侧状态区（始终填满剩余空间）
        right_panel = self._create_right_panel()
        right_policy = right_panel.sizePolicy()
        right_policy.setHorizontalPolicy(QSizePolicy.Expanding)
        right_policy.setHorizontalStretch(1)
        right_panel.setSizePolicy(right_policy)

        content_layout.addWidget(left_panel)
        content_layout.addWidget(right_panel, 1)

        main_layout.addWidget(content, 1)

    def _create_header(self) -> QWidget:
        """创建标题栏。"""
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet(f"""
            QWidget {{
                background-color: #0d1117;
                border-bottom: 1px solid #21262d;
            }}
        """)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 16, 0)

        # 标题 - 简洁有力
        title_label = QLabel("机械臂中转网关")
        title_label.setStyleSheet("""
            color: #e6edf3;
            font-size: 15px;
            font-weight: 600;
            letter-spacing: 0.3px;
        """)
        layout.addWidget(title_label)

        layout.addStretch()

        # 服务状态 - 紧凑胶囊样式
        self._header_status_label = QLabel("● 服务未启动")
        self._header_status_label.setStyleSheet("""
            color: #6e7681;
            font-size: 12px;
            padding: 5px 14px;
            background-color: #21262d;
            border-radius: 14px;
        """)
        layout.addWidget(self._header_status_label)

        layout.addSpacing(12)

        # 统计信息 - 简化显示
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(16)

        self._header_total_label = QLabel("0 次")
        self._header_total_label.setStyleSheet("color: #6e7681; font-size: 12px;")
        stats_layout.addWidget(self._header_total_label)

        self._header_success_label = QLabel("✓ 0")
        self._header_success_label.setStyleSheet("color: #22c55e; font-size: 12px; font-weight: 500;")
        stats_layout.addWidget(self._header_success_label)

        self._header_failed_label = QLabel("✗ 0")
        self._header_failed_label.setStyleSheet("color: #ef4444; font-size: 12px; font-weight: 500;")
        stats_layout.addWidget(self._header_failed_label)

        layout.addLayout(stats_layout)

        layout.addSpacing(12)

        # 启动/停止按钮 - 优化样式
        self._service_btn = QPushButton("▶ 启动服务")
        self._service_btn.setFixedSize(90, 30)
        self._service_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_SUCCESS};
                color: white;
                border: none;
                border-radius: {RADIUS_SM};
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: #16a34a;
            }}
        """)
        self._service_btn.clicked.connect(self._on_toggle_service)
        layout.addWidget(self._service_btn)

        return header

    def _create_left_panel(self) -> QWidget:
        """创建左侧面板（主测试区）。

        包含测试控制卡片和通讯日志卡片。
        """
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)  # 紧凑间距

        # 测试控制卡片（核心功能）
        test_control_card = self._create_test_control_card()
        layout.addWidget(test_control_card)

        # 测试进度面板
        test_progress_card = Card("测试进度")
        progress_layout = test_progress_card.content_layout()

        configured_duts = get_configured_dut_indices(self._config)
        self._test_progress_panel = TestProgressPanel(dut_indices=configured_duts)
        progress_layout.addWidget(self._test_progress_panel)

        layout.addWidget(test_progress_card)

        # 通讯日志卡片（占满剩余空间）
        log_card = self._create_log_card()
        layout.addWidget(log_card, 1)

        return panel

    def _create_test_control_card(self) -> QWidget:
        """创建测试控制卡片（核心主动测试功能）。"""
        card = Card("测试控制")
        layout = card.content_layout()
        layout.setSpacing(8)

        # 获取已配置的 DUT 列表
        self._configured_duts = get_configured_dut_indices(self._config)

        # 测试说明（紧凑）
        if self._configured_duts:
            desc_text = f"已配置 {len(self._configured_duts)} 个板子"
        else:
            desc_text = "请在 config.json 中配置 DUT"
        desc_label = QLabel(desc_text)
        desc_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(desc_label)

        # 板子复选框 - 紧凑布局
        self._board_checkboxes: list[QCheckBox] = []
        checkbox_row1 = QHBoxLayout()
        checkbox_row1.setSpacing(12)
        checkbox_row2 = QHBoxLayout()
        checkbox_row2.setSpacing(12)

        checkbox_style = f"""
            QCheckBox {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: 12px;
                spacing: 4px;
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
                border-radius: 3px;
                border: 1px solid {COLOR_BORDER};
                background-color: {COLOR_BG_TERTIARY};
            }}
            QCheckBox::indicator:checked {{
                background-color: {COLOR_ACCENT};
                border-color: {COLOR_ACCENT};
            }}
            QCheckBox::indicator:checked:hover {{
                background-color: {COLOR_ACCENT_HOVER};
                border-color: {COLOR_ACCENT_HOVER};
            }}
        """

        for i, dut_index in enumerate(self._configured_duts):
            checkbox = QCheckBox(f"#{dut_index}")
            checkbox.setChecked(True)
            checkbox.setStyleSheet(checkbox_style)
            self._board_checkboxes.append(checkbox)
            if i < 4:
                checkbox_row1.addWidget(checkbox)
            else:
                checkbox_row2.addWidget(checkbox)

        checkbox_row1.addStretch()
        layout.addLayout(checkbox_row1)
        layout.addLayout(checkbox_row2)

        # 快捷按钮行（紧凑）
        quick_btn_row = QHBoxLayout()
        quick_btn_row.setSpacing(8)

        dut_count = len(self._configured_duts)

        select_all_btn = QPushButton(f"全选({dut_count})")
        select_all_btn.setFixedSize(64, 24)
        select_all_btn.setStyleSheet(secondary_button_style())
        select_all_btn.clicked.connect(self._on_select_all_boards)
        quick_btn_row.addWidget(select_all_btn)

        clear_btn = QPushButton("清空")
        clear_btn.setFixedSize(48, 24)
        clear_btn.setStyleSheet(secondary_button_style())
        clear_btn.clicked.connect(self._on_clear_all_boards)
        quick_btn_row.addWidget(clear_btn)

        quick_btn_row.addStretch()
        layout.addLayout(quick_btn_row)

        # 触发测试按钮
        self._trigger_btn = QPushButton("▶ 触发测试")
        self._trigger_btn.setFixedHeight(40)
        self._trigger_btn.setStyleSheet(test_button_style())
        self._trigger_btn.clicked.connect(self._on_trigger_test)
        layout.addWidget(self._trigger_btn)

        # 提示信息（紧凑）
        hint_label = QLabel("💡 发送 @TEST_DONE 指令")
        hint_label.setStyleSheet("color: #6b7280; font-size: 10px;")
        layout.addWidget(hint_label)

        return card

    def _create_log_card(self) -> QWidget:
        """创建通讯日志卡片。"""
        card = Card("通讯日志")
        layout = card.content_layout()

        # 工具栏（紧凑）
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._auto_scroll_combo = QComboBox()
        self._auto_scroll_combo.addItems(["自动滚动", "固定滚动"])
        self._auto_scroll_combo.setCurrentIndex(0)
        self._auto_scroll_combo.setFixedWidth(100)
        self._auto_scroll_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {RADIUS_SM};
                padding: 3px 6px;
                font-size: 11px;
            }}
        """)
        toolbar.addWidget(self._auto_scroll_combo)

        toolbar.addStretch()

        clear_btn = QPushButton("清空")
        clear_btn.setFixedSize(44, 22)
        clear_btn.setStyleSheet(secondary_button_style())
        clear_btn.clicked.connect(self._on_clear_log)
        toolbar.addWidget(clear_btn)

        export_btn = QPushButton("导出")
        export_btn.setFixedSize(44, 22)
        export_btn.setStyleSheet(secondary_button_style())
        export_btn.clicked.connect(self._on_export_log)
        toolbar.addWidget(export_btn)

        layout.addLayout(toolbar)

        # 日志文本区（文档行数与 _log_buffer 同上限，
        # 防止长期运行时富文本文档无限膨胀导致内存增长与界面卡顿）
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.document().setMaximumBlockCount(self._log_buffer.maxlen or 5000)
        self._log_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLOR_BG_PRIMARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {RADIUS_MD};
                font-family: {FONT_MONO};
                font-size: 11px;
                padding: 6px;
            }}
        """)
        layout.addWidget(self._log_text, 1)

        return card

    def _create_right_panel(self) -> QWidget:
        """创建右侧面板（状态区）。

        布局优化：
        - 上部：连接状态 + DUT状态（固定高度，不滚动）
        - 中部：任务详情（紧凑布局）
        - 下部：历史统计（弹性占用剩余空间）
        - 告警：合并到任务详情行内
        """
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)  # 减小卡片间距

        # ===== 顶部区域：连接状态 + DUT状态（水平布局）=====
        top_container = QWidget()
        top_layout = QHBoxLayout(top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        # 连接状态卡片（只显示机械臂）
        conn_card = Card("设备连接")
        conn_layout = conn_card.content_layout()

        conn_row = QHBoxLayout()
        conn_row.setSpacing(16)

        self._arm_connection = ConnectionStatus("机械臂")
        conn_row.addWidget(self._arm_connection)

        conn_row.addStretch()
        conn_layout.addLayout(conn_row)
        top_layout.addWidget(conn_card, 0)  # 固定宽度，不弹性

        # DUT 状态网格卡片
        dut_card = Card("DUT 状态")
        dut_layout = dut_card.content_layout()

        configured_duts = get_configured_dut_indices(self._config)
        self._dut_grid_panel = DutGridPanel(dut_indices=configured_duts)
        dut_layout.addWidget(self._dut_grid_panel)
        top_layout.addWidget(dut_card, 2)  # 弹性比例2（更宽）

        layout.addWidget(top_container)

        # ===== 中部区域：任务详情 + 告警（合并为一行）=====
        middle_container = QWidget()
        middle_layout = QHBoxLayout(middle_container)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(8)

        # 当前任务卡片（紧凑）
        self._task_card = Card("任务详情")
        task_layout = self._task_card.content_layout()
        task_layout.setSpacing(6)

        # 任务信息 - 单行紧凑布局
        task_row1 = QHBoxLayout()
        task_row1.setSpacing(12)

        # Group
        g_layout = QVBoxLayout()
        g_layout.setSpacing(2)
        g_label = QLabel("Group")
        g_label.setStyleSheet("color: #6b7280; font-size: 10px;")
        self._task_group_label = QLabel("-")
        self._task_group_label.setStyleSheet("color: #3b82f6; font-size: 12px; font-family: monospace; font-weight: 600;")
        g_layout.addWidget(g_label)
        g_layout.addWidget(self._task_group_label)
        task_row1.addLayout(g_layout)

        # Bitmask
        b_layout = QVBoxLayout()
        b_layout.setSpacing(2)
        b_label = QLabel("Bitmask")
        b_label.setStyleSheet("color: #6b7280; font-size: 10px;")
        self._task_bitmask_label = QLabel("-")
        self._task_bitmask_label.setStyleSheet("color: #3b82f6; font-size: 12px; font-family: monospace; font-weight: 600;")
        b_layout.addWidget(b_label)
        b_layout.addWidget(self._task_bitmask_label)
        task_row1.addLayout(b_layout)

        # ErrorCodes
        e_layout = QVBoxLayout()
        e_layout.setSpacing(2)
        e_label = QLabel("ErrorCodes")
        e_label.setStyleSheet("color: #6b7280; font-size: 10px;")
        self._task_errorcodes_label = QLabel("-")
        self._task_errorcodes_label.setStyleSheet("color: #e8eaed; font-size: 11px; font-family: monospace;")
        e_layout.addWidget(e_label)
        e_layout.addWidget(self._task_errorcodes_label)
        task_row1.addLayout(e_layout)

        task_row1.addStretch()
        task_layout.addLayout(task_row1)

        # 第二行：耗时 + 状态
        task_row2 = QHBoxLayout()
        task_row2.setSpacing(12)

        d_layout = QVBoxLayout()
        d_layout.setSpacing(2)
        d_label = QLabel("耗时")
        d_label.setStyleSheet("color: #6b7280; font-size: 10px;")
        self._task_duration_label = QLabel("-")
        self._task_duration_label.setStyleSheet("color: #e8eaed; font-size: 12px; font-family: monospace;")
        d_layout.addWidget(d_label)
        d_layout.addWidget(self._task_duration_label)
        task_row2.addLayout(d_layout)

        s_layout = QVBoxLayout()
        s_layout.setSpacing(2)
        s_label = QLabel("状态")
        s_label.setStyleSheet("color: #6b7280; font-size: 10px;")

        # 状态标签：带背景和emoji
        self._gw_status_container = QWidget()
        self._gw_status_container.setStyleSheet("""
            background-color: #252530;
            border-radius: 4px;
            padding: 2px 8px;
        """)
        status_container_layout = QHBoxLayout(self._gw_status_container)
        status_container_layout.setContentsMargins(4, 2, 4, 2)
        status_container_layout.setSpacing(4)

        self._gw_status_emoji = QLabel("⚪")
        self._gw_status_emoji.setStyleSheet("font-size: 10px;")
        status_container_layout.addWidget(self._gw_status_emoji)

        self._gw_status_label = QLabel("空闲")
        self._gw_status_label.setStyleSheet("color: #6b7280; font-size: 11px; font-weight: 600;")
        status_container_layout.addWidget(self._gw_status_label)

        s_layout.addWidget(s_label)
        s_layout.addWidget(self._gw_status_container)
        task_row2.addLayout(s_layout)

        task_row2.addStretch()
        task_layout.addLayout(task_row2)

        middle_layout.addWidget(self._task_card, 3)  # 弹性比例3

        # 告警卡片（紧凑，仅在有告警时显示）
        self._alarm_card = Card("告警")
        self._alarm_layout = self._alarm_card.content_layout()
        self._alarm_layout.setSpacing(6)

        alarm_content = QHBoxLayout()
        alarm_content.setSpacing(8)

        self._alarm_label = QLabel("无")
        self._alarm_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        alarm_content.addWidget(self._alarm_label)

        self._clear_alarm_btn = QPushButton("清除")
        self._clear_alarm_btn.setFixedSize(48, 24)
        self._clear_alarm_btn.setStyleSheet("""
            QPushButton {
                background-color: #ef4444;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #dc2626;
            }
        """)
        self._clear_alarm_btn.clicked.connect(self._on_clear_alarm)
        alarm_content.addWidget(self._clear_alarm_btn)
        self._alarm_layout.addLayout(alarm_content)
        self._alarm_card.setVisible(False)
        self._alarm_card.setFixedWidth(140)  # 固定宽度，紧凑

        middle_layout.addWidget(self._alarm_card)

        layout.addWidget(middle_container)

        # ===== 底部区域：历史统计（弹性占用）=====
        stats_card = Card("历史统计")
        stats_layout = stats_card.content_layout()

        self._stats_panel = StatsPanel()
        stats_layout.addWidget(self._stats_panel)

        layout.addWidget(stats_card, 1)  # 弹性扩展，填满剩余空间

        return panel

    def _init_gateway(self) -> None:
        """初始化网关实例。"""
        try:
            self._gateway = SignalGateway(
                config=self._gateway_config,
                on_state_changed=self._on_gateway_state_changed,
                on_arm_connected=self._on_arm_connected,
                on_dut_status_changed=self._on_dut_status_changed,
                on_test_started=self._on_test_started,
                on_dut_result=self._on_dut_result,
                on_test_finished=self._on_test_finished,
                on_record=self._on_transfer_record,
                on_error=self._on_gateway_error,
            )
            logger.info("网关实例初始化成功")
        except Exception as e:
            logger.error("网关实例初始化失败: %s", e)
            logger.debug("初始化失败详情:", exc_info=True)

    def _on_toggle_service(self) -> None:
        """切换服务状态（启停在后台线程执行，避免设备连接/串口初始化阻塞 UI）。"""
        if self._gateway is None or self._service_busy:
            return

        is_start = not self._gateway.is_running
        self._service_busy = True
        self._service_btn.setEnabled(False)
        self._service_btn.setText("启动中..." if is_start else "停止中...")

        threading.Thread(
            target=self._service_worker,
            args=(is_start,),
            name="UI-ServiceWorker",
            daemon=True,
        ).start()

    def _service_worker(self, is_start: bool) -> None:
        """后台执行网关启停（工作线程，完成后经信号回主线程刷新 UI）。"""
        message = ""
        try:
            if is_start:
                ok = self._gateway.start()
            else:
                self._gateway.stop()
                ok = True
        except Exception as e:
            logger.exception("网关%s失败: %s", "启动" if is_start else "停止", e)
            ok = False
            message = str(e)
        self._sig_service_done.emit(is_start, ok, message)

    def _on_service_done_safe(self, is_start: bool, ok: bool, message: str) -> None:
        """网关启停完成后的 UI 更新（主线程安全）。"""
        self._service_busy = False
        self._service_btn.setEnabled(True)

        if is_start and ok:
            self._apply_service_started_ui()
            # 主动更新所有设备状态（解决初始状态不显示的问题）
            self._update_all_device_status()
            self._log("系统", "中转服务已启动，等待机械臂连接...")
        elif is_start:
            self._apply_service_stopped_ui()
            self._log("错误", f"启动网关失败: {message}" if message else "启动网关失败")
        else:
            self._apply_service_stopped_ui()
            self._log("系统", "中转服务已停止")

    def _apply_service_started_ui(self) -> None:
        """应用"服务运行中"的界面状态。"""
        # 更新按钮
        self._service_btn.setText("■ 停止服务")
        self._service_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_ERROR};
                color: white;
                border: none;
                border-radius: {RADIUS_SM};
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: #dc2626;
            }}
        """)

        # 更新标题栏状态
        self._header_status_label.setText("● 服务运行中")
        self._header_status_label.setStyleSheet("""
            color: #22c55e;
            font-size: 12px;
            padding: 5px 14px;
            background-color: #21262d;
            border-radius: 14px;
        """)

        # 更新网关状态标签
        if hasattr(self, '_gw_status_label'):
            self._gw_status_label.setText("空闲")
            if hasattr(self, '_gw_status_emoji'):
                self._gw_status_emoji.setText("⚪")

    def _update_all_device_status(self) -> None:
        """主动更新所有设备状态（解决初始状态不显示的问题）。"""
        if self._gateway is None:
            logger.warning("_update_all_device_status: gateway 未初始化")
            return

        try:
            # 获取所有设备状态摘要
            status_summary = self._gateway.get_device_status_summary()
            logger.debug("[UI状态] 设备状态摘要: %s", status_summary)

            # 检查 DUT 网格是否存在
            if not hasattr(self, '_dut_grid_panel') or self._dut_grid_panel is None:
                logger.warning("[UI状态] DUT网格未初始化")
                return

            # 检查摘要是否为空
            if not status_summary:
                logger.warning("[UI状态] 设备状态摘要为空，可能设备未连接")
                return

            # 检查 DUT 网格中实际包含的 DUT
            dut_indices_in_grid = list(self._dut_grid_panel._dut_widgets.keys()) if hasattr(self._dut_grid_panel, '_dut_widgets') else []
            logger.debug("[UI状态] DUT网格中的DUT: %s", dut_indices_in_grid)

            for dut_index, status_info in status_summary.items():
                status = status_info.get("status", "offline").upper()
                is_online = status_info.get("online", False)

                # 映射状态
                if status == "TESTING":
                    dut_status = "testing"
                elif status == "IDLE" and is_online:
                    dut_status = "online"
                elif status == "ERROR":
                    dut_status = "error"
                else:
                    dut_status = "offline"

                # 检查 DUT 是否在网格中
                if dut_index not in dut_indices_in_grid:
                    logger.warning("[UI状态] DUT#%d 不在UI网格中，跳过更新", dut_index)
                    continue

                logger.debug("[UI状态] DUT#%d: status=%s, online=%s -> %s (调用set_dut_status)",
                           dut_index, status, is_online, dut_status)

                # 调用 DUT 网格面板更新状态
                self._dut_grid_panel.set_dut_status(dut_index, dut_status)
                logger.debug("[UI状态] DUT#%d set_dut_status 调用完成", dut_index)

        except Exception as e:
            logger.exception("更新设备状态失败: %s", e)

    def _apply_service_stopped_ui(self) -> None:
        """应用"服务未启动"的界面状态。"""
        # 更新按钮
        self._service_btn.setText("▶ 启动服务")
        self._service_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_SUCCESS};
                color: white;
                border: none;
                border-radius: {RADIUS_SM};
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: #16a34a;
            }}
        """)

        # 更新标题栏状态
        self._header_status_label.setText("● 服务未启动")
        self._header_status_label.setStyleSheet("""
            color: #6e7681;
            font-size: 12px;
            padding: 5px 14px;
            background-color: #21262d;
            border-radius: 14px;
        """)

        # 重置显示
        self._arm_connection.set_status("offline")

        # 重置 DUT 网格
        if hasattr(self, '_dut_grid_panel'):
            self._dut_grid_panel.reset_all()

        # 重置测试进度面板
        if hasattr(self, '_test_progress_panel'):
            self._test_progress_panel.reset()

        # 更新网关状态标签
        if hasattr(self, '_gw_status_label'):
            self._gw_status_label.setText("空闲")
            self._gw_status_label.setStyleSheet(f"color: {COLOR_IDLE}; font-size: {FONT_SIZE_SM}; font-weight: 500;")

    def _on_clear_alarm(self) -> None:
        """清除告警。"""
        if self._gateway:
            self._gateway.clear_alarm()

        if self._alarm_card:
            self._alarm_card.setVisible(False)
        if hasattr(self, '_clear_alarm_btn') and self._clear_alarm_btn:
            self._clear_alarm_btn.setVisible(False)
        self._log("系统", "告警已清除")

    def _on_trigger_test(self) -> None:
        """主动触发测试（发送 @TEST_DONE 命令）。"""
        if self._gateway is None:
            self._log("错误", "网关未初始化")
            return

        if not self._gateway.is_running:
            self._log("错误", "网关未启动，无法触发测试")
            return

        if not self._gateway.is_arm_connected:
            self._log("错误", "机械臂未连接，无法触发测试")
            return

        # 获取用户选择的板子列表（复选框按 _configured_duts 顺序创建，
        # 勾选序号不等于板号，必须按位置映射回真实 DUT 编号）
        checked = [checkbox.isChecked() for checkbox in self._board_checkboxes]
        selected_boards = self._map_selected_boards(self._configured_duts, checked)

        if not selected_boards:
            self._log("错误", "请至少选择一个板子")
            return

        # 发送触发命令
        success = self._gateway.trigger_test(boards_to_test=selected_boards)

        if success:
            boards_str = "、".join([f"板子{i}" for i in selected_boards])
            self._log("触发", f"已发送 @TEST_DONE 触发命令（测试 {boards_str}），等待机械臂响应...")
        else:
            self._log("错误", "发送触发命令失败")

    @staticmethod
    def _map_selected_boards(configured_duts: list[int], checked: list[bool]) -> list[int]:
        """将复选框勾选状态映射为真实 DUT 编号列表。

        Args:
            configured_duts: 已配置的 DUT 编号列表（与复选框一一对应）。
            checked: 各复选框的勾选状态。

        Returns:
            被勾选的 DUT 编号列表（如配置 [3, 5] 且全勾选时返回 [3, 5]）。
        """
        return [dut for dut, is_checked in zip(configured_duts, checked) if is_checked]

    def _on_select_all_boards(self) -> None:
        """全选所有已配置的板子。"""
        for checkbox in self._board_checkboxes:
            checkbox.setChecked(True)

    def _on_clear_all_boards(self) -> None:
        """清空所有板子选择。"""
        for checkbox in self._board_checkboxes:
            checkbox.setChecked(False)

    def _on_gateway_state_changed(self, state: GatewayState) -> None:
        """网关状态变化回调（工作线程触发，经信号转发到主线程）。"""
        self._sig_state_changed.emit(state)

    def _update_flow_display_safe(self, state: GatewayState) -> None:
        """更新网关状态显示（主线程安全）。"""
        try:
            # 更新网关状态标签
            state_texts = {
                GatewayState.IDLE: "空闲",
                GatewayState.FORWARDING: "测试中",
                GatewayState.ERROR: "异常",
            }
            state_colors = {
                GatewayState.IDLE: "#6b7280",      # 灰色
                GatewayState.FORWARDING: "#f59e0b", # 橙色
                GatewayState.ERROR: "#ef4444",     # 红色
            }
            state_emojis = {
                GatewayState.IDLE: "⚪",
                GatewayState.FORWARDING: "🟡",
                GatewayState.ERROR: "🔴",
            }

            if hasattr(self, '_gw_status_label') and self._gw_status_label is not None:
                self._gw_status_label.setText(state_texts.get(state, "未知"))
                self._gw_status_label.setStyleSheet(
                    f"color: {state_colors.get(state, '#e8eaed')}; "
                    f"font-size: 11px; font-weight: 600;"
                )
                # 更新emoji
                if hasattr(self, '_gw_status_emoji'):
                    self._gw_status_emoji.setText(state_emojis.get(state, "⚪"))
        except Exception as e:
            logger.exception("更新网关状态显示失败: %s", e)

    def _on_arm_connected(self, connected: bool) -> None:
        """机械臂连接状态变化回调（工作线程触发，经信号转发到主线程）。"""
        self._sig_arm_connected.emit(connected)

    def _update_arm_display_safe(self, connected: bool) -> None:
        """更新机械臂显示（主线程安全）。"""
        try:
            # 检查控件是否已初始化
            if self._arm_connection is None:
                logger.warning("机械臂显示控件未初始化，跳过状态更新")
                return

            if connected:
                self._arm_connection.set_status("online")
                if self._gateway and self._gateway.arm_client_address:
                    self._arm_connection.set_status("online", self._gateway.arm_client_address)
                self._log("连接", "机械臂已连接")
            else:
                self._arm_connection.set_status("offline")
                self._log("连接", "机械臂已断开")
        except Exception as e:
            logger.exception("更新机械臂显示失败: %s", e)

    def _on_dut_status_changed(self, dut_index: int, status: TC3720Status) -> None:
        """单个 DUT 状态变化回调（线程安全）。

        Args:
            dut_index: DUT 编号 (1-8)。
            status: 新状态。
        """
        # 通过信号转发，确保在主线程执行
        self._sig_dut_status.emit(dut_index, status)

    def _update_dut_display_safe(self, dut_index: int, status: TC3720Status) -> None:
        """更新单个 DUT 显示（主线程安全）。

        Args:
            dut_index: DUT 编号 (1-8)。
            status: 新状态。
        """
        try:
            # 使用 status.value 进行映射，避免枚举对象不匹配的问题
            status_value = status.value if hasattr(status, 'value') else str(status)

            status_map = {
                "offline": "offline",
                "idle": "online",
                "testing": "testing",
                "error": "error",
            }
            mapped_status = status_map.get(status_value, "offline")

            logger.debug("[UI回调] _update_dut_display_safe: dut=%d, status_value=%s -> mapped=%s",
                       dut_index, status_value, mapped_status)

            # 更新 DUT 网格面板
            if hasattr(self, '_dut_grid_panel') and self._dut_grid_panel is not None:
                self._dut_grid_panel.set_dut_status(dut_index, mapped_status)
        except Exception as e:
            logger.exception("更新 DUT#%d 显示失败: %s", dut_index, e)

    def _on_transfer_record(self, record: TransferRecord) -> None:
        """中转记录回调（工作线程触发，经信号转发到主线程）。"""
        self._sig_record.emit(record)

    def _update_transfer_display_safe(self, record: TransferRecord) -> None:
        """更新传输显示（主线程安全）。

        Args:
            record: 中转记录
        """
        try:
            # 检查控件是否已初始化
            if self._task_group_label is None:
                logger.warning("任务显示控件未初始化，跳过传输更新")
                return

            # 根据方向显示日志（会话级统计在 _update_test_finished_safe 中更新）
            if record.direction == "arm_to_3720":
                self._log(
                    "发送",
                    f"透传 → 3720 [{record.size} 字节]: {record.raw_data!r}",
                )
            elif record.direction == "3720_to_arm":
                self._log(
                    "接收",
                    f"透传 ← 3720 [{record.size} 字节]: {record.raw_data!r}",
                )
            else:
                self._log("记录", f"[{record.size} 字节]: {record.raw_data!r}")

            if record.error_code != ErrorCode.NONE:
                self._log("异常", f"中转异常 - {record.error_code.value}: {record.error_message}")
        except Exception as e:
            logger.exception("更新传输显示失败: %s", e)

    def _update_stats_display(self) -> None:
        """更新统计显示（按测试会话统计）。"""
        total = self._stats["total"]
        success = self._stats["success"]
        failed = self._stats["failed"]

        self._header_total_label.setText(f"{total} 次")
        self._header_success_label.setText(f"✓ {success}")
        self._header_failed_label.setText(f"✗ {failed}")

        self._stats_panel.update_stats(total, success, failed)

    def _on_gateway_error(self, error_code: ErrorCode, message: str) -> None:
        """网关错误回调（工作线程触发，经信号转发到主线程）。"""
        self._sig_error.emit(error_code, message)

    def _update_error_display_safe(self, error_code: ErrorCode, message: str) -> None:
        """更新错误显示（主线程安全）。

        Args:
            error_code: 错误码
            message: 错误消息
        """
        try:
            # 检查控件是否已初始化
            if self._alarm_card is None or not hasattr(self, '_alarm_label'):
                logger.warning("告警显示控件未初始化，跳过错误更新")
                return

            # 显示告警（简化文本以适应紧凑布局）
            self._alarm_card.setVisible(True)
            if hasattr(self, '_clear_alarm_btn') and self._clear_alarm_btn:
                self._clear_alarm_btn.setVisible(True)
            # 截断过长的消息
            display_msg = message[:30] + "..." if len(message) > 30 else message
            self._alarm_label.setText(f"[{error_code.value}] {display_msg}")
            self._alarm_label.setStyleSheet("color: #ef4444; font-size: 11px;")

            # 告警指示灯
            if error_code == ErrorCode.ARM_DISCONNECTED:
                self._arm_connection.set_status("error")

            self._log("错误", f"[{error_code.value}] {message}")
        except Exception as e:
            logger.exception("更新错误显示失败: %s", e)

    def _on_test_started(self, group: str, bitmask: str, dut_indices: list[int]) -> None:
        """测试会话开始回调（工作线程触发，经信号转发到主线程）。"""
        self._sig_test_started.emit(group, bitmask, dut_indices)

    def _update_test_started_safe(self, group: str, bitmask: str, dut_indices: list[int]) -> None:
        """更新测试会话开始显示（主线程安全）。

        Args:
            group: 组号。
            bitmask: DUT 位掩码。
            dut_indices: 本次受测的 DUT 编号列表。
        """
        try:
            self._test_progress_panel.start_test(dut_indices)

            if self._task_group_label is not None:
                self._task_group_label.setText(group)
                self._task_bitmask_label.setText(bitmask)
                self._task_errorcodes_label.setText("-")
                self._task_duration_label.setText("-")

            duts_str = "、".join(f"#{d}" for d in dut_indices)
            self._log("系统", f"测试会话开始 - Bitmask: {bitmask}，受测 DUT: {duts_str}")
        except Exception as e:
            logger.exception("更新测试开始显示失败: %s", e)

    def _on_dut_result(self, dut_index: int, error_code: str) -> None:
        """单 DUT 结果回调（工作线程触发，经信号转发到主线程）。"""
        self._sig_dut_result.emit(dut_index, error_code)

    def _update_dut_result_safe(self, dut_index: int, error_code: str) -> None:
        """更新单 DUT 测试结果显示（主线程安全）。"""
        try:
            self._test_progress_panel.update_dut_result(dut_index, error_code)
        except Exception as e:
            logger.exception("更新 DUT#%d 结果显示失败: %s", dut_index, e)

    def _on_test_finished(self, group: str, results: dict[int, str], duration: float) -> None:
        """测试会话结束回调（工作线程触发，经信号转发到主线程）。"""
        self._sig_test_finished.emit(group, results, duration)

    def _update_test_finished_safe(self, group: str, results: dict[int, str], duration: float) -> None:
        """更新测试会话结束显示（主线程安全）。

        Args:
            group: 组号。
            results: 本次受测 DUT 的结果字典 {dut_index: error_code}。
            duration: 会话耗时（秒）。
        """
        try:
            self._test_progress_panel.complete_test(results)

            if self._task_errorcodes_label is not None:
                codes_text = " ".join(f"#{d}:{results[d]}" for d in sorted(results))
                self._task_errorcodes_label.setText(codes_text or "-")
                self._task_duration_label.setText(f"{duration:.1f} s")

            # 会话级统计：全部 0000 记成功，否则记失败
            self._stats["total"] += 1
            if results and all(code == "0000" for code in results.values()):
                self._stats["success"] += 1
            else:
                self._stats["failed"] += 1
            self._update_stats_display()

            passed = sum(1 for code in results.values() if code == "0000")
            self._log("完成", f"测试会话结束 - {passed}/{len(results)} 通过，耗时 {duration:.1f}s")
        except Exception as e:
            logger.exception("更新测试完成显示失败: %s", e)

    def _log(self, level: str, message: str) -> None:
        """添加日志条目（仅限主线程调用；网关回调均经 pyqtSignal 转发到主线程）。"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        # 颜色映射
        colors = {
            "系统": "#888899",
            "连接": "#22c55e",
            "接收": "#3b82f6",
            "发送": "#f59e0b",
            "完成": "#06b6d4",
            "异常": "#ef4444",
            "错误": "#ef4444",
            "调试": "#a855f7",
        }
        color = colors.get(level, "#9ca3af")

        # 格式化文本
        line = f'<span style="color: #4b5563;">[{timestamp}]</span> '
        line += f'<span style="color: {color};">[{level}]</span> '
        line += f'<span style="color: #e5e7eb;">{message}</span>'

        self._log_text.append(line)
        self._log_buffer.append(f"[{timestamp}] [{level}] {message}")

        # 自动滚动
        if self._auto_scroll_combo.currentIndex() == 0:
            self._log_text.verticalScrollBar().setValue(
                self._log_text.verticalScrollBar().maximum()
            )

    def _on_clear_log(self) -> None:
        """清空日志。"""
        self._log_text.clear()
        self._log_buffer.clear()

    def _on_export_log(self) -> None:
        """导出日志。"""
        from PyQt5.QtWidgets import QFileDialog

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "导出日志",
            f"gateway_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Text Files (*.txt);;All Files (*)",
        )

        if filename:
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write("\n".join(self._log_buffer))
                self._log("系统", f"日志已导出: {filename}")
            except Exception as e:
                QMessageBox.warning(self, "导出失败", str(e))

    def closeEvent(self, event: QCloseEvent) -> None:
        """窗口关闭事件（退出时同步停止网关，允许短暂阻塞）。"""
        if self._gateway and self._gateway.is_running:
            self._gateway.stop()

        event.accept()


def _show_startup_error(message: str) -> None:
    """显示启动失败弹窗（配置错误等致命异常）。"""
    QMessageBox.critical(None, "启动失败", message)


def main() -> None:
    """启动 GUI 应用。

    Note:
        日志已在 main.py 的 setup_logging() 中配置，
        此处不应重复配置。
    """
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    # 设置暗色主题
    app.setStyleSheet(f"""
        QWidget {{
            background-color: {COLOR_BG_PRIMARY};
            color: {COLOR_TEXT_PRIMARY};
            font-family: 'Segoe UI', 'Microsoft YaHei', Arial, sans-serif;
            font-size: {FONT_SIZE_BASE};
        }}

        QScrollBar:vertical {{
            background-color: transparent;
            width: 8px;
            border-radius: 4px;
            margin: 2px;
        }}

        QScrollBar::handle:vertical {{
            background-color: {COLOR_TEXT_MUTED};
            border-radius: 4px;
            min-height: 20px;
        }}

        QScrollBar::handle:vertical:hover {{
            background-color: {COLOR_TEXT_SECONDARY};
        }}

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}

        QScrollBar:horizontal {{
            background-color: transparent;
            height: 8px;
            border-radius: 4px;
            margin: 2px;
        }}

        QScrollBar::handle:horizontal {{
            background-color: {COLOR_TEXT_MUTED};
            border-radius: 4px;
            min-width: 20px;
        }}

        QScrollBar::handle:horizontal:hover {{
            background-color: {COLOR_TEXT_SECONDARY};
        }}

        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
    """)

    # 配置缺失/损坏时 get_gateway_config 会抛 ValueError，
    # 必须弹窗告知用户而非黑框闪退
    try:
        window = MainWindow()
    except Exception as e:
        logger.exception("主窗口初始化失败: %s", e)
        _show_startup_error(
            f"程序启动失败：{e}\n\n请检查 config.json 配置后重试。"
        )
        sys.exit(1)

    window.show()

    try:
        sys.exit(app.exec_())
    except KeyboardInterrupt:
        window.close()


if __name__ == "__main__":
    main()