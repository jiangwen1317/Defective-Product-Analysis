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
    COLOR_IDLE,
    COLOR_INFO,
    COLOR_PROCESSING,
    COLOR_SUCCESS,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
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
