"""
文件监听与增量处理模块

功能：
1. ZIP 文件多线程并行解压（参考 EVT_Tool 的 file_utils.py 模式）
2. 基于 (file_path, file_size, file_mtime) 的增量判断
3. 信号文件 (.signal) 监听与触发
"""
import json
import logging
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from database import DatabaseConnection, MetricsRepository
from log_parser import LogParser
from schema import init_database

logger = logging.getLogger(__name__)

# 默认最大解压线程数
DEFAULT_MAX_WORKERS = 8


# ============================================================
# ZIP 解压
# ============================================================

def _extract_single_zip(zip_path: str) -> tuple[bool, str, Optional[str]]:
    """解压单个 ZIP 文件到其所在目录。

    Args:
        zip_path: ZIP 文件绝对路径。

    Returns:
        (success, file_name, error_msg) 三元组。
    """
    if not os.path.exists(zip_path):
        return False, "", None

    base_name = os.path.basename(zip_path)
    extract_dir = os.path.dirname(zip_path)

    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_dir)
        os.remove(zip_path)
        return True, base_name, None
    except Exception as e:
        return False, base_name, str(e)


def extract_all_zips(
    directory: str,
    max_iterations: int = 2,
    max_workers: Optional[int] = None,
) -> int:
    """多线程并行深度解压目录下的所有 ZIP 文件，并删除原始压缩包。

    支持多轮迭代解压（处理 ZIP 内嵌 ZIP 的情况）。

    Args:
        directory: 解压目录。
        max_iterations: 最大迭代轮数。
        max_workers: 最大线程数，默认 8。

    Returns:
        成功解压的 ZIP 文件总数。
    """
    if max_workers is None:
        max_workers = DEFAULT_MAX_WORKERS

    logger.info("开始多线程并行解压 %s 下的 ZIP 文件", directory)
    total_success = 0

    for iteration in range(1, max_iterations + 1):
        zip_files = _find_files(directory, ".zip")
        if not zip_files:
            logger.info("第 %d 轮：未发现 ZIP 文件，停止", iteration)
            break

        logger.info("第 %d 轮：发现 %d 个 ZIP，使用 %d 线程", iteration, len(zip_files), max_workers)

        success_count = 0
        fail_count = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_extract_single_zip, zp): zp for zp in zip_files}
            for future in as_completed(futures):
                success, name, error = future.result()
                if success:
                    success_count += 1
                else:
                    fail_count += 1
                    logger.warning("解压失败: %s - %s", name, error)

        logger.info("第 %d 轮完成：成功=%d, 失败=%d", iteration, success_count, fail_count)
        total_success += success_count

        if success_count == 0:
            break

    logger.info("ZIP 解压完成，共成功处理 %d 个", total_success)
    return total_success


def _find_files(directory: str, extension: str, prefix: Optional[str] = None) -> list[str]:
    """递归查找指定扩展名的文件。

    Args:
        directory: 搜索起始目录。
        extension: 文件扩展名（如 '.zip'、'.txt'）。
        prefix: 文件名前缀过滤。

    Returns:
        匹配的文件绝对路径列表。
    """
    result: list[str] = []
    for root, _, files in os.walk(directory):
        for filename in files:
            if not filename.endswith(extension):
                continue
            if prefix is not None and not filename.startswith(prefix):
                continue
            result.append(os.path.join(root, filename))
    return result


def discover_log_files(directory: str, extensions: list[str]) -> list[str]:
    """发现目录下所有日志文件。

    Args:
        directory: 搜索目录。
        extensions: 文件扩展名列表（如 ['.txt', '.log']）。

    Returns:
        日志文件路径列表。
    """
    result: list[str] = []
    for ext in extensions:
        result.extend(_find_files(directory, ext))
    return result


# ============================================================
# 增量处理与批量解析
# ============================================================

class FileWatcher:
    """文件监听器，集成增量处理、ZIP 解压和信号文件触发。"""

    def __init__(
        self,
        db_path: str,
        signal_dir: str,
        config: dict,
    ) -> None:
        self._db_path = db_path
        self._signal_dir = signal_dir
        self._config = config
        self._db = DatabaseConnection(db_path)
        self._repo = MetricsRepository(self._db)
        self._parser = LogParser()

    def process_directory(self, directory: str) -> tuple[int, int, int]:
        """处理指定目录：先解压 ZIP，再增量解析日志文件。

        Args:
            directory: 目标目录。

        Returns:
            (success, failed, skipped) 三元组。
        """
        # 1. 解压 ZIP
        extract_all_zips(directory)

        # 2. 发现日志文件
        extensions = self._config.get("log_sources", {}).get("file_extensions", [".txt", ".log"])
        log_files = discover_log_files(directory, extensions)
        logger.info("发现 %d 个日志文件", len(log_files))

        # 3. 增量解析
        return self._parse_files(log_files)

    def _parse_files(self, file_paths: list[str]) -> tuple[int, int, int]:
        """增量解析文件列表。

        Args:
            file_paths: 文件路径列表。

        Returns:
            (success, failed, skipped) 三元组。
        """
        success = 0
        failed = 0
        skipped = 0

        for file_path in file_paths:
            file_name = os.path.basename(file_path)

            try:
                result = self._parser.parse_file(file_path)

                with self._db.connect() as conn:
                    # 增量判断
                    if self._repo.is_file_processed(conn, file_path, result.file_size, result.file_mtime):
                        logger.debug("跳过（已处理）: %s", file_name)
                        skipped += 1
                        continue

                    if result.status == "Failed":
                        self._repo.insert_process_log(
                            conn,
                            file_path=file_path,
                            file_size=result.file_size,
                            file_mtime=result.file_mtime,
                            action="failed",
                            error_message=result.error,
                        )
                        failed += 1
                        logger.error("解析失败: %s - %s", file_name, result.error)
                        continue

                    import json as _json
                    summary_id = self._repo.insert_summary(
                        conn,
                        file_name=result.file_name,
                        file_path=result.file_path,
                        file_size=result.file_size,
                        file_mtime=result.file_mtime,
                        device_name=result.device_name,
                        device_tool_name=result.device_tool_name,
                        device_config_name=result.device_config_name,
                        fw_version=result.fw_version,
                        mp_tool_version=result.mp_tool_version,
                        flash_id=result.flash_id,
                        original_bad_block=result.original_bad_block,
                        cycles=result.cycles,
                        overall_result=result.overall_result,
                        fail_sections=_json.dumps(result.fail_sections, ensure_ascii=False),
                        wai=result.wai,
                        slc_pe_min=result.slc_pe_min,
                        slc_pe_max=result.slc_pe_max,
                        tlc_pe_min=result.tlc_pe_min,
                        tlc_pe_max=result.tlc_pe_max,
                        increase_bad_block=result.increase_bad_block,
                        parse_status=result.status,
                    )

                    metric_tuples = [m.as_tuple() for m in result.metrics]
                    self._repo.insert_metrics_batch(conn, summary_id, metric_tuples)

                    self._repo.insert_process_log(
                        conn,
                        file_path=file_path,
                        file_size=result.file_size,
                        file_mtime=result.file_mtime,
                        action="parsed",
                        summary_id=summary_id,
                    )

                success += 1
                logger.info("入库: %s | 指标=%d | 结果=%s", file_name, len(result.metrics), result.overall_result)

            except Exception as exc:
                failed += 1
                logger.error("异常: %s - %s", file_name, exc, exc_info=True)

        logger.info("处理完成: 成功=%d, 失败=%d, 跳过=%d", success, failed, skipped)
        return success, failed, skipped

    # ---- 信号文件监听 ----

    def watch_loop(self, poll_interval: float = 5.0) -> None:
        """循环监听信号文件，检测到信号后触发处理。

        信号文件格式（JSON）：
            {"files": ["path/to/log1.txt", "path/to/log2.txt"], "action": "parse"}
            或
            {"dirs": ["path/to/dir/"], "action": "parse"}

        Args:
            poll_interval: 轮询间隔（秒）。
        """
        os.makedirs(self._signal_dir, exist_ok=True)
        logger.info("信号监听启动，目录: %s", self._signal_dir)

        try:
            while True:
                signal_files = _find_files(self._signal_dir, ".signal")
                for signal_path in signal_files:
                    self._process_signal(signal_path)

                time.sleep(poll_interval)
        except KeyboardInterrupt:
            logger.info("信号监听已停止")

    def watch_once(self) -> int:
        """单次检查信号文件。

        Returns:
            处理的文件数。
        """
        os.makedirs(self._signal_dir, exist_ok=True)
        signal_files = _find_files(self._signal_dir, ".signal")
        total = 0
        for signal_path in signal_files:
            total += self._process_signal(signal_path)
        return total

    def _process_signal(self, signal_path: str) -> int:
        """处理单个信号文件。

        Args:
            signal_path: 信号文件路径。

        Returns:
            处理的日志文件数。
        """
        logger.info("检测到信号文件: %s", signal_path)
        try:
            with open(signal_path, "r", encoding="utf-8") as f:
                signal_data = json.load(f)
        except Exception as exc:
            logger.error("信号文件读取失败: %s - %s", signal_path, exc)
            self._mark_signal_done(signal_path)
            return 0

        file_paths: list[str] = signal_data.get("files", [])
        dirs: list[str] = signal_data.get("dirs", [])

        total = 0

        # 处理指定文件
        if file_paths:
            valid_files = [f for f in file_paths if os.path.exists(f)]
            success, _, _ = self._parse_files(valid_files)
            total += success

        # 处理指定目录
        for d in dirs:
            if os.path.isdir(d):
                success, _, _ = self.process_directory(d)
                total += success

        self._mark_signal_done(signal_path)
        logger.info("信号处理完成: %s，处理 %d 个文件", signal_path, total)
        return total

    def _mark_signal_done(self, signal_path: str) -> None:
        """将信号文件重命名为 .done。

        Args:
            signal_path: 信号文件路径。
        """
        done_path = signal_path + ".done"
        try:
            if os.path.exists(done_path):
                os.remove(done_path)
            os.rename(signal_path, done_path)
        except Exception as exc:
            logger.warning("信号文件重命名失败: %s - %s", signal_path, exc)
