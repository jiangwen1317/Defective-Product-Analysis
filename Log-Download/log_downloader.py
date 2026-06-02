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
  python log_downloader.py              # 定时模式 (使用配置文件中的间隔)
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

        # 从配置中提取常用配置
        self.lvts_config = self.config.get("lvts_server", {})
        self.download_config = self.config.get("download", {})
        self.scheduler_config = self.config.get("scheduler", {})
        self.browser_config = self.config.get("browser", {})

        # 设置下载目录 (支持相对路径和绝对路径)
        download_dir = self.download_config.get("directory", "downloads")
        if not os.path.isabs(download_dir):
            # 相对路径基于脚本所在目录
            script_dir = os.path.dirname(os.path.abspath(__file__))
            download_dir = os.path.join(script_dir, download_dir)
        self.download_dir = download_dir

        # 确保下载目录存在
        os.makedirs(self.download_dir, exist_ok=True)

        # 下载记录文件路径
        self.record_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "downloaded_tasks.txt"
        )

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

        # 检查 LVTS 服务器配置
        lvts = config.get("lvts_server", {})
        if not lvts.get("url"):
            missing_fields.append("lvts_server.url")
        if not lvts.get("username"):
            missing_fields.append("lvts_server.username")
        if not lvts.get("password"):
            missing_fields.append("lvts_server.password")

        # 检查下载配置
        download = config.get("download", {})
        if not download.get("directory"):
            missing_fields.append("download.directory")

        if missing_fields:
            raise ValueError(
                f"配置文件缺少必需的字段:\n" +
                "\n".join(f"  - {field}" for field in missing_fields)
            )

    def _setup_logging(self):
        """设置日志配置"""
        log_config = self.config.get("log", {})
        log_level = getattr(logging, log_config.get("level", "INFO"))
        log_file = log_config.get("file", "log_downloader.log")

        # 如果 log_file 是相对路径,转换为绝对路径
        if not os.path.isabs(log_file):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            log_file = os.path.join(script_dir, log_file)

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

        # 配置下载目录
        download_dir_abs = os.path.abspath(self.download_dir)

        self.browser = self.playwright.chromium.launch(
            headless=headless,
            channel=self.browser_config.get("channel", "chrome"),
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        # 创建上下文并配置下载目录
        context = self.browser.new_context(
            accept_downloads=True,
            viewport=self.browser_config.get("viewport", {"width": 1920, "height": 1080}),
            # 设置下载目录
            # 注意: Playwright 的 set_download_behavior 需要在创建 context 后调用
        )

        # 配置下载行为
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
            self.page.wait_for_selector("input", timeout=10000)

            # 填写用户名 - 查找第一个可见的文本输入框
            username_input = self.page.locator(
                'input[type="text"], input:not([type="password"])'
            ).first
            if username_input.count() > 0:
                username_input.fill(username)
                logging.info("已输入用户名")
            else:
                logging.error("未找到用户名输入框")
                return False

            # 填写密码
            password_input = self.page.locator('input[type="password"]').first
            if password_input.count() > 0:
                password_input.fill(password)
                logging.info("已输入密码")
            else:
                logging.error("未找到密码输入框")
                return False

            # 点击登录按钮
            login_button = self.page.locator(
                'button:has-text("登录"), button[type="submit"], .el-button--primary'
            )
            if login_button.count() > 0:
                login_button.first.click()
                logging.info("已点击登录按钮")
            else:
                logging.error("未找到登录按钮")
                return False

            # 等待登录成功后的特征元素出现 (最多等待15秒)
            # 登录成功后通常会: 1) 登录按钮消失 2) 出现用户信息或任务列表
            try:
                # 等待登录按钮消失或任务表格出现
                success_indicator = self.page.locator(
                    'table tbody tr, .el-table__body-wrapper tbody tr, '
                    '.task-item, [class*="task-row"], .user-info, [class*="user-name"]'
                ).first
                success_indicator.wait_for(state="visible", timeout=15000)
                logging.info("检测到登录成功特征: 页面内容已加载")
            except Exception as e:
                # 如果超时，再检查登录按钮是否仍然可见
                login_button = self.page.locator('button:has-text("登录")')
                login_button_visible = login_button.count() > 0 and login_button.first.is_visible()
                if login_button_visible:
                    logging.error(f"登录失败: 等待页面加载超时 - {e}")
                    self._save_screenshot("login_failed")
                    return False
                # 登录按钮已消失但特征元素未出现，继续执行

            logging.info("登录成功")
            return True

        except Exception as e:
            logging.error(f"登录失败: {e}")
            self._save_screenshot("login_error")
            return False

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

            # 等待网络请求完成或短暂稳定
            self.page.wait_for_load_state("networkidle", timeout=10000)
            self.page.wait_for_timeout(500)  # 额外等待UI渲染完成

            # 检查是否存在任务表格
            if self._is_task_list_page():
                logging.info("任务列表页面已加载")
                return True
            else:
                logging.warning("未检测到任务列表表格,但继续执行")
                self._save_screenshot("task_list_verify")
                return True  # 不中断流程

        except Exception as e:
            logging.error(f"验证任务列表页面失败: {e}")
            self._save_screenshot("task_list_nav_error")
            return False

    def _is_task_list_page(self) -> bool:
        """
        检查当前页面是否是任务列表页面。

        Returns:
            如果是任务列表页面返回 True,否则返回 False
        """
        # 检查是否存在表格或任务列表元素
        task_list_indicators = [
            "table tbody tr",
            ".task-item",
            "[class*='task-row']",
            ".el-table",
            "table",
        ]

        for selector in task_list_indicators:
            if self.page.locator(selector).first.count() > 0:
                return True

        return False

    def scan_downloadable_tasks(self) -> List[Dict]:
        """
        扫描任务列表,识别所有可下载的任务。

        根据实际页面结构:
        - 任务列表是表格形式
        - 每行任务的"操作"列包含"详情"和"下载日志"按钮
        - 直接点击"下载日志"按钮即可触发下载

        Returns:
            可下载任务列表,每个任务包含 id、name 等信息
        """
        tasks = []

        try:
            logging.info("正在扫描可下载的任务")

            # 查找所有任务行 (Element UI 表格结构)
            task_rows = self.page.locator(".el-table__body-wrapper tbody tr").all()

            if not task_rows:
                # 备用选择器
                task_rows = self.page.locator("table tbody tr").all()

            logging.info(f"找到 {len(task_rows)} 个任务行")

            for idx, row in enumerate(task_rows):
                try:
                    # 查找"下载日志"按钮
                    download_btn = None

                    # 尝试多种选择器
                    download_selectors = [
                        'button:has-text("下载日志")',
                        'button:has-text("下载")',
                        ".el-button--text:has-text('下载')",
                        "td:last-child button:last-child",  # 操作列的最后一个按钮
                    ]

                    for selector in download_selectors:
                        btn = row.locator(selector).first
                        if btn.count() > 0 and btn.is_visible():
                            download_btn = btn
                            logging.debug(f"使用选择器 {selector} 找到下载按钮")
                            break

                    if download_btn:
                        # 提取任务信息
                        task_id = self._extract_task_id(row, idx)
                        task_name = self._extract_task_name(row, idx)

                        # 不存储页面元素引用，改用行索引，在使用时重新获取
                        tasks.append(
                            {
                                "id": task_id,
                                "name": task_name,
                                "row_index": idx,  # 使用索引而非元素引用
                            }
                        )

                        logging.info(f"发现可下载任务: {task_id} - {task_name}")

                except Exception as e:
                    logging.warning(f"解析任务行 {idx} 时出错: {e}")
                    continue

            logging.info(f"扫描完成,找到 {len(tasks)} 个可下载任务")
            return tasks

        except Exception as e:
            logging.error(f"扫描任务列表失败: {e}")
            self._save_screenshot("scan_tasks_error")
            return []

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
                cell = row.locator(selector).first
                if cell.count() > 0:
                    task_id = cell.inner_text().strip()
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
                cell = row.locator(selector).first
                if cell.count() > 0:
                    task_name = cell.inner_text().strip()
                    if task_name:
                        return task_name
            except Exception:
                continue

        # 如果都失败,使用任务 ID 作为名称
        return self._extract_task_id(row, row_index)

    def download_task_log(self, task: Dict) -> bool:
        """
        下载单个任务的日志文件。

        实际下载流程:
        1. 尝试勾选任务行的复选框 (可选操作)
        2. 右键点击任务行 (弹出上下文菜单)
        3. 从右键菜单中选择"下载日志"

        Args:
            task: 任务信息字典

        Returns:
            下载成功返回 True,否则返回 False
        """
        downloaded_file = None  # 初始化变量，避免未定义错误

        try:
            task_id = task["id"]
            task_name = task.get("name", task_id)
            logging.info(f"正在下载任务日志: {task_id}")

            # 使用行索引重新获取页面元素
            row_index = task.get("row_index")
            if row_index is None:
                logging.error(f"任务 {task_id} 没有行索引")
                return False

            # 重新获取任务行元素
            row = self.page.locator(".el-table__body-wrapper tbody tr").nth(row_index)
            if row.count() == 0:
                # 尝试备用选择器
                row = self.page.locator("table tbody tr").nth(row_index)
                if row.count() == 0:
                    logging.error(f"任务 {task_id} 行元素未找到 (索引: {row_index})")
                    self._save_screenshot(f"row_not_found_{task_id}")
                    return False

            # 步骤 1: 强制关闭可能存在的弹窗
            logging.info("检查并关闭可能的弹窗")
            try:
                # 使用 JavaScript 强制移除弹窗
                self.page.evaluate("""
                    () => {
                        // 移除所有弹窗
                        document.querySelectorAll('.ivu-modal-wrap, .ivu-modal-mask, [class*="modal"]').forEach(el => {
                            el.style.display = 'none';
                            el.remove();
                        });
                        // 移除遮罩层
                        document.querySelectorAll('.v-transfer-dom').forEach(el => {
                            el.style.display = 'none';
                        });
                    }
                """)
                logging.debug("已强制关闭弹窗")
            except Exception as e:
                logging.warning(f"关闭弹窗失败: {e}")

            # 尝试按 ESC 键关闭弹窗
            try:
                self.page.keyboard.press("Escape")
                logging.debug("已按 ESC 键")
            except Exception:
                pass

            # 步骤 2: 勾选任务行的复选框
            logging.info(f"勾选任务 {task_id} 的复选框")
            try:
                checkbox = row.locator("input[type='checkbox']").first
                if checkbox.count() > 0:
                    if not checkbox.is_checked():
                        checkbox.click()
                        # 等待复选框状态更新
                        self.page.wait_for_timeout(300)
                        logging.info("已勾选复选框")
                    else:
                        logging.info("复选框已勾选")
                else:
                    # 尝试点击第一列来勾选
                    first_cell = row.locator("td:first-child").first
                    if first_cell.count() > 0:
                        first_cell.click()
                        self.page.wait_for_timeout(300)
                        logging.info("已点击第一列勾选")
            except Exception as e:
                logging.warning(f"勾选复选框失败: {e}")

            # 步骤 3: 右键点击任务行 (弹出上下文菜单)
            logging.info(f"右键点击任务 {task_id} 的行")
            try:
                # 使用右键点击触发上下文菜单
                row.click(button="right")
                # 等待菜单出现 (最多等待3秒)
                try:
                    self.page.locator('li.ivu-dropdown-item:has-text("下载日志")').wait_for(
                        state="visible", timeout=3000
                    )
                    logging.info("已右键点击,菜单已渲染")
                except Exception:
                    # 如果菜单选择器不对，至少等待一小段时间
                    self.page.wait_for_timeout(500)
                    logging.debug("等待菜单渲染完成")
            except Exception as e:
                logging.error(f"右键点击失败: {e}")
                return False

            # 截图查看菜单是否出现
            self._save_screenshot(f"after_right_click_{task_id}")

            # 步骤 4: 从右键菜单中选择"下载日志"
            logging.info("选择下载日志菜单")
            try:
                # 根据实际 HTML 结构: <li class="ivu-dropdown-item">下载日志</li>
                download_menu_item = self.page.locator('li.ivu-dropdown-item:has-text("下载日志")').first

                if download_menu_item.count() > 0 and download_menu_item.is_visible():
                    # 在点击下载菜单项之前设置下载监听
                    with self.page.expect_download(timeout=60000) as download_info:
                        download_menu_item.click()
                        logging.info("已点击下载日志菜单,等待下载...")

                    # 获取下载对象
                    download = download_info.value
                    original_filename = download.suggested_filename
                    logging.info(f"捕获到下载事件: {original_filename}")

                    # 获取原始文件的扩展名
                    _, original_ext = os.path.splitext(original_filename)

                    # 生成文件名 (保留原始扩展名)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe_task_id = self._sanitize_filename(str(task['id']))
                    new_filename = f"{safe_task_id}_{timestamp}{original_ext}"
                    new_file_path = os.path.join(self.download_dir, new_filename)

                    # 如果目标文件已存在,添加序号
                    if os.path.exists(new_file_path):
                        base, ext = os.path.splitext(new_filename)
                        counter = 1
                        while os.path.exists(new_file_path):
                            new_filename = f"{base}_{counter}{ext}"
                            new_file_path = os.path.join(self.download_dir, new_filename)
                            counter += 1

                    download.save_as(new_file_path)
                    logging.info(f"文件已保存: {new_file_path}")

                    downloaded_file = new_file_path

                    # 截图保存下载后的页面状态 (在验证之前)
                    self._save_screenshot(f"after_download_click_{task_id}")

                    # 步骤 5: 等待并处理确认对话框 (如果有)
                    try:
                        confirm_btn = self.page.locator(
                            '.ivu-modal-footer button:has-text("确定"), '
                            '.ivu-btn-primary:has-text("确定")'
                        ).first
                        if confirm_btn.count() > 0 and confirm_btn.is_visible():
                            logging.info("检测到确认对话框,点击确定按钮")
                            confirm_btn.click()
                    except Exception as e:
                        logging.debug(f"未检测到确认对话框或点击失败: {e}")

                    # 验证文件完整性
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

    def _generate_filename(self, task: Dict) -> str:
        """
        生成下载文件名。

        Args:
            task: 任务信息字典

        Returns:
            文件名字符串
        """
        task_id = task["id"]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pattern = self.download_config.get(
            "filename_pattern", "{task_id}_{timestamp}.log"
        )

        return pattern.format(task_id=task_id, timestamp=timestamp)

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
        # 假设文件名格式: {task_id}_{timestamp}.log
        match = re.match(r"^(.+?)_\d{8}_\d{6}\.", filename)
        if match:
            return match.group(1)
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
            max_retries: 最大重试次数,默认使用配置文件中的值

        Returns:
            下载成功返回 True,否则返回 False
        """
        if max_retries is None:
            max_retries = self.scheduler_config.get("retry_count", 3)

        retry_delay = self.scheduler_config.get("retry_delay_seconds", 30)

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
            headless = self.browser_config.get("headless", True)
            self._init_browser(headless=headless)

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
            interval_hours: 执行间隔 (小时),默认使用配置文件中的值
        """
        if interval_hours is None:
            interval_hours = self.scheduler_config.get("interval_hours", 1)

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
        """
        保存页面截图。

        Args:
            name: 截图文件名 (不含扩展名)
        """
        try:
            if self.page:
                # 清理文件名
                safe_name = self._sanitize_filename(name)
                screenshot_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), f"{safe_name}.png"
                )
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
  python log_downloader.py              # 定时模式 (使用配置文件中的间隔)
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
        help="执行间隔 (小时),覆盖配置文件中的设置",
    )

    args = parser.parse_args()

    # 创建下载器实例
    downloader = LogDownloader(args.config)

    # 覆盖浏览器可见性设置
    if args.visible:
        downloader.browser_config["headless"] = False

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