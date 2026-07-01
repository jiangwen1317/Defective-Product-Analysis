"""
UI 样式常量定义。

提供统一的深色主题样式表，便于维护和主题切换。
"""

# ============================================================================
# 色彩系统
# ============================================================================

# 主背景色
COLOR_BG_PRIMARY = "#0f1117"       # 最深背景
COLOR_BG_SECONDARY = "#161822"     # 卡片背景
COLOR_BG_TERTIARY = "#1e2130"      # 嵌套区域背景
COLOR_BG_HOVER = "#252936"         # 悬停背景

# 边框色
COLOR_BORDER = "#2a2e3d"           # 默认边框
COLOR_BORDER_FOCUS = "#4a8a6a"     # 聚焦边框

# 文字色
COLOR_TEXT_PRIMARY = "#e8eaed"     # 主要文字
COLOR_TEXT_SECONDARY = "#9ca3af"   # 次要文字
COLOR_TEXT_MUTED = "#6b7280"       # 辅助文字
COLOR_TEXT_DISABLED = "#4b5563"    # 禁用文字

# 状态色 - 成功
COLOR_SUCCESS = "#22c55e"
COLOR_SUCCESS_BG = "#22c55e20"
COLOR_SUCCESS_BORDER = "#22c55e40"

# 状态色 - 警告
COLOR_WARNING = "#f59e0b"
COLOR_WARNING_BG = "#f59e0b20"
COLOR_WARNING_BORDER = "#f59e0b40"

# 状态色 - 错误
COLOR_ERROR = "#ef4444"
COLOR_ERROR_BG = "#ef444420"
COLOR_ERROR_BORDER = "#ef444440"

# 状态色 - 信息
COLOR_INFO = "#3b82f6"
COLOR_INFO_BG = "#3b82f620"
COLOR_INFO_BORDER = "#3b82f640"

# 状态色 - 空闲
COLOR_IDLE = "#6b7280"
COLOR_IDLE_BG = "#6b728020"
COLOR_IDLE_BORDER = "#6b728040"

# 状态色 - 处理中
COLOR_PROCESSING = "#8b5cf6"
COLOR_PROCESSING_BG = "#8b5cf620"
COLOR_PROCESSING_BORDER = "#8b5cf640"

# 强调色
COLOR_ACCENT = "#3b82f6"          # 链接、强调
COLOR_ACCENT_HOVER = "#60a5fa"    # 悬停强调

# 状态机颜色映射
STATE_COLORS = {
    "idle": ("#6b7280", "#6b728020"),          # 灰色 - 空闲
    "received_start": ("#3b82f6", "#3b82f620"), # 蓝色 - 收到请求
    "forwarded_3720": ("#f59e0b", "#f59e0b20"), # 橙色 - 转发中
    "waiting_result": ("#8b5cf6", "#8b5cf620"), # 紫色 - 等待结果
    "auto_reply": ("#22c55e", "#22c55e20"),     # 绿色 - 回传完成
    "error": ("#ef4444", "#ef444420"),          # 红色 - 异常
}

# 连接状态颜色
CONNECTION_STATUS_COLORS = {
    "online": ("#22c55e", "#22c55e30"),
    "offline": ("#6b7280", "#6b728030"),
    "error": ("#ef4444", "#ef444430"),
    "testing": ("#f59e0b", "#f59e0b30"),
}


# ============================================================================
# 字体系统
# ============================================================================

FONT_FAMILY = "'Segoe UI', 'Microsoft YaHei', Arial, sans-serif"
FONT_MONO = "'Cascadia Code', 'Consolas', 'Courier New', monospace"

FONT_SIZE_XS = "10px"
FONT_SIZE_SM = "11px"
FONT_SIZE_BASE = "12px"
FONT_SIZE_MD = "13px"
FONT_SIZE_LG = "14px"
FONT_SIZE_XL = "16px"
FONT_SIZE_2XL = "18px"
FONT_SIZE_3XL = "24px"


# ============================================================================
# 间距系统
# ============================================================================

SPACING_XS = 4
SPACING_SM = 8
SPACING_MD = 12
SPACING_LG = 16
SPACING_XL = 20
SPACING_2XL = 24

# 圆角
RADIUS_SM = 4
RADIUS_MD = 8
RADIUS_LG = 12
RADIUS_FULL = 9999


# ============================================================================
# 阴影系统
# ============================================================================

SHADOW_SM = "0 1px 2px rgba(0, 0, 0, 0.3)"
SHADOW_MD = "0 4px 6px rgba(0, 0, 0, 0.3)"
SHADOW_LG = "0 10px 15px rgba(0, 0, 0, 0.4)"
SHADOW_GLOW_SUCCESS = "0 0 20px rgba(34, 197, 94, 0.4)"
SHADOW_GLOW_ERROR = "0 0 20px rgba(239, 68, 68, 0.4)"
SHADOW_GLOW_INFO = "0 0 20px rgba(59, 130, 246, 0.4)"


# ============================================================================
# QSS 样式表
# ============================================================================

# 基础样式
QSS_BASE = f"""
QWidget {{
    background-color: {COLOR_BG_PRIMARY};
    color: {COLOR_TEXT_PRIMARY};
    font-family: {FONT_FAMILY};
    font-size: {FONT_SIZE_BASE};
}}
"""

# 应用整体样式
QSS_APP = f"""
QWidget {{
    background-color: {COLOR_BG_PRIMARY};
    color: {COLOR_TEXT_PRIMARY};
    font-family: {FONT_FAMILY};
    font-size: {FONT_SIZE_BASE};
}}

QGroupBox {{
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_MD};
    margin-top: 10px;
    padding-top: 10px;
    font-weight: bold;
    color: {COLOR_TEXT_SECONDARY};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
    color: {COLOR_TEXT_SECONDARY};
}}

QLineEdit, QComboBox, QSpinBox {{
    background-color: {COLOR_BG_TERTIARY};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SM};
    padding: 6px 10px;
    selection-background-color: {COLOR_ACCENT};
}}

QLineEdit:focus, QComboBox:focus {{
    border-color: {COLOR_BORDER_FOCUS};
}}

QLineEdit:disabled, QComboBox:disabled {{
    color: {COLOR_TEXT_DISABLED};
    background-color: {COLOR_BG_SECONDARY};
}}

QComboBox {{
    padding-right: 20px;
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {COLOR_TEXT_MUTED};
    margin-right: 8px;
}}

QPushButton {{
    background-color: {COLOR_BG_TERTIARY};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SM};
    padding: 8px 16px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: {COLOR_BG_HOVER};
    border-color: {COLOR_TEXT_MUTED};
}}

QPushButton:pressed {{
    background-color: {COLOR_BG_SECONDARY};
}}

QPushButton:disabled {{
    color: {COLOR_TEXT_DISABLED};
    background-color: {COLOR_BG_SECONDARY};
    border-color: {COLOR_BORDER};
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

QToolTip {{
    background-color: {COLOR_BG_TERTIARY};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SM};
    padding: 6px 10px;
    font-size: {FONT_SIZE_SM};
}}
"""

# 卡片容器样式
def card_style(bg_color: str = COLOR_BG_SECONDARY, border_color: str = COLOR_BORDER) -> str:
    """生成卡片样式。"""
    return f"""
    QFrame {{
        background-color: {bg_color};
        border: 1px solid {border_color};
        border-radius: {RADIUS_MD};
    }}
    """
