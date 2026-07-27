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

# 主动测试区域颜色
COLOR_TEST_CONTROL = "#10b981"       # 测试控制强调色（青绿）
COLOR_TEST_CONTROL_BG = "#10b98115"
COLOR_TEST_CONTROL_BORDER = "#10b98130"
COLOR_TEST_ACTIVE = "#f59e0b"        # 测试进行中（橙色）
COLOR_TEST_SUCCESS = "#22c55e"       # 测试通过
COLOR_TEST_FAILED = "#ef4444"        # 测试失败

# 强调色
COLOR_ACCENT = "#3b82f6"          # 链接、强调
COLOR_ACCENT_HOVER = "#60a5fa"    # 悬停强调


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
# QSS 样式表
# ============================================================================

# 卡片容器样式
def card_style(bg_color: str = "#161822", border_color: str = "#2a2e3d") -> str:
    """生成卡片样式。"""
    return f"""
    QFrame {{
        background-color: {bg_color};
        border: 1px solid {border_color};
        border-radius: {RADIUS_MD};
    }}
    """


# 测试控制按钮样式（主按钮）
def test_button_style(
    bg_color: str = COLOR_SUCCESS,
    hover_color: str = "#16a34a",
) -> str:
    """生成测试按钮样式。

    Args:
        bg_color: 背景色
        hover_color: 悬停背景色
    """
    return f"""
    QPushButton {{
        background-color: {bg_color};
        color: white;
        border: none;
        border-radius: {RADIUS_MD};
        font-size: {FONT_SIZE_LG};
        font-weight: bold;
        padding: 14px 24px;
        min-height: 48px;
    }}
    QPushButton:hover {{
        background-color: {hover_color};
    }}
    QPushButton:pressed {{
        background-color: {bg_color};
    }}
    QPushButton:disabled {{
        background-color: {COLOR_TEXT_DISABLED};
        color: {COLOR_BG_SECONDARY};
    }}
    """


# 次要操作按钮样式
def secondary_button_style() -> str:
    """生成次要按钮样式。"""
    return f"""
    QPushButton {{
        background-color: {COLOR_BG_TERTIARY};
        color: {COLOR_TEXT_PRIMARY};
        border: 1px solid {COLOR_BORDER};
        border-radius: {RADIUS_SM};
        font-size: {FONT_SIZE_SM};
        padding: 6px 12px;
    }}
    QPushButton:hover {{
        background-color: {COLOR_BG_HOVER};
        border-color: {COLOR_TEXT_MUTED};
    }}
    QPushButton:pressed {{
        background-color: {COLOR_BG_SECONDARY};
    }}
    """
