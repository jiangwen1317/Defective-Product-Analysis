"""
机械臂上位机 - 主窗口界面（PyQt5）。

专业级监控系统界面，采用三栏布局设计：
- 左侧面板：服务状态、连接状态、配置信息
- 中部区域：实时流程状态机、当前任务、统计数据
- 右侧区域：通讯日志、调试工具

架构说明：
- Gateway 在独立线程运行
- 回调通过 QMetaObject.invokeMethod 安全传递到主线程
- 使用统一的样式系统
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

# 将项目根目录添加到模块搜索路径
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
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
    StatusIndicator,
    TestProgressPanel,
)
from config import get_gateway_config, get_ui_config, load_config
from router import ErrorCode, GatewayState, SignalGateway, TransferRecord
from ui.styles import (
    COLOR_ACCENT,
    COLOR_ACCENT_HOVER,
    COLOR_BG_PRIMARY,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_BORDER,
    COLOR_ERROR,
    COLOR_IDLE,
    COLOR_INFO,
    COLOR_PROCESSING,
    COLOR_SUCCESS,
    COLOR_TEST_ACTIVE,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    FONT_MONO,
    FONT_SIZE_BASE,
    FONT_SIZE_LG,
    FONT_SIZE_SM,
    FONT_SIZE_XL,
    FONT_SIZE_XS,
    RADIUS_MD,
    RADIUS_SM,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
    SPACING_XL,
    SPACING_XS,
    secondary_button_style,
    test_button_style,
)

logger = logging.getLogger(__name__)

# 状态配置（透传模式）
STATE_CONFIG = {
    GatewayState.IDLE: {"text": "空闲", "color": COLOR_IDLE, "icon": "○"},
    GatewayState.FORWARDING: {"text": "透传中", "color": COLOR_INFO, "icon": "◉"},
    GatewayState.ERROR: {"text": "异常", "color": COLOR_ERROR, "icon": "●"},
}


class MainWindow(QMainWindow):
    """机械臂上位机主窗口。

    采用三栏布局的专业级监控系统界面。
    """

    def __init__(self) -> None:
        """初始化主窗口。"""
        super().__init__()

        # 配置加载
        self._config = load_config()
        self._ui_config = get_ui_config(self._config)
        self._gateway_config = get_gateway_config(self._config)

        # 网关实例
        self._gateway: SignalGateway | None = None

        # 统计数据
        self._stats = {"total": 0, "success": 0, "failed": 0}

        # 日志
        self._log_buffer: list[str] = []

        # UI 控件引用（初始化为 None，便于安全检查）
        self._flow_icons: dict[GatewayState, QLabel] | None = None
        self._flow_nodes: dict[GatewayState, QWidget] | None = None
        self._arm_connection: ConnectionStatus | None = None
        self._tc3720_connection: ConnectionStatus | None = None
        self._alarm_card: Card | None = None
        self._task_group_label: QLabel | None = None
        self._dut_connections: dict[int, ConnectionStatus] = {}  # DUT 状态字典

        # 窗口初始化
        self._init_ui()
        self._init_gateway()

        # 状态更新定时器
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._on_timer_tick)
        self._update_timer.start(100)

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

        # 内容区域 - 两栏布局
        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(SPACING_LG, SPACING_MD, SPACING_LG, SPACING_LG)
        content_layout.setSpacing(SPACING_LG)

        # 左侧主测试区（固定宽度 380px）
        left_panel = self._create_left_panel()
        left_panel.setFixedWidth(380)
        content_layout.addWidget(left_panel)

        # 右侧状态区（弹性拉伸）
        right_panel = self._create_right_panel()
        content_layout.addWidget(right_panel, 1)

        main_layout.addWidget(content, 1)

    def _create_header(self) -> QWidget:
        """创建标题栏。"""
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(f"""
            QWidget {{
                background-color: {COLOR_BG_SECONDARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
        """)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(SPACING_LG, 0, SPACING_LG, 0)

        # 标题
        title_label = QLabel("机械臂中转网关")
        title_label.setStyleSheet(f"""
            color: {COLOR_TEXT_PRIMARY};
            font-size: {FONT_SIZE_LG};
            font-weight: bold;
        """)
        layout.addWidget(title_label)

        layout.addStretch()

        # 服务状态（紧凑显示）
        status_layout = QHBoxLayout()
        status_layout.setSpacing(SPACING_SM)

        self._header_service_indicator = StatusIndicator("offline", 8)
        status_layout.addWidget(self._header_service_indicator)

        self._header_status_label = QLabel("服务未启动")
        self._header_status_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM};")
        status_layout.addWidget(self._header_status_label)

        layout.addLayout(status_layout)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"background-color: {COLOR_BORDER}; max-width: 1px;")
        sep.setFixedWidth(1)
        layout.addWidget(sep)

        # 统计信息（紧凑）
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(SPACING_MD)

        self._header_total_label = QLabel("总数: 0")
        self._header_total_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: {FONT_SIZE_SM};")
        stats_layout.addWidget(self._header_total_label)

        self._header_success_label = QLabel("✓ 0")
        self._header_success_label.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: {FONT_SIZE_SM};")
        stats_layout.addWidget(self._header_success_label)

        self._header_failed_label = QLabel("✗ 0")
        self._header_failed_label.setStyleSheet(f"color: {COLOR_ERROR}; font-size: {FONT_SIZE_SM};")
        stats_layout.addWidget(self._header_failed_label)

        layout.addLayout(stats_layout)

        # 分隔线
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet(f"background-color: {COLOR_BORDER}; max-width: 1px;")
        sep2.setFixedWidth(1)
        layout.addWidget(sep2)

        # 启动/停止按钮
        self._service_btn = QPushButton("▶ 启动服务")
        self._service_btn.setFixedSize(100, 32)
        self._service_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_SUCCESS};
                color: white;
                border: none;
                border-radius: {RADIUS_SM};
                font-size: {FONT_SIZE_SM};
                font-weight: bold;
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
        layout.setSpacing(SPACING_MD)

        # 测试控制卡片（核心功能）
        test_control_card = self._create_test_control_card()
        layout.addWidget(test_control_card)

        # 测试进度面板
        test_progress_card = Card("测试进度")
        progress_layout = test_progress_card.content_layout()

        self._test_progress_panel = TestProgressPanel()
        progress_layout.addWidget(self._test_progress_panel)

        layout.addWidget(test_progress_card)

        # 通讯日志卡片（占满剩余空间）
        log_card = self._create_log_card()
        layout.addWidget(log_card, 1)

        return panel

    def _create_test_control_card(self) -> QWidget:
        """创建测试控制卡片（核心主动测试功能）。"""
        card = Card("⏵ 主动测试控制")
        layout = card.content_layout()
        layout.setSpacing(SPACING_SM)

        # 测试说明
        desc_label = QLabel("选择要测试的 DUT 板子，点击按钮触发测试")
        desc_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_XS};")
        layout.addWidget(desc_label)

        # 板子复选框 - 使用简单的 HBoxLayout 代替 GridLayout
        self._board_checkboxes: list[QCheckBox] = []
        checkbox_row1 = QHBoxLayout()
        checkbox_row1.setSpacing(SPACING_SM)
        checkbox_row2 = QHBoxLayout()
        checkbox_row2.setSpacing(SPACING_SM)

        for i in range(1, 9):
            checkbox = QCheckBox(f"板子{i}")
            checkbox.setChecked(i <= 2)  # 默认勾选前两个
            checkbox.setStyleSheet(f"""
                QCheckBox {{
                    color: {COLOR_TEXT_PRIMARY};
                    font-size: {FONT_SIZE_SM};
                }}
                QCheckBox::indicator {{
                    width: 16px;
                    height: 16px;
                    border-radius: 3px;
                    border: 1px solid {COLOR_BORDER};
                    background-color: {COLOR_BG_TERTIARY};
                }}
                QCheckBox::indicator:checked {{
                    background-color: {COLOR_ACCENT};
                    border-color: {COLOR_ACCENT};
                }}
            """)
            self._board_checkboxes.append(checkbox)
            if i <= 4:
                checkbox_row1.addWidget(checkbox)
            else:
                checkbox_row2.addWidget(checkbox)

        layout.addLayout(checkbox_row1)
        layout.addLayout(checkbox_row2)

        # 快捷按钮行
        quick_btn_row = QHBoxLayout()
        quick_btn_row.setSpacing(SPACING_SM)

        select_all_btn = QPushButton("全选")
        select_all_btn.setFixedSize(56, 26)
        select_all_btn.setStyleSheet(secondary_button_style())
        select_all_btn.clicked.connect(self._on_select_all_boards)
        quick_btn_row.addWidget(select_all_btn)

        board1_2_btn = QPushButton("前两个")
        board1_2_btn.setFixedSize(56, 26)
        board1_2_btn.setStyleSheet(secondary_button_style())
        board1_2_btn.clicked.connect(self._on_select_board1_2)
        quick_btn_row.addWidget(board1_2_btn)

        clear_btn = QPushButton("清空")
        clear_btn.setFixedSize(56, 26)
        clear_btn.setStyleSheet(secondary_button_style())
        clear_btn.clicked.connect(self._on_clear_all_boards)
        quick_btn_row.addWidget(clear_btn)

        quick_btn_row.addStretch()
        layout.addLayout(quick_btn_row)

        # 触发测试按钮（大号主按钮）
        self._trigger_btn = QPushButton("▶ 主动触发测试")
        self._trigger_btn.setFixedHeight(44)
        self._trigger_btn.setStyleSheet(test_button_style())
        self._trigger_btn.clicked.connect(self._on_trigger_test)
        layout.addWidget(self._trigger_btn)

        # 提示信息
        hint_label = QLabel("💡 发送 @TEST_DONE 触发机械臂开始测试流程")
        hint_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_XS};")
        layout.addWidget(hint_label)

        return card

    def _create_log_card(self) -> QWidget:
        """创建通讯日志卡片。"""
        card = Card("📋 通讯日志")
        layout = card.content_layout()

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(SPACING_SM)

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
                padding: 4px 8px;
                font-size: {FONT_SIZE_SM};
            }}
        """)
        toolbar.addWidget(self._auto_scroll_combo)

        toolbar.addStretch()

        clear_btn = QPushButton("清空")
        clear_btn.setFixedSize(50, 24)
        clear_btn.setStyleSheet(secondary_button_style())
        clear_btn.clicked.connect(self._on_clear_log)
        toolbar.addWidget(clear_btn)

        export_btn = QPushButton("导出")
        export_btn.setFixedSize(50, 24)
        export_btn.setStyleSheet(secondary_button_style())
        export_btn.clicked.connect(self._on_export_log)
        toolbar.addWidget(export_btn)

        layout.addLayout(toolbar)

        # 日志文本区
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLOR_BG_PRIMARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {RADIUS_MD};
                font-family: {FONT_MONO};
                font-size: {FONT_SIZE_SM};
                padding: {SPACING_SM};
            }}
        """)
        layout.addWidget(self._log_text, 1)

        return card

    def _create_center_panel(self) -> QWidget:
        """创建中部面板（兼容旧代码）。"""
        return self._create_right_panel()

    def _create_right_panel(self) -> QWidget:
        """创建右侧面板（状态区）。"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_MD)

        # 连接状态卡片（简化版）
        conn_card = Card("设备连接状态")
        conn_layout = conn_card.content_layout()

        # 机械臂和 TC3720 连接状态
        conn_row = QHBoxLayout()
        conn_row.setSpacing(SPACING_LG)

        self._arm_connection = ConnectionStatus("机械臂")
        conn_row.addWidget(self._arm_connection)

        self._tc3720_connection = ConnectionStatus("TC3720")
        conn_row.addWidget(self._tc3720_connection)

        conn_row.addStretch()
        conn_layout.addLayout(conn_row)

        layout.addWidget(conn_card)

        # DUT 状态网格卡片（核心状态显示）
        dut_card = Card("DUT 状态监控")
        dut_layout = dut_card.content_layout()

        self._dut_grid_panel = DutGridPanel()
        dut_layout.addWidget(self._dut_grid_panel)

        layout.addWidget(dut_card)

        # 当前任务卡片
        self._task_card = Card("当前任务详情")
        task_layout = self._task_card.content_layout()
        task_layout.setSpacing(SPACING_SM)

        # 任务信息网格
        task_info_layout = QGridLayout()
        task_info_layout.setSpacing(SPACING_MD)

        # Group 行
        group_label = QLabel("Group:")
        group_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM};")
        task_info_layout.addWidget(group_label, 0, 0)

        self._task_group_label = QLabel("-")
        self._task_group_label.setStyleSheet(f"color: {COLOR_ACCENT}; font-size: {FONT_SIZE_SM}; font-weight: bold; font-family: {FONT_MONO};")
        task_info_layout.addWidget(self._task_group_label, 0, 1)

        # Bitmask 行
        bitmask_label = QLabel("Bitmask:")
        bitmask_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM};")
        task_info_layout.addWidget(bitmask_label, 0, 2)

        self._task_bitmask_label = QLabel("-")
        self._task_bitmask_label.setStyleSheet(f"color: {COLOR_ACCENT}; font-size: {FONT_SIZE_SM}; font-weight: bold; font-family: {FONT_MONO};")
        task_info_layout.addWidget(self._task_bitmask_label, 0, 3)

        # ErrorCodes 行
        error_label = QLabel("ErrorCodes:")
        error_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM};")
        task_info_layout.addWidget(error_label, 1, 0)

        self._task_errorcodes_label = QLabel("-")
        self._task_errorcodes_label.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: {FONT_SIZE_SM}; font-family: {FONT_MONO};")
        task_info_layout.addWidget(self._task_errorcodes_label, 1, 1, 1, 3)

        # 耗时行
        duration_label = QLabel("耗时:")
        duration_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM};")
        task_info_layout.addWidget(duration_label, 2, 0)

        self._task_duration_label = QLabel("-")
        self._task_duration_label.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: {FONT_SIZE_SM}; font-family: {FONT_MONO};")
        task_info_layout.addWidget(self._task_duration_label, 2, 1)

        # 网关状态
        gw_status_label = QLabel("状态:")
        gw_status_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM};")
        task_info_layout.addWidget(gw_status_label, 2, 2)

        self._gw_status_label = QLabel("空闲")
        self._gw_status_label.setStyleSheet(f"color: {COLOR_IDLE}; font-size: {FONT_SIZE_SM}; font-weight: 500;")
        task_info_layout.addWidget(self._gw_status_label, 2, 3)

        task_layout.addLayout(task_info_layout)
        layout.addWidget(self._task_card)

        # 告警卡片
        self._alarm_card = Card("⚠ 告警信息")
        self._alarm_layout = self._alarm_card.content_layout()
        self._alarm_label = QLabel("无告警")
        self._alarm_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM};")
        self._alarm_layout.addWidget(self._alarm_label)

        self._clear_alarm_btn = QPushButton("清除告警")
        self._clear_alarm_btn.setFixedHeight(28)
        self._clear_alarm_btn.setVisible(False)
        self._clear_alarm_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_ERROR};
                color: white;
                border: none;
                border-radius: {RADIUS_SM};
                font-size: {FONT_SIZE_SM};
            }}
            QPushButton:hover {{
                background-color: #dc2626;
            }}
        """)
        self._clear_alarm_btn.clicked.connect(self._on_clear_alarm)
        self._alarm_layout.addWidget(self._clear_alarm_btn)
        self._alarm_card.setVisible(False)

        layout.addWidget(self._alarm_card)

        # 历史统计卡片
        stats_card = Card("历史统计")
        stats_layout = stats_card.content_layout()

        self._stats_panel = StatsPanel()
        stats_layout.addWidget(self._stats_panel)

        layout.addWidget(stats_card)

        layout.addStretch()

        return panel

    def _create_flow_diagram(self) -> QWidget:
        """创建流程状态图（保留兼容但不再使用）。"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_SM)

        # 状态节点（透传模式）
        states = [
            GatewayState.IDLE,
            GatewayState.FORWARDING,
        ]

        self._flow_nodes = {}
        self._flow_icons = {}

        for i, state in enumerate(states):
            config = STATE_CONFIG[state]

            # 节点行
            node_row = QWidget()
            node_layout = QHBoxLayout(node_row)
            node_layout.setContentsMargins(0, SPACING_XS, 0, SPACING_XS)
            node_layout.setSpacing(SPACING_MD)

            # 步骤编号
            step_label = QLabel(f"{i + 1}")
            step_label.setFixedSize(24, 24)
            step_label.setAlignment(Qt.AlignCenter)
            step_label.setStyleSheet(f"""
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_MUTED};
                border-radius: 12px;
                font-size: {FONT_SIZE_SM};
                font-weight: bold;
            """)
            node_layout.addWidget(step_label)

            # 状态图标
            icon_label = QLabel(config["icon"])
            icon_label.setStyleSheet(f"""
                color: {COLOR_TEXT_MUTED};
                font-size: 18px;
            """)
            self._flow_icons[state] = icon_label
            node_layout.addWidget(icon_label)

            # 状态文字
            state_label = QLabel(config["text"])
            state_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM};")
            node_layout.addWidget(state_label)

            node_layout.addStretch()

            # 保存节点引用
            self._flow_nodes[state] = node_row

            layout.addWidget(node_row)

            # 连接线
            if i < len(states) - 1:
                line = QFrame()
                line.setFrameShape(QFrame.VLine)
                line.setStyleSheet(f"""
                    background-color: {COLOR_BORDER};
                    border: 1px dashed {COLOR_BORDER};
                    max-height: 20px;
                """)
                line.setFixedHeight(20)
                layout.addWidget(line)

        return widget

    def _init_gateway(self) -> None:
        """初始化网关实例。"""
        try:
            self._gateway = SignalGateway(
                config=self._gateway_config,
                on_state_changed=self._on_gateway_state_changed,
                on_arm_connected=self._on_arm_connected,
                on_3720_status_changed=self._on_3720_status_changed,
                on_dut_status_changed=self._on_dut_status_changed,  # 单个 DUT 状态回调
                on_record=self._on_transfer_record,
                on_error=self._on_gateway_error,
            )
            logger.info("网关实例初始化成功")
        except Exception as e:
            logger.error("网关实例初始化失败: %s", e)
            import traceback
            traceback.print_exc()

    def _on_timer_tick(self) -> None:
        """定时器回调。"""
        pass

    def _on_toggle_service(self) -> None:
        """切换服务状态。"""
        if self._gateway is None:
            return

        if self._gateway.is_running:
            self._stop_gateway()
        else:
            self._start_gateway()

    def _start_gateway(self) -> None:
        """启动网关服务。"""
        if self._gateway is None or self._gateway.is_running:
            return

        try:
            result = self._gateway.start()
        except Exception as e:
            import traceback
            self._log("错误", f"启动异常: {e}\n{traceback.format_exc()}")
            return

        if result:
            # 更新按钮
            self._service_btn.setText("■ 停止服务")
            self._service_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLOR_ERROR};
                    color: white;
                    border: none;
                    border-radius: {RADIUS_SM};
                    font-size: {FONT_SIZE_SM};
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: #dc2626;
                }}
            """)

            # 更新标题栏状态
            self._header_service_indicator.set_status("online")
            self._header_status_label.setText("服务运行中")
            self._header_status_label.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: {FONT_SIZE_SM};")

            # 更新网关状态标签
            if hasattr(self, '_gw_status_label'):
                self._gw_status_label.setText("空闲")
                self._gw_status_label.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: {FONT_SIZE_SM}; font-weight: 500;")

            self._log("系统", "中转服务已启动，等待机械臂连接...")
        else:
            self._log("错误", "启动网关失败")

    def _stop_gateway(self) -> None:
        """停止网关服务。"""
        if self._gateway is None or not self._gateway.is_running:
            return

        self._gateway.stop()

        # 更新按钮
        self._service_btn.setText("▶ 启动服务")
        self._service_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_SUCCESS};
                color: white;
                border: none;
                border-radius: {RADIUS_SM};
                font-size: {FONT_SIZE_SM};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #16a34a;
            }}
        """)

        # 更新标题栏状态
        self._header_service_indicator.set_status("offline")
        self._header_status_label.setText("服务未启动")
        self._header_status_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM};")

        self._log("系统", "中转服务已停止")

        # 重置显示
        self._arm_connection.set_status("offline")
        self._tc3720_connection.set_status("offline")

        # 重置 DUT 网格
        if hasattr(self, '_dut_grid_panel'):
            self._dut_grid_panel.reset_all()

        # 重置测试进度面板
        if hasattr(self, '_test_progress_panel'):
            self._test_progress_panel.reset()

        # 重置流程显示
        self._reset_flow_display()

        # 更新网关状态标签
        if hasattr(self, '_gw_status_label'):
            self._gw_status_label.setText("空闲")
            self._gw_status_label.setStyleSheet(f"color: {COLOR_IDLE}; font-size: {FONT_SIZE_SM}; font-weight: 500;")

    def _reset_flow_display(self) -> None:
        """重置流程显示。"""
        # 新布局中可能没有流程图控件，跳过更新
        if self._flow_icons is None or self._flow_nodes is None:
            return

        for state, icon_label in self._flow_icons.items():
            icon_label.setText(STATE_CONFIG[state]["icon"])
            icon_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 18px;")

        # 重置步骤编号样式
        for state in STATE_CONFIG.keys():
            step_label = self._flow_nodes[state].layout().itemAt(0).widget()
            step_label.setStyleSheet(f"""
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_MUTED};
                border-radius: 12px;
                font-size: {FONT_SIZE_SM};
                font-weight: bold;
            """)

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

        # 获取用户选择的板子列表
        selected_boards = []
        for i, checkbox in enumerate(self._board_checkboxes, start=1):
            if checkbox.isChecked():
                selected_boards.append(i)

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

    def _on_select_all_boards(self) -> None:
        """全选所有板子。"""
        for checkbox in self._board_checkboxes:
            checkbox.setChecked(True)

    def _on_clear_all_boards(self) -> None:
        """清空所有板子选择。"""
        for checkbox in self._board_checkboxes:
            checkbox.setChecked(False)

    def _on_select_board1_2(self) -> None:
        """只选择前两个板子。"""
        for i, checkbox in enumerate(self._board_checkboxes):
            checkbox.setChecked(i < 2)

    def _on_gateway_state_changed(self, state: GatewayState) -> None:
        """网关状态变化回调（线程安全）。"""
        QTimer.singleShot(0, lambda s=state: self._update_flow_display_safe(s))

    def _update_flow_display_safe(self, state: GatewayState) -> None:
        """更新流程显示（主线程安全）。"""
        try:
            # 更新网关状态标签（即使没有流程图也要更新）
            state_texts = {
                GatewayState.IDLE: "空闲",
                GatewayState.FORWARDING: "测试中",
                GatewayState.ERROR: "异常",
            }
            state_colors = {
                GatewayState.IDLE: COLOR_IDLE,
                GatewayState.FORWARDING: COLOR_INFO,
                GatewayState.ERROR: COLOR_ERROR,
            }

            if hasattr(self, '_gw_status_label') and self._gw_status_label is not None:
                self._gw_status_label.setText(state_texts.get(state, "未知"))
                self._gw_status_label.setStyleSheet(
                    f"color: {state_colors.get(state, COLOR_TEXT_PRIMARY)}; "
                    f"font-size: {FONT_SIZE_SM}; font-weight: 500;"
                )

            # 检查流程图控件是否已初始化
            if self._flow_icons is None or self._flow_nodes is None:
                return

            # 更新所有节点
            for s, icon_label in self._flow_icons.items():
                config = STATE_CONFIG[s]
                step_label = self._flow_nodes[s].layout().itemAt(0).widget()

                if s == state:
                    icon_label.setText("●")
                    icon_label.setStyleSheet(f"color: {config['color']}; font-size: 18px; font-weight: bold;")
                    step_label.setStyleSheet(f"""
                        background-color: {config['color']};
                        color: white;
                        border-radius: 12px;
                        font-size: {FONT_SIZE_SM};
                        font-weight: bold;
                    """)
                elif s.value < state.value:
                    icon_label.setText("●")
                    icon_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 18px; opacity: 0.5;")
                    step_label.setStyleSheet(f"""
                        background-color: {COLOR_TEXT_MUTED};
                        color: {COLOR_BG_PRIMARY};
                        border-radius: 12px;
                        font-size: {FONT_SIZE_SM};
                        font-weight: bold;
                        opacity: 0.5;
                    """)
                else:
                    icon_label.setText(STATE_CONFIG[s]["icon"])
                    icon_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 18px;")
                    step_label.setStyleSheet(f"""
                        background-color: {COLOR_BG_TERTIARY};
                        color: {COLOR_TEXT_MUTED};
                        border-radius: 12px;
                        font-size: {FONT_SIZE_SM};
                        font-weight: bold;
                    """)
        except Exception as e:
            logger.error("更新流程显示失败: %s", e)
            import traceback
            traceback.print_exc()

    def _on_arm_connected(self, connected: bool) -> None:
        """机械臂连接状态变化回调（线程安全）。"""
        QTimer.singleShot(0, lambda c=connected: self._update_arm_display_safe(c))

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
            logger.error("更新机械臂显示失败: %s", e)
            import traceback
            traceback.print_exc()

    def _on_3720_status_changed(self, status: TC3720Status) -> None:
        """3720 状态变化回调（线程安全）。

        使用 QTimer.singleShot 将 UI 更新调度到主线程。
        """
        # 通过 QTimer.singleShot(0, ...) 确保在主线程执行
        QTimer.singleShot(0, lambda s=status: self._update_3720_display_safe(s))

    def _update_3720_display_safe(self, status: TC3720Status) -> None:
        """更新 3720 显示（主线程安全）。"""
        try:
            # 检查控件是否已初始化
            if self._tc3720_connection is None:
                logger.warning("3720 显示控件未初始化，跳过状态更新")
                return

            status_map = {
                TC3720Status.OFFLINE: "offline",
                TC3720Status.IDLE: "online",
                TC3720Status.TESTING: "testing",
                TC3720Status.ERROR: "error",
            }

            self._tc3720_connection.set_status(status_map.get(status, "offline"))
        except Exception as e:
            logger.error("更新 3720 显示失败: %s", e)
            import traceback
            traceback.print_exc()

    def _on_dut_status_changed(self, dut_index: int, status: TC3720Status) -> None:
        """单个 DUT 状态变化回调（线程安全）。

        Args:
            dut_index: DUT 编号 (1-8)。
            status: 新状态。
        """
        # 通过 QTimer.singleShot(0, ...) 确保在主线程执行
        QTimer.singleShot(0, lambda di=dut_index, s=status: self._update_dut_display_safe(di, s))

    def _update_dut_display_safe(self, dut_index: int, status: TC3720Status) -> None:
        """更新单个 DUT 显示（主线程安全）。

        Args:
            dut_index: DUT 编号 (1-8)。
            status: 新状态。
        """
        try:
            status_map = {
                TC3720Status.OFFLINE: "offline",
                TC3720Status.IDLE: "online",
                TC3720Status.TESTING: "testing",
                TC3720Status.ERROR: "error",
            }
            mapped_status = status_map.get(status, "offline")

            # 更新 DUT 网格面板
            if hasattr(self, '_dut_grid_panel') and self._dut_grid_panel is not None:
                self._dut_grid_panel.set_dut_status(dut_index, mapped_status)

            # 兼容旧的连接状态字典（如果存在）
            if hasattr(self, '_dut_connections') and self._dut_connections and dut_index in self._dut_connections:
                self._dut_connections[dut_index].set_status(mapped_status)
        except Exception as e:
            logger.error("更新 DUT#%d 显示失败: %s", dut_index, e)
            import traceback
            traceback.print_exc()

    def _on_transfer_record(self, record: TransferRecord) -> None:
        """中转记录回调（线程安全）。

        使用 QTimer.singleShot 确保 UI 更新在主线程执行。
        """
        # 将 record 对象传递给主线程
        QTimer.singleShot(0, lambda r=record: self._update_transfer_display_safe(r))

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

            # 更新统计数据
            self._stats["total"] += 1

            # 根据方向显示日志
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
                self._stats["failed"] += 1
                self._log("异常", f"中转异常 - {record.error_code.value}: {record.error_message}")

            # 更新统计显示
            self._update_stats_display()
        except Exception as e:
            logger.error("更新传输显示失败: %s", e)
            import traceback
            traceback.print_exc()

    def _update_stats_display(self) -> None:
        """更新统计显示。"""
        total = self._stats["total"]
        success = self._stats["success"]
        failed = self._stats["failed"]

        self._header_total_label.setText(f"总数: {total}")
        self._header_success_label.setText(f"✓ {success}")
        self._header_failed_label.setText(f"✗ {failed}")

        self._stats_panel.update_stats(total, success, failed)

    def _on_gateway_error(self, error_code: ErrorCode, message: str) -> None:
        """网关错误回调（线程安全）。"""
        QTimer.singleShot(0, lambda e=error_code, m=message: self._update_error_display_safe(e, m))

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

            # 显示告警
            self._alarm_card.setVisible(True)
            if hasattr(self, '_clear_alarm_btn') and self._clear_alarm_btn:
                self._clear_alarm_btn.setVisible(True)
            self._alarm_label.setText(f"[{error_code.value}] {message}")
            self._alarm_label.setStyleSheet(f"color: {COLOR_ERROR}; font-size: {FONT_SIZE_SM};")

            # 告警指示灯
            if error_code == ErrorCode.ARM_DISCONNECTED:
                self._arm_connection.set_status("error")
            elif error_code == ErrorCode.TC3720_ERROR or error_code == ErrorCode.TIMEOUT_3720:
                self._tc3720_connection.set_status("error")

            self._log("错误", f"[{error_code.value}] {message}")
        except Exception as e:
            logger.error("更新错误显示失败: %s", e)
            import traceback
            traceback.print_exc()

    def _log(self, level: str, message: str) -> None:
        """添加日志条目（线程安全）。"""
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

        # 限制日志行数
        max_lines = self._ui_config.get("log_max_lines", 5000)
        if len(self._log_buffer) > max_lines:
            self._log_buffer = self._log_buffer[-max_lines:]

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

    def closeEvent(self, event: QEvent) -> None:
        """窗口关闭事件。"""
        if self._gateway and self._gateway.is_running:
            self._stop_gateway()

        self._update_timer.stop()
        event.accept()


def main() -> None:
    """启动 GUI 应用。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )

    app = QApplication(sys.argv)
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

    window = MainWindow()
    window.show()

    try:
        sys.exit(app.exec_())
    except KeyboardInterrupt:
        window.close()


if __name__ == "__main__":
    main()