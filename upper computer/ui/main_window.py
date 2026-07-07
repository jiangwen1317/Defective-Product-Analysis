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
import re
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
    QComboBox,
    QFrame,
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
from ui.components import Card, ConnectionStatus, StatsPanel, StatusIndicator
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

        # 窗口初始化
        self._init_ui()
        self._init_gateway()

        # 状态更新定时器
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._on_timer_tick)
        self._update_timer.start(100)

    def _init_ui(self) -> None:
        """初始化界面布局。"""
        self.setWindowTitle("机械臂中转网关 v1.0")
        self.setGeometry(
            100, 100,
            self._ui_config.get("window_width", 1400),
            self._ui_config.get("window_height", 900),
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

        # 内容区域
        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(SPACING_LG, SPACING_MD, SPACING_LG, SPACING_LG)
        content_layout.setSpacing(SPACING_LG)

        # 左侧面板
        left_panel = self._create_left_panel()
        left_panel.setFixedWidth(280)
        content_layout.addWidget(left_panel)

        # 中部区域
        center_widget = self._create_center_panel()
        content_layout.addWidget(center_widget, 1)

        # 右侧面板
        right_panel = self._create_right_panel()
        right_panel.setFixedWidth(420)
        content_layout.addWidget(right_panel)

        main_layout.addWidget(content, 1)

    def _create_header(self) -> QWidget:
        """创建标题栏。"""
        header = QWidget()
        header.setFixedHeight(60)
        header.setStyleSheet(f"""
            QWidget {{
                background-color: {COLOR_BG_SECONDARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
        """)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(SPACING_LG, 0, SPACING_LG, 0)

        # 标题
        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)

        title_label = QLabel("机械臂中转网关")
        title_label.setStyleSheet(f"""
            color: {COLOR_TEXT_PRIMARY};
            font-size: {FONT_SIZE_XL};
            font-weight: bold;
        """)
        title_layout.addWidget(title_label)

        subtitle_label = QLabel("ARM-TC3720 Signal Gateway")
        subtitle_label.setStyleSheet(f"""
            color: {COLOR_TEXT_MUTED};
            font-size: {FONT_SIZE_XS};
        """)
        title_layout.addWidget(subtitle_label)

        layout.addLayout(title_layout)

        # 服务状态
        self._header_status_layout = QHBoxLayout()
        self._header_status_layout.setSpacing(SPACING_LG)

        self._header_service_indicator = StatusIndicator("offline", 10)
        self._header_status_layout.addWidget(self._header_service_indicator)

        self._header_status_label = QLabel("服务未启动")
        self._header_status_label.setStyleSheet(f"""
            color: {COLOR_TEXT_MUTED};
            font-size: {FONT_SIZE_SM};
        """)
        self._header_status_layout.addWidget(self._header_status_label)

        layout.addLayout(self._header_status_layout)

        layout.addStretch()

        # 统计信息
        self._header_stats = QHBoxLayout()
        self._header_stats.setSpacing(SPACING_XL)

        self._header_total_label = QLabel("总传输: 0")
        self._header_total_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: {FONT_SIZE_SM};")
        self._header_stats.addWidget(self._header_total_label)

        self._header_success_label = QLabel("成功: 0")
        self._header_success_label.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: {FONT_SIZE_SM};")
        self._header_stats.addWidget(self._header_success_label)

        self._header_failed_label = QLabel("失败: 0")
        self._header_failed_label.setStyleSheet(f"color: {COLOR_ERROR}; font-size: {FONT_SIZE_SM};")
        self._header_stats.addWidget(self._header_failed_label)

        layout.addLayout(self._header_stats)

        # 启动/停止按钮
        self._service_btn = QPushButton("启动服务")
        self._service_btn.setFixedSize(100, 36)
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
        """创建左侧面板。"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_MD)

        # 连接状态卡片
        conn_card = Card("连接状态")
        conn_layout = conn_card.content_layout()

        self._arm_connection = ConnectionStatus("机械臂")
        conn_layout.addWidget(self._arm_connection)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background-color: {COLOR_BORDER};")
        sep.setFixedHeight(1)
        conn_layout.addWidget(sep)

        self._tc3720_connection = ConnectionStatus("TC3720 测试仪")
        conn_layout.addWidget(self._tc3720_connection)

        layout.addWidget(conn_card)

        # 网关配置卡片
        config_card = Card("网关配置")
        config_layout = config_card.content_layout()

        cfg = self._gateway_config
        config_items = [
            ("监听地址", f"{cfg.arm_host}:{cfg.arm_port}"),
            ("测试设备", "8 DUTs"),
            ("超时设置", f"{cfg.test_timeout}s"),
        ]

        for label, value in config_items:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, SPACING_XS, 0, SPACING_XS)

            label_widget = QLabel(label)
            label_widget.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM};")
            row_layout.addWidget(label_widget)
            row_layout.addStretch()

            value_widget = QLabel(value)
            value_widget.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: {FONT_SIZE_SM}; font-family: {FONT_MONO};")
            row_layout.addWidget(value_widget)

            config_layout.addWidget(row)

        layout.addWidget(config_card)

        # 告警卡片
        self._alarm_card = Card("告警信息")
        self._alarm_layout = self._alarm_card.content_layout()
        self._alarm_label = QLabel("无告警")
        self._alarm_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM};")
        self._alarm_layout.addWidget(self._alarm_label)

        self._clear_alarm_btn = QPushButton("清除告警")
        self._clear_alarm_btn.setFixedHeight(32)
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

        layout.addStretch()

        # 版本信息
        version_label = QLabel("v1.0 | threading 架构")
        version_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_XS};")
        layout.addWidget(version_label)

        return panel

    def _create_center_panel(self) -> QWidget:
        """创建中部面板。"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_MD)

        # 流程状态卡片
        flow_card = Card("实时流程状态")
        flow_layout = flow_card.content_layout()

        # 创建流程图
        self._flow_widget = self._create_flow_diagram()
        flow_layout.addWidget(self._flow_widget)

        layout.addWidget(flow_card)

        # 当前任务卡片
        self._task_card = Card("当前任务")
        task_layout = self._task_card.content_layout()
        task_layout.setSpacing(SPACING_SM)

        # Group 信息
        group_row = QWidget()
        group_layout = QHBoxLayout(group_row)
        group_layout.setContentsMargins(0, 0, 0, 0)

        group_label = QLabel("Group")
        group_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM}; min-width: 60px;")
        group_layout.addWidget(group_label)

        self._task_group_label = QLabel("-")
        self._task_group_label.setStyleSheet(f"color: {COLOR_ACCENT}; font-size: {FONT_SIZE_LG}; font-weight: bold; font-family: {FONT_MONO};")
        group_layout.addWidget(self._task_group_label)

        group_layout.addStretch()

        # Bitmask 信息
        bitmask_label = QLabel("Bitmask")
        bitmask_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM}; min-width: 60px;")
        group_layout.addWidget(bitmask_label)

        self._task_bitmask_label = QLabel("-")
        self._task_bitmask_label.setStyleSheet(f"color: {COLOR_ACCENT}; font-size: {FONT_SIZE_LG}; font-weight: bold; font-family: {FONT_MONO};")
        group_layout.addWidget(self._task_bitmask_label)

        task_layout.addWidget(group_row)

        # 错误码信息
        error_row = QWidget()
        error_layout = QHBoxLayout(error_row)
        error_layout.setContentsMargins(0, 0, 0, 0)

        error_code_label = QLabel("ErrorCodes")
        error_code_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM}; min-width: 60px;")
        error_layout.addWidget(error_code_label)

        self._task_errorcodes_label = QLabel("-")
        self._task_errorcodes_label.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: {FONT_SIZE_BASE}; font-family: {FONT_MONO};")
        error_layout.addWidget(self._task_errorcodes_label)

        error_layout.addStretch()

        # 耗时信息
        duration_label = QLabel("耗时")
        duration_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM}; min-width: 60px;")
        error_layout.addWidget(duration_label)

        self._task_duration_label = QLabel("-")
        self._task_duration_label.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: {FONT_SIZE_BASE}; font-family: {FONT_MONO};")
        error_layout.addWidget(self._task_duration_label)

        task_layout.addWidget(error_row)

        layout.addWidget(self._task_card)

        # 历史统计卡片
        stats_card = Card("历史统计")
        stats_layout = stats_card.content_layout()

        self._stats_panel = StatsPanel()
        stats_layout.addWidget(self._stats_panel)

        layout.addWidget(stats_card)

        layout.addStretch()

        return panel

    def _create_flow_diagram(self) -> QWidget:
        """创建流程状态图。"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_SM)

        # 状态节点（透传模式）
        states = [
            GatewayState.IDLE,
            GatewayState.FORWARDING,
        ]

        self._flow_nodes: dict[GatewayState, QWidget] = {}

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
            self._flow_icons: dict[GatewayState, QLabel] = {}
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

    def _create_right_panel(self) -> QWidget:
        """创建右侧面板。"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_MD)

        # 通讯日志卡片
        log_card = Card("通讯日志")
        log_layout = log_card.content_layout()

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
        clear_btn.setFixedSize(60, 28)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_SECONDARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {RADIUS_SM};
                font-size: {FONT_SIZE_SM};
            }}
            QPushButton:hover {{
                background-color: {COLOR_BG_SECONDARY};
            }}
        """)
        clear_btn.clicked.connect(self._on_clear_log)
        toolbar.addWidget(clear_btn)

        export_btn = QPushButton("导出")
        export_btn.setFixedSize(60, 28)
        export_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_SECONDARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {RADIUS_SM};
                font-size: {FONT_SIZE_SM};
            }}
            QPushButton:hover {{
                background-color: {COLOR_BG_SECONDARY};
            }}
        """)
        export_btn.clicked.connect(self._on_export_log)
        toolbar.addWidget(export_btn)

        log_layout.addLayout(toolbar)

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
        log_layout.addWidget(self._log_text, 1)

        layout.addWidget(log_card, 1)

        # 调试工具卡片
        self._debug_card = Card("调试工具")
        debug_layout = self._debug_card.content_layout()
        debug_layout.setSpacing(SPACING_SM)

        # 主动触发测试区域
        trigger_label = QLabel("主动测试模式")
        trigger_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: {FONT_SIZE_SM}; font-weight: bold;")
        debug_layout.addWidget(trigger_label)

        trigger_desc = QLabel("发送 @TEST_DONE 触发机械臂开始测试流程")
        trigger_desc.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_XS};")
        debug_layout.addWidget(trigger_desc)

        # 触发测试按钮
        trigger_btn = QPushButton("▶ 主动触发测试")
        trigger_btn.setFixedHeight(36)
        trigger_btn.setStyleSheet(f"""
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
        trigger_btn.clicked.connect(self._on_trigger_test)
        debug_layout.addWidget(trigger_btn)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background-color: {COLOR_BORDER}; max-height: 1px;")
        debug_layout.addWidget(sep)

        # 手动注入区域
        inject_label = QLabel("手动模拟模式")
        inject_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: {FONT_SIZE_SM}; font-weight: bold;")
        debug_layout.addWidget(inject_label)

        # Group 输入
        group_row = QHBoxLayout()
        group_row.setSpacing(SPACING_SM)

        group_label = QLabel("Group:")
        group_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM};")
        group_row.addWidget(group_label)

        self._debug_group_input = QLineEdit()
        self._debug_group_input.setPlaceholderText("00")
        self._debug_group_input.setFixedWidth(60)
        self._debug_group_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {RADIUS_SM};
                padding: 4px 8px;
                font-size: {FONT_SIZE_SM};
                font-family: {FONT_MONO};
            }}
        """)
        group_row.addWidget(self._debug_group_input)

        bitmask_label = QLabel("Bitmask:")
        bitmask_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM};")
        group_row.addWidget(bitmask_label)

        self._debug_bitmask_input = QLineEdit()
        self._debug_bitmask_input.setPlaceholderText("11000000")
        self._debug_bitmask_input.setFixedWidth(80)
        self._debug_bitmask_input.setText("11000000")  # 默认测试前两个 DUT
        self._debug_bitmask_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {RADIUS_SM};
                padding: 4px 8px;
                font-size: {FONT_SIZE_SM};
                font-family: {FONT_MONO};
            }}
        """)
        group_row.addWidget(self._debug_bitmask_input)

        group_row.addStretch()

        debug_layout.addLayout(group_row)

        # 注入按钮
        inject_btn = QPushButton("⚡ 模拟 START_TEST")
        inject_btn.setFixedHeight(32)
        inject_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_ACCENT};
                color: white;
                border: none;
                border-radius: {RADIUS_SM};
                font-size: {FONT_SIZE_SM};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLOR_ACCENT_HOVER};
            }}
        """)
        inject_btn.clicked.connect(self._on_inject_test_signal)
        debug_layout.addWidget(inject_btn)

        # 调试工具仅在调试模式下显示
        self._debug_card.setVisible(self._gateway_config.enable_debug)

        layout.addWidget(self._debug_card)

        return panel

    def _init_gateway(self) -> None:
        """初始化网关实例。"""
        self._gateway = SignalGateway(
            config=self._gateway_config,
            on_state_changed=self._on_gateway_state_changed,
            on_arm_connected=self._on_arm_connected,
            on_3720_status_changed=self._on_3720_status_changed,
            on_record=self._on_transfer_record,
            on_error=self._on_gateway_error,
        )

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
            self._service_btn.setText("停止服务")
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

            self._log("系统", "中转服务已启动")
        else:
            self._log("错误", "启动网关失败")

    def _stop_gateway(self) -> None:
        """停止网关服务。"""
        if self._gateway is None or not self._gateway.is_running:
            return

        self._gateway.stop()

        # 更新按钮
        self._service_btn.setText("启动服务")
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
        self._reset_flow_display()

    def _reset_flow_display(self) -> None:
        """重置流程显示。"""
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

        self._alarm_card.setVisible(False)
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

        # 发送触发命令
        success = self._gateway.trigger_test()

        if success:
            self._log("触发", "已发送 @TEST_DONE 触发命令，等待机械臂响应...")
        else:
            self._log("错误", "发送触发命令失败")

    def _on_inject_test_signal(self) -> None:
        """注入测试信号（调试用）。"""
        if self._gateway is None or not self._gateway.is_running:
            self._log("错误", "网关未启动，无法注入信号")
            return

        group = self._debug_group_input.text().strip().upper() or "00"
        bitmask = self._debug_bitmask_input.text().strip() or "11111111"

        # 验证输入
        if not re.match(r"^[0-9A-Fa-f]{2}$", group):
            self._log("错误", "Group 必须是2位十六进制数")
            return

        if not re.match(r"^[01]{8}$", bitmask):
            self._log("错误", "Bitmask 必须是8位二进制字符串")
            return

        self._gateway.on_start_test(group, bitmask)
        self._log("调试", f"已注入测试信号 - Group: {group}, Bitmask: {bitmask}")

    def _on_gateway_state_changed(self, state: GatewayState) -> None:
        """网关状态变化回调（线程安全）。"""
        QTimer.singleShot(0, lambda s=state: self._update_flow_display_safe(s))

    def _update_flow_display_safe(self, state: GatewayState) -> None:
        """更新流程显示（主线程安全）。"""
        # 检查控件是否已初始化
        if not hasattr(self, '_flow_icons') or not self._flow_icons:
            logger.warning("流程图控件未初始化，跳过状态更新")
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

    def _on_arm_connected(self, connected: bool) -> None:
        """机械臂连接状态变化回调（线程安全）。"""
        QTimer.singleShot(0, lambda c=connected: self._update_arm_display_safe(c))

    def _update_arm_display_safe(self, connected: bool) -> None:
        """更新机械臂显示（主线程安全）。"""
        # 检查控件是否已初始化
        if not hasattr(self, '_arm_connection') or self._arm_connection is None:
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

    def _on_3720_status_changed(self, status: TC3720Status) -> None:
        """3720 状态变化回调（线程安全）。

        使用 QTimer.singleShot 将 UI 更新调度到主线程。
        """
        # 通过 QTimer.singleShot(0, ...) 确保在主线程执行
        QTimer.singleShot(0, lambda s=status: self._update_3720_display_safe(s))

    def _update_3720_display_safe(self, status: TC3720Status) -> None:
        """更新 3720 显示（主线程安全）。"""
        # 检查控件是否已初始化
        if not hasattr(self, '_tc3720_connection') or self._tc3720_connection is None:
            logger.warning("3720 显示控件未初始化，跳过状态更新")
            return

        status_map = {
            TC3720Status.OFFLINE: "offline",
            TC3720Status.IDLE: "online",
            TC3720Status.TESTING: "testing",
            TC3720Status.ERROR: "error",
        }

        self._tc3720_connection.set_status(status_map.get(status, "offline"))

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
        # 检查控件是否已初始化
        if not hasattr(self, '_task_group_label') or self._task_group_label is None:
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

    def _update_stats_display(self) -> None:
        """更新统计显示。"""
        total = self._stats["total"]
        success = self._stats["success"]
        failed = self._stats["failed"]

        self._header_total_label.setText(f"总传输: {total}")
        self._header_success_label.setText(f"成功: {success}")
        self._header_failed_label.setText(f"失败: {failed}")

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
        # 检查控件是否已初始化
        if not hasattr(self, '_alarm_card') or self._alarm_card is None:
            logger.warning("告警显示控件未初始化，跳过错误更新")
            return

        # 显示告警
        self._alarm_card.setVisible(True)
        self._clear_alarm_btn.setVisible(True)
        self._alarm_label.setText(f"[{error_code.value}] {message}")
        self._alarm_label.setStyleSheet(f"color: {COLOR_ERROR}; font-size: {FONT_SIZE_SM};")

        # 告警指示灯
        if error_code == ErrorCode.ARM_DISCONNECTED:
            self._arm_connection.set_status("error")
        elif error_code == ErrorCode.TC3720_ERROR or error_code == ErrorCode.TIMEOUT_3720:
            self._tc3720_connection.set_status("error")

        self._log("错误", f"[{error_code.value}] {message}")

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