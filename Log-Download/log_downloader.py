#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LVTS 日志定时下载器

功能:
- 自动登录 LVTS 服务器
- 导航到任务列表页面
- 扫描并识别可下载的任务
- 自动下载日志文件
- 去重机制 (避免重复下载)
- 定时执行支持
- 完善的错误处理和日志记录

使用方法:
  python log_downloader.py              # 定时模式 (默认间隔 1 小时)
  python log_downloader.py --once       # 单次执行模式
  python log_downloader.py --visible    # 显示浏览器窗口 (调试用)
  python log_downloader.py --interval 2 # 设置执行间隔为 2 小时

依赖:
  pip install playwright
  playwright install chromium
"""

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
from playwright.sync_api import sync_playwright, Page, Browser


class LoginStatus:
    """登录状态枚举"""
    SUCCESS = "success"           # 登录成功
    FAILED = "failed"             # 登录失败
    TIMEOUT = "timeout"           # 等待超时
    UNKNOWN = "unknown"           # 未知状态


class Selectors:
    """UI 选择器常量"""
    # 任务表格行选择器（按优先级排序）
    TABLE_ROWS = [
        ".el-table__body-wrapper tbody tr",
        "table tbody tr",
    ]

    # 下载按钮选择器
    DOWNLOAD_BUTTON = [
        'button:has-text("下载日志")',
        'button:has-text("下载")',
        ".el-button--text:has-text('下载')",
        "td:last-child button:last-child",
    ]

    # 登录相关选择器
    USERNAME_INPUT = ['input[type="text"]', 'input:not([type="password"])']
    PASSWORD_INPUT = 'input[type="password"]'
    LOGIN_BUTTON = [
        'button:has-text("登录")',
        'button:has-text("登 录")',
        'button[type="submit"]',
        '.el-button--primary:has-text("登录")',
        '[class*="login"] button',
    ]

    # 登录成功后的特征元素
    LOGIN_SUCCESS = [
        ".el-table__body-wrapper tbody tr",
        "table tbody tr",
        ".el-table__empty-text",
        ".user-info",
        "[class*='user-name']",
        "[class*='username']",
        ".el-aside",
    ]

    # 任务列表页面特征
    TASK_LIST_PAGE = [
        "table tbody tr",
        ".task-item",
        "[class*='task-row']",
        ".el-table",
        "table",
    ]

    # 下载菜单项
    DOWNLOAD_MENU = 'li.ivu-dropdown-item:has-text("下载日志")'

    # 确认对话框按钮
    CONFIRM_BUTTON = [
        '.ivu-modal-footer button:has-text("确定")',
        '.ivu-btn-primary:has-text("确定")',
    ]


class Timeout:
    """超时时间常量（毫秒）"""
    FORM_WAIT = 10_000      # 等待表单加载
    LOGIN_WAIT = 15_000     # 等待登录成功
    NETWORK_IDLE = 10_000   # 等待网络空闲
    MENU_RENDER = 3_000     # 等待菜单渲染
    DOWNLOAD_WAIT = 60_000  # 等待下载完成
    UI_RENDER = 500         # UI 渲染等待
    CHECKBOX_UPDATE = 300   # 复选框更新等待


class LogDownloader:
    """LVTS 日志下载器"""

    def __init__(self, config_path: str = "config.json"):
        """
        初始化下载器。

        Args:
            config_path: 配置文件路径,默认为 config.json
        """
        self.config = self._load_config(config_path)
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.playwright = None

        # 缓存脚本所在目录（避免重复计算）
        self._script_dir = os.path.dirname(os.path.abspath(__file__))

        # 从配置中提取核心配置
        self.lvts_config = self.config.get("lvts_server", {})
        self.download_config = self.config.get("download", {})

        # 浏览器设置 (可通过命令行参数覆盖)
        self.headless = True  # 默认无头模式

        # 设置下载目录 (支持相对路径和绝对路径)
        download_dir = self.download_config.get("directory", "downloads")
        if not os.path.isabs(download_dir):
            download_dir = os.path.join(self._script_dir, download_dir)
        self.download_dir = download_dir

        # 确保下载目录存在
        os.makedirs(self.download_dir, exist_ok=True)

        # 下载记录文件路径
        self.record_file = os.path.join(self._script_dir, "downloaded_tasks.txt")

        # 设置日志
        self._setup_logging()

    def _load_config(self, config_path: str) -> Dict:
        """
        加载配置文件。

        Args:
            config_path: 配置文件路径

        Returns:
            配置字典

        Raises:
            FileNotFoundError: 配置文件不存在
            ValueError: 配置文件格式错误或缺少必需字段
        """
        # 检查文件是否存在
        config_abs_path = os.path.abspath(config_path)
        if not os.path.exists(config_path):
            raise FileNotFoundError(
                f"配置文件不存在: {config_abs_path}\n"
                f"请确保 config.json 文件存在"
            )

        # 尝试加载并解析 JSON
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"配置文件格式错误: {config_abs_path}\n"
                f"JSON 解析失败: {e}"
            )

        # 验证必需的配置字段
        self._validate_config(config)

        return config

    def _validate_config(self, config: Dict) -> None:
        """
        验证配置文件的必需字段。

        Args:
            config: 配置字典

        Raises:
            ValueError: 缺少必需的配置字段
        """
        missing_fields = []

        # 检查 LVTS 服务器配置 (核心必需)
        lvts = config.get("lvts_server", {})
        if not lvts.get("url"):
            missing_fields.append("lvts_server.url")
        if not lvts.get("username"):
            missing_fields.append("lvts_server.username")
        if not lvts.get("password"):
            missing_fields.append("lvts_server.password")

        # 检查下载目录配置 (核心必需)
        download = config.get("download", {})
        if not download.get("directory"):
            missing_fields.append("download.directory")

        if missing_fields:
            raise ValueError(
                f"配置文件缺少必需的字段:\n" +
                "\n".join(f"  - {field}" for field in missing_fields)
            )

    def _setup_logging(self):
        """设置日志配置 (使用硬编码默认值)"""
        # 硬编码日志配置
        log_level = logging.INFO
        log_file = "log_downloader.log"

        # 相对路径转换为绝对路径
        if not os.path.isabs(log_file):
            log_file = os.path.join(self._script_dir, log_file)

        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(log_file, encoding="utf-8"),
                logging.StreamHandler(),
            ],
        )

    def _init_browser(self, headless: bool = True):
        """
        初始化浏览器实例。

        Args:
            headless: 是否使用无头模式,默认为 True
        """
        self.playwright = sync_playwright().start()

        # 硬编码浏览器配置
        download_dir_abs = os.path.abspath(self.download_dir)

        self.browser = self.playwright.chromium.launch(
            headless=headless,
            channel="chrome",
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        # 创建上下文
        context = self.browser.new_context(
            accept_downloads=True,
            viewport={"width": 1920, "height": 1080},
        )

        context.set_default_timeout(60000)
        self.page = context.new_page()

        logging.info(f"浏览器初始化完成,下载目录: {download_dir_abs}")

    def _close_browser(self):
        """关闭浏览器并释放资源"""
        if self.browser:
            try:
                self.browser.close()
            except Exception as e:
                logging.warning(f"关闭浏览器时出现警告: {e}")
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception as e:
                logging.warning(f"停止 Playwright 时出现警告: {e}")

        self.browser = None
        self.page = None
        self.playwright = None
        logging.debug("浏览器已关闭")

    def login(self) -> bool:
        """
        登录 LVTS 服务器。

        Returns:
            登录成功返回 True,否则返回 False
        """
        try:
            url = self.lvts_config.get("url", "")
            username = self.lvts_config.get("username", "")
            password = self.lvts_config.get("password", "")

            if not url or not username or not password:
                logging.error("LVTS 服务器配置不完整,请检查 URL、用户名和密码")
                return False

            logging.info(f"正在登录 LVTS 服务器: {url}")
            self.page.goto(url, wait_until="networkidle")

            # 等待登录表单加载
            self.page.wait_for_selector("input", timeout=Timeout.FORM_WAIT)

            # 填写用户名
            username_locator = self.page.locator(", ".join(Selectors.USERNAME_INPUT))
            if username_locator.count() > 0:
                username_locator.first.fill(username)
                logging.info("已输入用户名")
            else:
                logging.error("未找到用户名输入框")
                return False

            # 填写密码
            password_locator = self.page.locator(Selectors.PASSWORD_INPUT)
            if password_locator.count() > 0:
                password_locator.first.fill(password)
                logging.info("已输入密码")
            else:
                logging.error("未找到密码输入框")
                return False

            # 点击登录按钮
            login_button_locators = [self.page.locator(sel) for sel in Selectors.LOGIN_BUTTON]
            login_button = next((loc for loc in login_button_locators if loc.count() > 0), None)
            if login_button:
                login_button.first.click()
                logging.info("已点击登录按钮")
            else:
                logging.error("未找到登录按钮")
                return False

            # 等待登录成功
            login_status = self._wait_for_login_success()

            if login_status == LoginStatus.SUCCESS:
                logging.info("登录成功")
                return True
            else:
                # FAILED、TIMEOUT、UNKNOWN 都视为失败
                error_msg = {
                    LoginStatus.FAILED: "登录按钮仍然可见或页面异常",
                    LoginStatus.TIMEOUT: "等待页面加载超时",
                    LoginStatus.UNKNOWN: "登录状态未知",
                }.get(login_status, "未知错误")
                logging.error(f"登录失败: {error_msg}")
                self._save_screenshot(f"login_failed_{login_status}")
                return False

        except Exception as e:
            logging.error(f"登录失败: {e}")
            self._save_screenshot("login_error")
            return False

    def _wait_for_login_success(self, timeout: int = 15000) -> str:
        """
        等待并验证登录成功。

        验证策略：
        1. 登录按钮消失（必要条件）
        2. 出现任务列表或其他成功特征（充分条件）

        Args:
            timeout: 单次等待超时（毫秒），总超时限制为 timeout * 1.5

        Returns:
            LoginStatus: 登录状态
        """
        start_time = time.time()
        max_total_timeout = int(timeout * 1.5)  # 总超时限制为 timeout 的 1.5 倍

        # 步骤 1: 等待登录按钮消失
        logging.debug("等待登录按钮消失...")

        login_button_locator = None
        for selector in Selectors.LOGIN_BUTTON:
            locator = self.page.locator(selector)
            if locator.count() > 0:
                login_button_locator = locator
                break

        if login_button_locator:
            remaining = max_total_timeout - int((time.time() - start_time) * 1000)
            if remaining <= 0:
                return LoginStatus.TIMEOUT

            try:
                login_button_locator.wait_for(state="hidden", timeout=remaining)
                elapsed = (time.time() - start_time) * 1000
                logging.debug(f"登录按钮已消失 (耗时 {elapsed:.0f}ms)")
            except Exception:
                if login_button_locator.is_visible():
                    logging.warning("登录按钮仍然可见，登录可能失败")
                    return LoginStatus.FAILED

        # 步骤 2: 遍历成功特征选择器，等待任一元素出现
        logging.debug("等待成功特征元素出现...")

        for selector in Selectors.LOGIN_SUCCESS:
            elapsed_ms = int((time.time() - start_time) * 1000)

            # 检查总超时
            if elapsed_ms >= max_total_timeout:
                logging.warning(f"总超时限制已达 ({max_total_timeout}ms)")
                break

            locator = self.page.locator(selector)
            if locator.count() == 0:
                continue  # 元素不存在，继续检查下一个选择器

            # 元素存在，等待它变为可见
            try:
                remaining = max_total_timeout - elapsed_ms
                locator.wait_for(state="visible", timeout=min(timeout // 2, remaining))
                logging.debug(f"检测到成功特征: {selector}")
                return LoginStatus.SUCCESS
            except Exception:
                # 等待失败，继续检查下一个选择器
                continue

        # 步骤 3: 检查 URL 是否离开登录页
        current_url = self.page.url
        logging.debug(f"当前 URL: {current_url}")
        login_page_indicators = ["/login", "/signin", "/enter"]
        if not any(ind in current_url.lower() for ind in login_page_indicators):
            logging.info("URL 已离开登录页，登录可能成功")
            return LoginStatus.SUCCESS

        # 步骤 4: 快速检测（不再等待，只检查元素是否已存在且可见）
        for selector in Selectors.LOGIN_SUCCESS:
            locator = self.page.locator(selector)
            if locator.count() > 0 and locator.is_visible():
                logging.debug(f"检测到成功特征: {selector}")
                return LoginStatus.SUCCESS

        # 返回超时状态
        elapsed = (time.time() - start_time) * 1000
        logging.warning(f"未能在 {elapsed:.0f}ms 内检测到登录成功特征")
        return LoginStatus.TIMEOUT

    def navigate_to_task_list(self) -> bool:
        """
        导航到任务列表页面。

        注意: 根据实际页面结构,登录后的 URL 已经是任务列表页面,
        因此此方法主要验证页面是否正确加载。

        Returns:
            导航成功返回 True,否则返回 False
        """
        try:
            logging.info("验证任务列表页面")
            self.page.wait_for_load_state("networkidle", timeout=Timeout.NETWORK_IDLE)
            self.page.wait_for_timeout(Timeout.UI_RENDER)

            if self._is_task_list_page():
                logging.info("任务列表页面已加载")
                return True
            else:
                logging.warning("未检测到任务列表表格,但继续执行")
                self._save_screenshot("task_list_verify")
                return True

        except Exception as e:
            logging.error(f"验证任务列表页面失败: {e}")
            self._save_screenshot("task_list_nav_error")
            return False

    def _is_task_list_page(self) -> bool:
        """检查当前页面是否是任务列表页面。"""
        return any(
            self.page.locator(sel).count() > 0
            for sel in Selectors.TASK_LIST_PAGE
        )

    def scan_downloadable_tasks(self) -> List[Dict]:
        """
        扫描任务列表,识别所有可下载的任务。

        Returns:
            可下载任务列表,每个任务包含 id、name 等信息
        """
        tasks = []

        try:
            logging.info("正在扫描可下载的任务")

            # 查找所有任务行
            task_rows = []
            for selector in Selectors.TABLE_ROWS:
                task_rows = self.page.locator(selector).all()
                if task_rows:
                    break

            logging.info(f"找到 {len(task_rows)} 个任务行")

            for idx, row in enumerate(task_rows):
                try:
                    # 查找下载按钮
                    download_btn_locator = None
                    used_selector = None

                    for selector in Selectors.DOWNLOAD_BUTTON:
                        btn_locator = row.locator(selector)
                        if btn_locator.count() > 0 and btn_locator.first.is_visible():
                            download_btn_locator = btn_locator
                            used_selector = selector
                            break

                    if download_btn_locator:
                        task_id = self._extract_task_id(row, idx)
                        task_name = self._extract_task_name(row, idx)

                        tasks.append({
                            "id": task_id,
                            "name": task_name,
                        })
                        logging.debug(f"使用选择器 {used_selector} 找到任务: {task_id}")

                except Exception as e:
                    logging.warning(f"解析任务行 {idx} 时出错: {e}")

            logging.info(f"扫描完成,找到 {len(tasks)} 个可下载任务")
            return tasks

        except Exception as e:
            logging.error(f"扫描任务列表失败: {e}")
            self._save_screenshot("scan_tasks_error")
            return []

    def _find_task_row(self, task_id: str):
        """通过任务 ID 在页面中查找对应的行元素。

        Args:
            task_id: 任务 ID

        Returns:
            匹配的行 Locator，如果未找到则返回 None
        """
        for selector in Selectors.TABLE_ROWS:
            rows = self.page.locator(selector).all()
            for row in rows:
                try:
                    cell_locator = row.locator("td:nth-child(2)")
                    if cell_locator.count() > 0:
                        cell_text = cell_locator.first.inner_text().strip()
                        if cell_text == task_id:
                            return row
                except Exception:
                    continue
        return None

    def _extract_task_id(self, row, row_index: int) -> str:
        """
        从任务行中提取任务 ID。

        根据实际页面结构:
        - ID 列通常在第二列 (td:nth-child(2))

        Args:
            row: 任务行元素
            row_index: 行索引

        Returns:
            任务 ID 字符串
        """
        # 根据截图,ID 在第二列
        id_selectors = [
            "td:nth-child(2)",  # 截图显示 ID 在第二列
            "td:nth-child(1)",
        ]

        for selector in id_selectors:
            try:
                cell_locator = row.locator(selector)
                if cell_locator.count() > 0:
                    task_id = cell_locator.first.inner_text().strip()
                    if task_id and task_id.isdigit():  # ID 通常是数字
                        return task_id
            except Exception:
                continue

        # 如果都失败,使用行索引作为 ID
        return f"task_row_{row_index}"

    def _extract_task_name(self, row, row_index: int) -> str:
        """
        从任务行中提取任务名称。

        根据实际页面结构:
        - 任务名称在 ID 列之后 (td:nth-child(3))

        Args:
            row: 任务行元素
            row_index: 行索引

        Returns:
            任务名称字符串
        """
        # 根据截图,任务名称在第三列
        name_selectors = [
            "td:nth-child(3)",  # 截图显示任务名称在第三列
            "td:nth-child(4)",
        ]

        for selector in name_selectors:
            try:
                cell_locator = row.locator(selector)
                if cell_locator.count() > 0:
                    task_name = cell_locator.first.inner_text().strip()
                    if task_name:
                        return task_name
            except Exception:
                continue

        # 如果都失败,使用任务 ID 作为名称
        return self._extract_task_id(row, row_index)

    def download_task_log(self, task: Dict) -> bool:
        """
        下载单个任务的日志文件。

        下载流程:
        1. 勾选任务行的复选框
        2. 右键点击任务行 (弹出上下文菜单)
        3. 从右键菜单中选择"下载日志"

        Args:
            task: 任务信息字典

        Returns:
            下载成功返回 True,否则返回 False
        """
        downloaded_file = None

        try:
            task_id = task["id"]
            task_name = task.get("name", task_id)
            logging.info(f"正在下载任务日志: {task_id}")

            # 通过任务 ID 查找行元素（不再依赖行索引）
            row = self._find_task_row(task_id)
            if not row:
                logging.error(f"任务 {task_id} 行元素未找到")
                self._save_screenshot(f"row_not_found_{task_id}")
                return False

            logging.debug(f"开始下载任务 {task_id}")

            # 步骤 1: 关闭可能存在的弹窗
            self._close_modals()

            # 步骤 2: 勾选复选框
            logging.info(f"勾选任务 {task_id} 的复选框")
            try:
                checkbox_locator = row.locator("input[type='checkbox']")
                if checkbox_locator.count() > 0:
                    if not checkbox_locator.first.is_checked():
                        checkbox_locator.first.click()
                        self.page.wait_for_timeout(Timeout.CHECKBOX_UPDATE)
                    logging.info("已勾选复选框")
                else:
                    first_cell_locator = row.locator("td:first-child")
                    if first_cell_locator.count() > 0:
                        first_cell_locator.first.click()
                        self.page.wait_for_timeout(Timeout.CHECKBOX_UPDATE)
            except Exception as e:
                logging.warning(f"勾选复选框失败: {e}")

            # 步骤 3: 右键点击任务行
            logging.info(f"右键点击任务 {task_id} 的行")
            try:
                row.click(button="right")
                # 首先尝试等待菜单出现
                try:
                    self.page.locator(Selectors.DOWNLOAD_MENU).wait_for(
                        state="visible", timeout=Timeout.MENU_RENDER
                    )
                    logging.info("已右键点击,菜单已出现")
                except Exception:
                    # 如果等待失败，添加固定等待作为后备
                    self.page.wait_for_timeout(1000)
                    logging.debug("菜单等待超时，使用固定等待")
            except Exception as e:
                logging.error(f"右键点击失败: {e}")
                self._save_screenshot(f"right_click_failed_{task_id}")
                return False

            self._save_screenshot(f"after_right_click_{task_id}")

            # 步骤 4: 选择下载日志菜单
            logging.info("选择下载日志菜单")
            try:
                download_menu_locator = self.page.locator(Selectors.DOWNLOAD_MENU)

                if download_menu_locator.count() > 0 and download_menu_locator.first.is_visible():
                    with self.page.expect_download(timeout=Timeout.DOWNLOAD_WAIT) as download_info:
                        download_menu_locator.first.click()
                        logging.info("已点击下载日志菜单,等待下载...")

                    download = download_info.value
                    original_filename = download.suggested_filename
                    logging.info(f"捕获到下载事件: {original_filename}")

                    # 生成新文件名
                    _, original_ext = os.path.splitext(original_filename)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe_task_id = self._sanitize_filename(str(task['id']))
                    new_filename = f"{safe_task_id}_{timestamp}{original_ext}"
                    new_file_path = self._get_unique_filepath(new_filename)

                    download.save_as(new_file_path)
                    logging.info(f"文件已保存: {new_file_path}")

                    downloaded_file = new_file_path
                    self._save_screenshot(f"after_download_click_{task_id}")

                    # 处理确认对话框
                    self._handle_confirm_dialog()

                    if self.verify_file_integrity(downloaded_file):
                        logging.info(f"任务 [{task_name}] 下载成功")
                        return True
                    else:
                        logging.error(f"任务 [{task_name}] 下载的文件验证失败")
                        return False
                else:
                    logging.error("未找到下载日志菜单项")
                    self._save_screenshot(f"no_download_menu_{task_id}")
                    return False
            except Exception as e:
                logging.error(f"选择下载日志菜单失败: {e}")
                self._save_screenshot(f"download_menu_error_{task_id}")
                return False

        except Exception as e:
            logging.error(f"下载任务 {task.get('id', 'unknown')} 日志失败: {e}")
            self._save_screenshot(f"download_error_{task.get('id', 'unknown')}")
            return False

    def _close_modals(self):
        """关闭可能存在的弹窗（不影响 dropdown 组件）"""
        try:
            self.page.evaluate("""
                () => {
                    // 只隐藏明确的弹窗遮罩，不删除 DOM 节点
                    // 注意: 不能移除 .v-transfer-dom，它是 iView dropdown 的容器
                    document.querySelectorAll('.ivu-modal-wrap, .ivu-modal-mask')
                        .forEach(el => { el.style.display = 'none'; });
                }
            """)
        except Exception as e:
            logging.debug(f"关闭弹窗失败: {e}")

        try:
            self.page.keyboard.press("Escape")
        except Exception:
            pass

    def _get_unique_filepath(self, filename: str) -> str:
        """生成唯一的文件路径，避免文件名冲突"""
        file_path = os.path.join(self.download_dir, filename)
        if not os.path.exists(file_path):
            return file_path

        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(file_path):
            file_path = os.path.join(self.download_dir, f"{base}_{counter}{ext}")
            counter += 1
        return file_path

    def _handle_confirm_dialog(self):
        """处理确认对话框"""
        try:
            for selector in Selectors.CONFIRM_BUTTON:
                btn_locator = self.page.locator(selector)
                if btn_locator.count() > 0 and btn_locator.first.is_visible():
                    btn_locator.first.click()
                    logging.debug("已点击确认按钮")
                    break
        except Exception:
            pass

    def verify_file_integrity(self, file_path: str) -> bool:
        """
        验证下载文件的完整性。

        Args:
            file_path: 文件路径

        Returns:
            文件完整返回 True,否则返回 False
        """
        try:
            if not os.path.exists(file_path):
                logging.error(f"文件不存在: {file_path}")
                return False

            file_size = os.path.getsize(file_path)
            if file_size == 0:
                logging.error(f"文件大小为 0: {file_path}")
                return False

            logging.debug(f"文件验证通过: {file_path} (大小: {file_size} bytes)")
            return True

        except Exception as e:
            logging.error(f"验证文件完整性失败: {e}")
            return False

    def load_downloaded_tasks(self) -> Set[str]:
        """
        加载已下载的任务 ID 集合。

        Returns:
            已下载任务 ID 集合
        """
        downloaded = set()

        # 从下载记录文件加载 (优先)
        if os.path.exists(self.record_file):
            try:
                with open(self.record_file, "r", encoding="utf-8") as f:
                    for line in f:
                        task_id = line.strip()
                        if task_id:
                            downloaded.add(task_id)
                logging.debug(
                    f"从记录文件加载了 {len(downloaded)} 个已下载任务 ID"
                )
            except Exception as e:
                logging.warning(f"读取下载记录文件失败: {e}")

        # 从下载目录扫描 (仅补充记录文件未包含的)
        try:
            for filename in os.listdir(self.download_dir):
                task_id = self._extract_task_id_from_filename(filename)
                # 只添加记录文件中不存在的任务ID，避免重复计数
                if task_id and task_id not in downloaded:
                    downloaded.add(task_id)
            logging.debug(f"从下载目录扫描到 {len(downloaded)} 个已下载任务")
        except Exception as e:
            logging.warning(f"扫描下载目录失败: {e}")

        return downloaded

    def save_downloaded_task(self, task_id: str):
        """
        保存已下载的任务 ID 到记录文件。

        Args:
            task_id: 任务 ID
        """
        try:
            with open(self.record_file, "a", encoding="utf-8") as f:
                f.write(f"{task_id}\n")
            logging.debug(f"已记录下载任务: {task_id}")
        except Exception as e:
            logging.warning(f"保存下载记录失败: {e}")

    def _extract_task_id_from_filename(self, filename: str) -> Optional[str]:
        """
        从文件名中提取任务 ID。

        Args:
            filename: 文件名

        Returns:
            任务 ID,如果无法提取则返回 None
        """
        # 文件名格式: {task_id}_{YYYYMMDD}_{HHMMSS}.{ext}
        # task_id 可以是纯数字或包含下划线的字符串（如 task_row_5）
        # 使用非贪婪匹配，确保提取的是时间戳之前的部分
        match = re.match(r"^(.+?)_\d{8}_\d{6}\.", filename)
        if match:
            return match.group(1)

        # 备用方案：尝试匹配 task_row_{数字} 格式
        match = re.match(r"^(task_row_\d+)_", filename)
        if match:
            return match.group(1)

        # 备用方案：尝试匹配纯数字 ID
        match = re.match(r"^(\d+)_", filename)
        if match:
            return match.group(1)

        logging.debug(f"无法从文件名提取任务 ID: {filename}")
        return None

    def filter_pending_tasks(self, tasks: List[Dict]) -> List[Dict]:
        """
        过滤出待下载的任务 (排除已下载的)。

        Args:
            tasks: 所有可下载任务列表

        Returns:
            待下载任务列表
        """
        downloaded = self.load_downloaded_tasks()
        pending = [task for task in tasks if task["id"] not in downloaded]

        skipped_count = len(tasks) - len(pending)
        if skipped_count > 0:
            logging.info(f"跳过 {skipped_count} 个已下载任务")

        return pending

    def _download_with_retry(self, task: Dict, max_retries: int = None) -> bool:
        """
        带重试机制的下载任务。

        Args:
            task: 任务信息
            max_retries: 最大重试次数,默认 3 次

        Returns:
            下载成功返回 True,否则返回 False
        """
        if max_retries is None:
            max_retries = 3  # 默认重试 3 次

        retry_delay = 30  # 默认重试间隔 30 秒

        for attempt in range(1, max_retries + 1):
            try:
                if self.download_task_log(task):
                    return True

                logging.warning(
                    f"下载失败 (尝试 {attempt}/{max_retries}): {task['id']}"
                )

            except Exception as e:
                logging.error(
                    f"下载异常 (尝试 {attempt}/{max_retries}): {task['id']} - {e}"
                )

            if attempt < max_retries:
                logging.info(f"等待 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)

        return False

    def run_single_cycle(self) -> Dict:
        """
        执行单次下载周期。

        Returns:
            执行结果统计字典,包含 total、downloaded、skipped、failed
        """
        result = {"total": 0, "downloaded": 0, "skipped": 0, "failed": 0}

        try:
            # 初始化浏览器
            self._init_browser(headless=self.headless)

            # 登录
            if not self.login():
                logging.error("登录失败,终止本次周期")
                return result

            # 导航到任务列表
            if not self.navigate_to_task_list():
                logging.error("导航到任务列表失败,终止本次周期")
                return result

            # 扫描可下载任务
            tasks = self.scan_downloadable_tasks()
            result["total"] = len(tasks)

            if result["total"] == 0:
                logging.info("未找到可下载的任务")
                return result

            # 过滤已下载任务
            pending_tasks = self.filter_pending_tasks(tasks)
            result["skipped"] = len(tasks) - len(pending_tasks)

            logging.info(f"待下载任务数: {len(pending_tasks)}")

            # 下载任务
            for idx, task in enumerate(pending_tasks, 1):
                logging.info(f"下载进度: {idx}/{len(pending_tasks)}")

                if self._download_with_retry(task):
                    result["downloaded"] += 1
                    self.save_downloaded_task(task["id"])
                else:
                    result["failed"] += 1
                    logging.error(f"任务下载最终失败: {task['id']}")

        except KeyboardInterrupt:
            logging.info("收到中断信号,终止本次周期")
        except Exception as e:
            logging.error(f"执行下载周期时发生异常: {e}")
        finally:
            self._close_browser()

        return result

    def run_scheduler(self, interval_hours: float = None):
        """
        启动定时调度器。

        Args:
            interval_hours: 执行间隔 (小时),默认 1 小时
        """
        if interval_hours is None:
            interval_hours = 1  # 默认 1 小时

        interval_seconds = interval_hours * 3600

        logging.info(f"启动定时调度器,执行间隔: {interval_hours} 小时")
        logging.info("按 Ctrl+C 停止调度器")

        cycle_count = 0

        try:
            while True:
                cycle_count += 1
                start_time = datetime.now()
                logging.info(
                    f"\n{'='*60}"
                )
                logging.info(
                    f"开始执行下载任务周期 #{cycle_count}: {start_time.strftime('%Y-%m-%d %H:%M:%S')}"
                )
                logging.info(
                    f"{'='*60}"
                )

                result = self.run_single_cycle()

                logging.info(
                    f"执行完成 - 总任务: {result['total']}, "
                    f"已下载: {result['downloaded']}, "
                    f"跳过: {result['skipped']}, "
                    f"失败: {result['failed']}"
                )

                # 计算等待时间
                elapsed = (datetime.now() - start_time).total_seconds()
                wait_time = max(0, interval_seconds - elapsed)

                if wait_time > 0:
                    next_run = datetime.now().timestamp() + wait_time
                    next_run_time = datetime.fromtimestamp(next_run)
                    logging.info(
                        f"等待 {wait_time/3600:.2f} 小时后下次执行 "
                        f"(预计时间: {next_run_time.strftime('%Y-%m-%d %H:%M:%S')})"
                    )
                    time.sleep(wait_time)
                else:
                    logging.warning(
                        f"本次执行耗时 {elapsed:.0f} 秒,超过设定间隔,立即开始下次执行"
                    )

        except KeyboardInterrupt:
            logging.info("\n收到中断信号,停止调度")
        except Exception as e:
            logging.error(f"调度器异常: {e}")
        finally:
            logging.info("调度器已停止")

    def _sanitize_filename(self, filename: str) -> str:
        """
        清理文件名,移除或替换非法字符。

        Args:
            filename: 原始文件名

        Returns:
            清理后的文件名
        """
        # 替换Windows文件名的非法字符
        illegal_chars = r'[<>:"/\\|?*]'
        sanitized = re.sub(illegal_chars, '_', filename)
        # 移除控制字符
        sanitized = re.sub(r'[\x00-\x1f\x7f]', '', sanitized)
        # 限制长度 (Windows路径最长260字符,保留足够空间)
        if len(sanitized) > 200:
            sanitized = sanitized[:200]
        return sanitized

    def _save_screenshot(self, name: str):
        """保存页面截图。"""
        try:
            if self.page:
                safe_name = self._sanitize_filename(name)
                screenshot_path = os.path.join(self._script_dir, f"{safe_name}.png")
                self.page.screenshot(path=screenshot_path)
                logging.info(f"已保存截图: {screenshot_path}")
        except Exception as e:
            logging.warning(f"保存截图失败: {e}")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(
        description="LVTS 日志定时下载器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python log_downloader.py              # 定时模式 (默认间隔 1 小时)
  python log_downloader.py --once       # 单次执行模式
  python log_downloader.py --visible    # 显示浏览器窗口 (调试用)
  python log_downloader.py --interval 2 # 设置执行间隔为 2 小时
        """,
    )

    parser.add_argument(
        "-c", "--config", default="config.json", help="配置文件路径 (默认: config.json)"
    )
    parser.add_argument(
        "--once", action="store_true", help="单次执行模式 (不循环)"
    )
    parser.add_argument(
        "--visible", action="store_true", help="显示浏览器窗口 (用于调试)"
    )
    parser.add_argument(
        "--interval",
        type=float,
        help="执行间隔 (小时),默认 1 小时",
    )

    args = parser.parse_args()

    # 创建下载器实例
    downloader = LogDownloader(args.config)

    # 覆盖浏览器可见性设置
    if args.visible:
        downloader.headless = False

    # 覆盖间隔设置
    interval = args.interval

    try:
        if args.once:
            # 单次执行模式
            logging.info("运行模式: 单次执行")
            result = downloader.run_single_cycle()

            print("\n" + "=" * 60)
            print("LVTS 日志下载结果")
            print("=" * 60)
            print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"总任务数: {result['total']}")
            print(f"成功下载: {result['downloaded']}")
            print(f"跳过 (已下载): {result['skipped']}")
            print(f"失败: {result['failed']}")
            print("=" * 60)

            if result["failed"] > 0:
                print("\n警告: 有部分任务下载失败,请检查日志文件")
        else:
            # 定时调度模式
            logging.info("运行模式: 定时调度")
            downloader.run_scheduler(interval_hours=interval)

    except Exception as e:
        logging.error(f"程序执行异常: {e}")
        print(f"\n错误: {e}")
    finally:
        logging.info("程序退出")


if __name__ == "__main__":
    main()