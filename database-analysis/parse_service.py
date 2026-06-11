"""
解析入库服务

封装「解析 → 增量判断 → 去重 → 入库 → 记录处理日志」的完整流程，
供 CLI (main.py)、GUI (gui_app.py)、文件监听 (file_watcher.py) 统一调用，
消除三处约 55 行的重复逻辑。
"""
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from database import DatabaseConnection, MetricsRepository
from log_parser import LogParser, ParseResult

logger = logging.getLogger(__name__)


# ============================================================
# 数据验证
# ============================================================

# 合法枚举值
_VALID_OVERALL_RESULTS = {"Pass", "Fail", "Unknown"}
_VALID_PARSE_STATUSES = {"Success", "Failed", "Partial"}
_VALID_VALUE_TYPES = {"hex", "decimal", "float", "string", "hexdump"}
_VALID_PROCESS_ACTIONS = {"parsed", "skipped", "failed"}


class ValidationError(Exception):
    """数据验证失败时抛出的异常。"""


def validate_parse_result(result: ParseResult) -> list[str]:
    """验证 ParseResult 的关键字段。

    Args:
        result: 待验证的解析结果。

    Returns:
        验证错误消息列表。空列表表示验证通过。
    """
    errors: list[str] = []

    # 必填字段
    if not result.file_name:
        errors.append("file_name 不能为空")
    if not result.file_path:
        errors.append("file_path 不能为空")
    if result.file_size < 0:
        errors.append(f"file_size 不能为负数: {result.file_size}")
    if result.file_mtime <= 0:
        errors.append(f"file_mtime 无效: {result.file_mtime}")

    # 枚举值校验
    if result.overall_result not in _VALID_OVERALL_RESULTS:
        errors.append(
            f"overall_result 值无效: '{result.overall_result}'，"
            f"允许值: {_VALID_OVERALL_RESULTS}"
        )
    if result.status not in _VALID_PARSE_STATUSES:
        errors.append(
            f"parse_status 值无效: '{result.status}'，"
            f"允许值: {_VALID_PARSE_STATUSES}"
        )

    # 数值字段非负校验
    if result.cycles < 0:
        errors.append(f"cycles 不能为负数: {result.cycles}")
    if result.test_cycle < 0:
        errors.append(f"test_cycle 不能为负数: {result.test_cycle}")
    if result.test_case < 0:
        errors.append(f"test_case 不能为负数: {result.test_case}")

    # WAI 合理范围校验（磨损指标不应为负）
    if result.wai is not None and result.wai < 0:
        errors.append(f"WAI 不能为负数: {result.wai}")

    return errors


# ============================================================
# 处理结果
# ============================================================

@dataclass
class FileProcessResult:
    """单个文件的处理结果。"""

    file_name: str
    file_path: str
    action: str  # "parsed" | "skipped" | "failed"
    summary_id: Optional[int] = None
    metric_count: int = 0
    overall_result: Optional[str] = None
    error: Optional[str] = None


@dataclass
class BatchProcessResult:
    """批量处理结果汇总。"""

    success: int = 0
    failed: int = 0
    skipped: int = 0
    details: list[FileProcessResult] = None

    def __post_init__(self) -> None:
        if self.details is None:
            self.details = []

    @property
    def total(self) -> int:
        return self.success + self.failed + self.skipped


# ============================================================
# 解析入库服务
# ============================================================

class ParseService:
    """解析入库服务，封装完整的「解析 → 去重 → 入库 → 记录」流程。

    通过回调函数支持不同入口的日志输出需求：
    - CLI: 使用 logger.info
    - GUI: 使用 _log_parse 回调更新 UI
    - FileWatcher: 使用 logger.info/debug
    """

    def __init__(
        self,
        db: DatabaseConnection,
        repo: MetricsRepository | None = None,
        parser: LogParser | None = None,
    ) -> None:
        self._db = db
        self._repo = repo or MetricsRepository(db)
        self._parser = parser or LogParser()

    def process_file(
        self,
        file_path: str,
        *,
        on_log: Optional[callable] = None,
    ) -> FileProcessResult:
        """处理单个日志文件：解析 → 增量判断 → 入库。

        Args:
            file_path: 日志文件绝对路径。
            on_log: 可选的日志回调函数 (msg: str) -> None。

        Returns:
            FileProcessResult 处理结果。
        """
        file_name = os.path.basename(file_path)
        _log = on_log or (lambda msg: logger.info(msg))

        try:
            result = self._parser.parse_file(file_path)

            # 数据验证
            validation_errors = validate_parse_result(result)
            if validation_errors:
                error_msg = f"数据验证失败: {'; '.join(validation_errors)}"
                _log(f"  ⚠️ 验证失败: {file_name} - {error_msg}")
                logger.warning("数据验证失败 [%s]: %s", file_name, validation_errors)
                # 验证失败仍记录到 process_log
                with self._db.connect() as conn:
                    self._repo.insert_process_log(
                        conn,
                        file_path=file_path,
                        file_size=result.file_size,
                        file_mtime=result.file_mtime,
                        action="failed",
                        error_message=error_msg,
                    )
                return FileProcessResult(
                    file_name=file_name,
                    file_path=file_path,
                    action="failed",
                    error=error_msg,
                )

            with self._db.connect() as conn:
                # 增量判断
                if self._repo.is_file_processed(
                    conn, file_path, result.file_size, result.file_mtime
                ):
                    _log(f"  ⏭️ 跳过（已处理且未变化）: {file_name}")
                    return FileProcessResult(
                        file_name=file_name,
                        file_path=file_path,
                        action="skipped",
                    )

                # 解析失败
                if result.status == "Failed":
                    self._repo.insert_process_log(
                        conn,
                        file_path=file_path,
                        file_size=result.file_size,
                        file_mtime=result.file_mtime,
                        action="failed",
                        error_message=result.error,
                    )
                    _log(f"  ❌ 解析失败: {file_name} - {result.error}")
                    return FileProcessResult(
                        file_name=file_name,
                        file_path=file_path,
                        action="failed",
                        error=result.error,
                    )

                # 清除同路径旧记录（文件内容变化时的重解析场景）
                self._repo.delete_summary_by_filepath(conn, result.file_path)

                # 插入主表
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
                    fail_sections=json.dumps(
                        result.fail_sections, ensure_ascii=False
                    ),
                    controller=result.controller,
                    capacity_mb=result.capacity_mb,
                    capacity_sectors=result.capacity_sectors,
                    part_number=result.part_number,
                    task_link=result.task_link,
                    test_cycle=result.test_cycle,
                    test_case=result.test_case,
                    rtms_result=result.rtms_result,
                    rtms_code=result.rtms_code,
                    wai=result.wai,
                    slc_pe_min=result.slc_pe_min,
                    slc_pe_max=result.slc_pe_max,
                    tlc_pe_min=result.tlc_pe_min,
                    tlc_pe_max=result.tlc_pe_max,
                    increase_bad_block=result.increase_bad_block,
                    parse_status=result.status,
                )

                # 批量插入指标
                metric_tuples = [m.as_tuple() for m in result.metrics]
                self._repo.insert_metrics_batch(conn, summary_id, metric_tuples)

                # 记录处理日志
                self._repo.insert_process_log(
                    conn,
                    file_path=file_path,
                    file_size=result.file_size,
                    file_mtime=result.file_mtime,
                    action="parsed",
                    summary_id=summary_id,
                )

            _log(
                f"  ✅ 入库: {file_name} | 指标={len(result.metrics)}"
                f" | 结果={result.overall_result}"
            )
            return FileProcessResult(
                file_name=file_name,
                file_path=file_path,
                action="parsed",
                summary_id=summary_id,
                metric_count=len(result.metrics),
                overall_result=result.overall_result,
            )

        except Exception as exc:
            error_msg = f"解析异常: {exc}"
            _log(f"  ❌ 异常: {file_name} - {exc}")
            logger.error("解析异常 [%s]: %s", file_name, exc, exc_info=True)
            return FileProcessResult(
                file_name=file_name,
                file_path=file_path,
                action="failed",
                error=error_msg,
            )

    def process_files(
        self,
        file_paths: list[str],
        *,
        on_log: Optional[callable] = None,
    ) -> BatchProcessResult:
        """批量处理日志文件列表。

        Args:
            file_paths: 日志文件绝对路径列表。
            on_log: 可选的日志回调函数 (msg: str) -> None。

        Returns:
            BatchProcessResult 汇总结果。
        """
        batch = BatchProcessResult()
        _log = on_log or (lambda msg: logger.info(msg))

        for file_path in file_paths:
            file_name = os.path.basename(file_path)
            _log(f"解析: {file_name}")

            result = self.process_file(file_path, on_log=on_log)
            batch.details.append(result)

            if result.action == "parsed":
                batch.success += 1
            elif result.action == "skipped":
                batch.skipped += 1
            else:
                batch.failed += 1

        _log(f"处理完成: 成功={batch.success}, 失败={batch.failed}, 跳过={batch.skipped}")
        logger.info(
            "批量处理完成: 成功=%d, 失败=%d, 跳过=%d, 总计=%d",
            batch.success, batch.failed, batch.skipped, batch.total,
        )
        return batch

