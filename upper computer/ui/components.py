"""
通用 UI 组件库。

提供可复用的 UI 组件，包括卡片、状态指示器、统计面板等。
"""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from ui.styles import (
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_BORDER,
    COLOR_ERROR,
    COLOR_ERROR_BG,
    COLOR_ERROR_BORDER,
    COLOR_IDLE,
    COLOR_INFO,
    COLOR_PROCESSING,
    COLOR_SUCCESS,
    COLOR_SUCCESS_BG,
    COLOR_SUCCESS_BORDER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    COLOR_WARNING_BG,
    COLOR_WARNING_BORDER,
    FONT_MONO,
    FONT_SIZE_2XL,
    FONT_SIZE_3XL,
    FONT_SIZE_BASE,
    FONT_SIZE_LG,
    FONT_SIZE_SM,
    FONT_SIZE_XL,
    FONT_SIZE_XS,
    RADIUS_FULL,
    RADIUS_MD,
    RADIUS_SM,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
    SPACING_XS,
    SPACING_XL,
    card_style,
)


class StatusIndicator(QWidget):
    """状态指示器组件。

    显示一个带发光效果的状态圆点。
    """

    def __init__(
        self,
        status: str = "offline",
        size: int = 12,
        parent: QWidget | None = None,
    ) -> None:
        """初始化状态指示器。

        Args:
            status: 状态类型 ('online', 'offline', 'error', 'warning', 'info', 'processing')
            size: 指示器大小
            parent: 父部件
        """
        super().__init__(parent)
        self._status = status
        self._size = size
        self._pulsing = False
        self._pulse_timer: QTimer | None = None

        self.setFixedSize(size + 4, size + 4)
        self._update_style()

    def _get_color(self) -> str:
        """获取状态对应的颜色。"""
        colors = {
            "online": COLOR_SUCCESS,
            "offline": COLOR_IDLE,
            "error": COLOR_ERROR,
            "warning": COLOR_WARNING,
            "info": COLOR_INFO,
            "processing": COLOR_PROCESSING,
        }
        return colors.get(self._status, COLOR_IDLE)

    def _update_style(self) -> None:
        """更新样式。"""
        color = self._get_color()
        size = self._size
        glow = self._status in ("online", "error", "processing")

        shadow = ""
        if glow:
            shadows = {
                COLOR_SUCCESS: "0 0 12px rgba(34, 197, 94, 0.6)",
                COLOR_ERROR: "0 0 12px rgba(239, 68, 68, 0.6)",
                COLOR_PROCESSING: "0 0 12px rgba(139, 92, 246, 0.6)",
            }
            shadow = shadows.get(color, "")

        self.setStyleSheet(f"""
            QWidget {{
                background-color: {color};
                border-radius: {size // 2}px;
                {"box-shadow: " + shadow if shadow else ""}
            }}
        """)

    def set_status(self, status: str) -> None:
        """设置状态。"""
        self._status = status
        self._update_style()

    def start_pulse(self) -> None:
        """开始脉冲动画。"""
        if self._pulsing:
            return
        self._pulsing = True

        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._on_pulse)
        self._pulse_timer.start(800)

    def stop_pulse(self) -> None:
        """停止脉冲动画。"""
        self._pulsing = False
        if self._pulse_timer:
            self._pulse_timer.stop()
            self._pulse_timer = None

    def _on_pulse(self) -> None:
        """脉冲动画回调。"""
        current = self.windowOpacity()
        if current > 0.5:
            self.setWindowOpacity(0.3)
        else:
            self.setWindowOpacity(1.0)


class Card(QFrame):
    """卡片容器组件。

    提供统一风格的卡片容器。
    """

    def __init__(
        self,
        title: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """初始化卡片。

        Args:
            title: 卡片标题，为 None 时不显示标题栏
            parent: 父部件
        """
        super().__init__(parent)
        self.setStyleSheet(card_style())

        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 标题栏
        self._title_widget: QWidget | None = None
        self._content_widget: QWidget | None = None

        if title:
            self._title_widget = self._create_title_bar(title)
            main_layout.addWidget(self._title_widget)

        # 内容区域
        self._content_widget = QWidget()
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(
            SPACING_MD, SPACING_MD, SPACING_MD, SPACING_MD
        )
        self._content_layout.setSpacing(SPACING_SM)
        main_layout.addWidget(self._content_widget, 1)

    def _create_title_bar(self, title: str) -> QWidget:
        """创建标题栏。"""
        title_bar = QWidget()
        title_bar.setStyleSheet(f"""
            QWidget {{
                background-color: {COLOR_BG_TERTIARY};
                border-top-left-radius: {RADIUS_MD};
                border-top-right-radius: {RADIUS_MD};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
        """)

        layout = QHBoxLayout(title_bar)
        layout.setContentsMargins(SPACING_MD, SPACING_SM, SPACING_MD, SPACING_SM)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"""
            color: {COLOR_TEXT_SECONDARY};
            font-size: {FONT_SIZE_SM};
            font-weight: bold;
        """)
        layout.addWidget(title_label)
        layout.addStretch()

        self._title_spacer = QSpacerItem(20, 0, QSizePolicy.Fixed, QSizePolicy.Minimum)
        layout.addSpacerItem(self._title_spacer)

        return title_bar

    def add_title_widget(self, widget: QWidget) -> None:
        """添加标题栏部件。"""
        if self._title_widget:
            layout = self._title_widget.layout()
            # 移除弹性空间
            layout.removeItem(self._title_spacer)
            layout.addWidget(widget)
            layout.addSpacerItem(self._title_spacer)

    def content_layout(self) -> QVBoxLayout:
        """获取内容布局。"""
        return self._content_layout

    def add_content(self, widget: QWidget, stretch: int = 0) -> None:
        """添加内容部件。"""
        self._content_layout.addWidget(widget, stretch)


class StatCard(QWidget):
    """统计卡片组件。

    显示单个统计数据。
    """

    def __init__(
        self,
        label: str,
        value: str | int = "0",
        icon: str = "",
        color: str = COLOR_TEXT_PRIMARY,
        parent: QWidget | None = None,
    ) -> None:
        """初始化统计卡片。

        Args:
            label: 标签文字
            value: 数值
            icon: 图标（emoji 或文字）
            color: 数值颜色
            parent: 父部件
        """
        super().__init__(parent)
        self._setup_ui(label, value, icon, color)

    def _setup_ui(
        self,
        label: str,
        value: str | int,
        icon: str,
        color: str,
    ) -> None:
        """设置 UI。"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING_SM, SPACING_XS, SPACING_SM, SPACING_XS)
        layout.setSpacing(SPACING_MD)

        # 图标
        if icon:
            icon_label = QLabel(icon)
            icon_label.setStyleSheet(f"font-size: {FONT_SIZE_LG};")
            layout.addWidget(icon_label)

        # 标签和数值
        text_layout = QVBoxLayout()
        text_layout.setSpacing(0)

        self._value_label = QLabel(str(value))
        self._value_label.setStyleSheet(f"""
            color: {color};
            font-size: {FONT_SIZE_XL};
            font-weight: bold;
            font-family: {FONT_MONO};
        """)
        text_layout.addWidget(self._value_label)

        label_label = QLabel(label)
        label_label.setStyleSheet(f"""
            color: {COLOR_TEXT_MUTED};
            font-size: {FONT_SIZE_XS};
        """)
        text_layout.addWidget(label_label)

        layout.addLayout(text_layout)
        layout.addStretch()

    def set_value(self, value: str | int, color: str | None = None) -> None:
        """设置数值和颜色。"""
        self._value_label.setText(str(value))
        if color:
            self._value_label.setStyleSheet(f"""
                color: {color};
                font-size: {FONT_SIZE_XL};
                font-weight: bold;
                font-family: {FONT_MONO};
            """)


class StatsPanel(QWidget):
    """统计面板组件。

    显示多个统计数据。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化统计面板。"""
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """设置 UI。"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_MD)

        # 统计数据
        self._stats: dict[str, StatCard] = {}
        stats_data = [
            ("total", "总传输", "0", ""),
            ("success", "成功", "0", ""),
            ("failed", "失败", "0", ""),
            ("rate", "成功率", "0%", ""),
        ]

        for stat_id, label, value, icon in stats_data:
            stat_card = StatCard(label, value, icon)
            self._stats[stat_id] = stat_card
            layout.addWidget(stat_card)

        layout.addStretch()

    def update_stats(
        self,
        total: int,
        success: int,
        failed: int,
    ) -> None:
        """更新统计数据。"""
        rate = f"{success / total * 100:.1f}%" if total > 0 else "0%"

        self._stats["total"].set_value(str(total))
        self._stats["success"].set_value(str(success), COLOR_SUCCESS)
        self._stats["failed"].set_value(str(failed), COLOR_ERROR)

        # 更新成功率颜色
        rate_float = success / total if total > 0 else 0
        if rate_float >= 0.95:
            color = COLOR_SUCCESS
        elif rate_float >= 0.8:
            color = COLOR_WARNING
        else:
            color = COLOR_ERROR

        self._stats["rate"].set_value(rate, color)


class ConnectionStatus(QWidget):
    """连接状态组件。

    显示设备连接状态。
    """

    def __init__(
        self,
        name: str,
        icon: str = "●",
        parent: QWidget | None = None,
    ) -> None:
        """初始化连接状态。

        Args:
            name: 设备名称
            icon: 图标
            parent: 父部件
        """
        super().__init__(parent)
        self._name = name
        self._setup_ui(icon)

    def _setup_ui(self, icon: str) -> None:
        """设置 UI。"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, SPACING_SM, 0, SPACING_SM)
        layout.setSpacing(SPACING_MD)

        # 状态指示器
        self._indicator = StatusIndicator("offline", 10)
        layout.addWidget(self._indicator)

        # 信息
        info_layout = QVBoxLayout()
        info_layout.setSpacing(SPACING_XS)

        name_label = QLabel(self._name)
        name_label.setStyleSheet(f"""
            color: {COLOR_TEXT_PRIMARY};
            font-size: {FONT_SIZE_BASE};
            font-weight: 500;
        """)
        info_layout.addWidget(name_label)

        self._status_label = QLabel("离线")
        self._status_label.setStyleSheet(f"""
            color: {COLOR_TEXT_MUTED};
            font-size: {FONT_SIZE_SM};
        """)
        info_layout.addWidget(self._status_label)

        layout.addLayout(info_layout)
        layout.addStretch()

    def set_status(
        self,
        status: str,
        detail: str = "",
    ) -> None:
        """设置状态。"""
        status_texts = {
            "online": "已连接",
            "offline": "离线",
            "error": "异常",
            "testing": "测试中",
            "processing": "处理中",
        }

        self._indicator.set_status(status)
        status_text = status_texts.get(status, status)
        if detail:
            self._status_label.setText(f"{status_text} - {detail}")
        else:
            self._status_label.setText(status_text)


class InfoRow(QWidget):
    """信息行组件。

    显示单个键值对信息。
    """

    def __init__(
        self,
        label: str,
        value: str = "-",
        parent: QWidget | None = None,
    ) -> None:
        """初始化信息行。

        Args:
            label: 标签
            value: 值
            parent: 父部件
        """
        super().__init__(parent)
        self._setup_ui(label, value)

    def _setup_ui(self, label: str, value: str) -> None:
        """设置 UI。"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, SPACING_XS, 0, SPACING_XS)
        layout.setSpacing(SPACING_MD)

        label_widget = QLabel(label)
        label_widget.setStyleSheet(f"""
            color: {COLOR_TEXT_MUTED};
            font-size: {FONT_SIZE_SM};
        """)
        layout.addWidget(label_widget)

        layout.addStretch()

        self._value_widget = QLabel(value)
        self._value_widget.setStyleSheet(f"""
            color: {COLOR_TEXT_PRIMARY};
            font-size: {FONT_SIZE_SM};
            font-family: {FONT_MONO};
        """)
        layout.addWidget(self._value_widget)

    def set_value(self, value: str) -> None:
        """设置值。"""
        self._value_widget.setText(value)


class DutGridPanel(QWidget):
    """DUT 状态网格面板。

    以网格形式显示已配置 DUT 的状态，每个 DUT 显示编号和状态。
    默认显示全部 8 个 DUT，可通过 dut_indices 参数指定显示哪些。
    """

    def __init__(
        self,
        dut_indices: list[int] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """初始化 DUT 网格面板。

        Args:
            dut_indices: 要显示的 DUT 编号列表。默认为 [1,2,3,4,5,6,7,8]。
            parent: 父部件。
        """
        super().__init__(parent)
        self._dut_widgets: dict[int, QFrame] = {}
        self._dut_status_labels: dict[int, QLabel] = {}
        self._dut_indicators: dict[int, StatusIndicator] = {}
        self._dut_indices = dut_indices if dut_indices is not None else list(range(1, 9))
        self._setup_ui()

    def _setup_ui(self) -> None:
        """设置 UI。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_MD)

        # 根据 dut_indices 动态创建网格
        # 2 行布局，每行最多 4 个
        row1_indices = [d for d in self._dut_indices if self._dut_indices.index(d) < 4]
        row2_indices = [d for d in self._dut_indices if self._dut_indices.index(d) >= 4]

        for row_indices in [row1_indices, row2_indices]:
            if not row_indices:
                continue
            row_layout = QHBoxLayout()
            # 根据格子数量增加间距，格子少时间距更大
            if len(row_indices) <= 2:
                row_layout.setSpacing(SPACING_LG)
            else:
                row_layout.setSpacing(SPACING_SM)
            row_layout.addStretch()  # 居中效果

            for dut_index in row_indices:
                dut_frame = self._create_dut_item(dut_index)
                self._dut_widgets[dut_index] = dut_frame
                row_layout.addWidget(dut_frame)

            row_layout.addStretch()  # 居中效果
            layout.addLayout(row_layout)

    def _create_dut_item(self, dut_index: int) -> QFrame:
        """创建单个 DUT 项。

        Args:
            dut_index: DUT 编号 (1-8)

        Returns:
            DUT 项框架
        """
        frame = QFrame()
        frame.setFixedSize(65, 55)
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLOR_BG_TERTIARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {RADIUS_SM};
            }}
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignCenter)

        # 状态指示器 + 编号
        header_layout = QHBoxLayout()
        header_layout.setAlignment(Qt.AlignCenter)
        header_layout.setSpacing(4)

        indicator = StatusIndicator("offline", 8)
        self._dut_indicators[dut_index] = indicator
        header_layout.addWidget(indicator)

        index_label = QLabel(f"#{dut_index}")
        index_label.setStyleSheet(f"""
            color: {COLOR_TEXT_PRIMARY};
            font-size: {FONT_SIZE_SM};
            font-weight: bold;
        """)
        header_layout.addWidget(index_label)
        layout.addLayout(header_layout)

        # 状态文字
        status_label = QLabel("离线")
        status_label.setAlignment(Qt.AlignCenter)
        status_label.setStyleSheet(f"""
            color: {COLOR_TEXT_MUTED};
            font-size: {FONT_SIZE_XS};
        """)
        self._dut_status_labels[dut_index] = status_label
        layout.addWidget(status_label)

        return frame

    def set_dut_status(self, dut_index: int, status: str) -> None:
        """设置单个 DUT 的状态。

        Args:
            dut_index: DUT 编号 (1-8)
            status: 状态 ('offline', 'online', 'testing', 'success', 'failed', 'error')
        """
        if dut_index not in self._dut_widgets:
            return

        # 状态文本映射
        status_texts = {
            "offline": "离线",
            "online": "就绪",
            "testing": "测试中",
            "success": "通过",
            "failed": "失败",
            "error": "异常",
        }

        # 更新指示器
        if dut_index in self._dut_indicators:
            self._dut_indicators[dut_index].set_status(status)

        # 更新状态文字和样式
        frame = self._dut_widgets[dut_index]
        status_label = self._dut_status_labels[dut_index]
        status_text = status_texts.get(status, status)
        status_label.setText(status_text)

        # 更新边框和背景颜色
        colors = {
            "offline": (COLOR_BORDER, COLOR_BG_TERTIARY),
            "online": (COLOR_SUCCESS_BORDER, COLOR_SUCCESS_BG),
            "testing": (COLOR_WARNING_BORDER, "#f59e0b20"),
            "success": (COLOR_SUCCESS_BORDER, COLOR_SUCCESS_BG),
            "failed": (COLOR_ERROR_BORDER, COLOR_ERROR_BG),
            "error": (COLOR_ERROR_BORDER, COLOR_ERROR_BG),
        }
        border_color, bg_color = colors.get(status, (COLOR_BORDER, COLOR_BG_TERTIARY))

        text_colors = {
            "offline": COLOR_TEXT_MUTED,
            "online": COLOR_SUCCESS,
            "testing": COLOR_WARNING,
            "success": COLOR_SUCCESS,
            "failed": COLOR_ERROR,
            "error": COLOR_ERROR,
        }
        text_color = text_colors.get(status, COLOR_TEXT_MUTED)

        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: {RADIUS_SM};
            }}
        """)
        status_label.setStyleSheet(f"color: {text_color}; font-size: {FONT_SIZE_XS};")

    def reset_all(self) -> None:
        """重置所有显示的 DUT 状态为离线。"""
        for dut_index in self._dut_indices:
            self.set_dut_status(dut_index, "offline")


class TestProgressPanel(QWidget):
    """测试进度面板。

    显示测试进度、各 DUT 结果和统计信息。
    默认显示全部 8 个 DUT，可通过 dut_indices 参数指定显示哪些。
    """

    def __init__(
        self,
        dut_indices: list[int] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """初始化测试进度面板。

        Args:
            dut_indices: 要显示的 DUT 编号列表。默认为 [1,2,3,4,5,6,7,8]。
            parent: 父部件。
        """
        super().__init__(parent)
        self._dut_indices = dut_indices if dut_indices is not None else list(range(1, 9))
        self._dut_results: dict[int, str] = {i: "-" for i in self._dut_indices}
        self._result_labels: dict[int, QLabel] = {}
        self._is_testing = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        """设置 UI。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_SM)

        # 状态行
        status_layout = QHBoxLayout()
        status_layout.setSpacing(SPACING_SM)

        self._status_indicator = StatusIndicator("offline", 10)
        status_layout.addWidget(self._status_indicator)

        self._status_label = QLabel("等待测试")
        self._status_label.setStyleSheet(f"""
            color: {COLOR_TEXT_MUTED};
            font-size: {FONT_SIZE_SM};
            font-weight: 500;
        """)
        status_layout.addWidget(self._status_label)
        status_layout.addStretch()

        layout.addLayout(status_layout)

        # 进度条
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {COLOR_BG_TERTIARY};
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {COLOR_SUCCESS};
                border-radius: 4px;
            }}
        """)
        self._progress_bar.setValue(0)
        layout.addWidget(self._progress_bar)

        # 结果行（根据 dut_indices 显示）
        results_layout = QHBoxLayout()
        # 根据数量调整间距
        if len(self._dut_indices) <= 2:
            results_layout.setSpacing(SPACING_LG)
        else:
            results_layout.setSpacing(SPACING_XS)
        # 添加起始弹性空间保持居中
        results_layout.addStretch()

        for dut_index in self._dut_indices:
            result_label = QLabel("-")
            result_label.setFixedWidth(36)
            result_label.setAlignment(Qt.AlignCenter)
            result_label.setStyleSheet(f"""
                color: {COLOR_TEXT_MUTED};
                font-size: {FONT_SIZE_SM};
                font-family: {FONT_MONO};
            """)
            self._result_labels[dut_index] = result_label
            results_layout.addWidget(result_label)

        results_layout.addStretch()
        layout.addLayout(results_layout)

    def start_test(self, dut_indices: list[int]) -> None:
        """开始测试。

        Args:
            dut_indices: 要测试的 DUT 编号列表
        """
        self._is_testing = True

        # 更新状态
        self._status_indicator.set_status("processing")
        self._status_indicator.start_pulse()
        self._status_label.setText("测试进行中...")
        self._status_label.setStyleSheet(f"color: {COLOR_PROCESSING}; font-size: {FONT_SIZE_SM}; font-weight: 500;")

        # 重置结果
        for dut_index in self._dut_indices:
            self._dut_results[dut_index] = "-"
            if dut_index in self._result_labels:
                self._result_labels[dut_index].setText("-")
                self._result_labels[dut_index].setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_XS}; font-family: {FONT_MONO};")

        # 重置进度条
        self._progress_bar.setValue(0)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {COLOR_BG_TERTIARY};
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {COLOR_TEST_ACTIVE};
                border-radius: 4px;
            }}
        """)

    def update_dut_result(self, dut_index: int, result: str) -> None:
        """更新单个 DUT 的测试结果。

        Args:
            dut_index: DUT 编号 (1-8)
            result: 测试结果 ('0000' = 通过，其他 = 失败错误码)
        """
        if dut_index not in self._result_labels:
            return

        self._dut_results[dut_index] = result
        label = self._result_labels[dut_index]

        if result == "0000":
            label.setText("✓")
            label.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: {FONT_SIZE_SM}; font-weight: bold;")
        elif result == "-":
            label.setText("-")
            label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_XS}; font-family: {FONT_MONO};")
        else:
            label.setText("✗")
            label.setStyleSheet(f"color: {COLOR_ERROR}; font-size: {FONT_SIZE_SM}; font-weight: bold;")

        # 更新进度
        completed = sum(1 for r in self._dut_results.values() if r != "-")
        total = len(self._dut_indices)
        if total > 0:
            self._progress_bar.setValue(int(completed / total * 100))

    def complete_test(self, results: dict[int, str]) -> None:
        """测试完成。

        Args:
            results: 测试结果字典 {dut_index: error_code}
        """
        self._is_testing = False
        self._status_indicator.stop_pulse()

        # 计算通过率
        passed = sum(1 for code in results.values() if code == "0000")
        total = len(results) if results else len(self._dut_indices)
        rate = (passed / total * 100) if total > 0 else 0

        if rate == 100:
            self._status_indicator.set_status("online")
            self._status_label.setText(f"测试完成 - 全部通过 ({passed}/{total})")
            self._status_label.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: {FONT_SIZE_SM}; font-weight: 500;")
            self._progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    background-color: {COLOR_BG_TERTIARY};
                    border: none;
                    border-radius: 4px;
                }}
                QProgressBar::chunk {{
                    background-color: {COLOR_SUCCESS};
                    border-radius: 4px;
                }}
            """)
        else:
            self._status_indicator.set_status("error")
            self._status_label.setText(f"测试完成 - {passed}/{total} 通过")
            self._status_label.setStyleSheet(f"color: {COLOR_ERROR}; font-size: {FONT_SIZE_SM}; font-weight: 500;")
            self._progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    background-color: {COLOR_BG_TERTIARY};
                    border: none;
                    border-radius: 4px;
                }}
                QProgressBar::chunk {{
                    background-color: {COLOR_ERROR};
                    border-radius: 4px;
                }}
            """)

        self._progress_bar.setValue(100)

        # 更新所有结果标签
        for dut_index, error_code in results.items():
            if dut_index in self._result_labels:
                label = self._result_labels[dut_index]
                if error_code == "0000":
                    label.setText("✓")
                    label.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: {FONT_SIZE_SM}; font-weight: bold;")
                else:
                    label.setText("✗")
                    label.setStyleSheet(f"color: {COLOR_ERROR}; font-size: {FONT_SIZE_SM}; font-weight: bold;")

    def reset(self) -> None:
        """重置面板状态。"""
        self._is_testing = False
        self._status_indicator.stop_pulse()
        self._status_indicator.set_status("offline")
        self._status_label.setText("等待测试")
        self._status_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_SM}; font-weight: 500;")
        self._progress_bar.setValue(0)

        for dut_index in self._dut_indices:
            self._dut_results[dut_index] = "-"
            if dut_index in self._result_labels:
                self._result_labels[dut_index].setText("-")
                self._result_labels[dut_index].setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_SIZE_XS}; font-family: {FONT_MONO};")
