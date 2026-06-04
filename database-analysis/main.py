"""
EMMC 测试日志解析与分析系统 - CLI 入口

子命令：
  init-db   初始化数据库（建表建索引）
  parse     解析日志文件入库
  query     查询数据
  compare   对比分析
  report    导出 RMA 报告
  watch     启动信号文件监听服务

用法示例：
  python main.py init-db
  python main.py parse --file RTMS_RTMSLOG_0.txt
  python main.py parse --dir D:/logs/
  python main.py query --device DM3720.012.13 --section Wear_Detection
  python main.py query --result Fail
  python main.py compare --ids 1,5 --section Wear_Detection
  python main.py report --output report.xlsx
  python main.py watch --signal-dir D:/signals/
"""
import argparse
import json
import logging
import os
import sys

# 将脚本目录加入 Python 路径，确保相对导入可用
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from database import DatabaseConnection, MetricsRepository
from log_parser import LogParser
from schema import init_database

# 日志配置
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# 默认配置文件路径
DEFAULT_CONFIG_PATH = os.path.join(_SCRIPT_DIR, "config.json")


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """读取配置文件，返回配置字典。

    Args:
        config_path: 配置文件路径，默认使用脚本目录下的 config.json。

    Returns:
        配置字典。
    """
    if not os.path.exists(config_path):
        logger.warning("配置文件不存在: %s，使用默认配置", config_path)
        return {
            "database": {"path": "emmc_analysis.db"},
            "log_sources": {
                "scan_dirs": [],
                "file_extensions": [".txt", ".log"],
            },
            "export": {"report_dir": "reports"},
            "anomaly_thresholds": {},
        }

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_db_path(config: dict) -> str:
    """从配置中获取数据库绝对路径。

    Args:
        config: 配置字典。

    Returns:
        数据库文件绝对路径。
    """
    db_path = config.get("database", {}).get("path", "emmc_analysis.db")
    if not os.path.isabs(db_path):
        db_path = os.path.join(_SCRIPT_DIR, db_path)
    return db_path


# ============================================================
# 子命令实现
# ============================================================

def cmd_init_db(args: argparse.Namespace) -> None:
    """初始化数据库：建表建索引。"""
    config = load_config(args.config)
    db_path = get_db_path(config)

    logger.info("初始化数据库: %s", db_path)
    db = DatabaseConnection(db_path)
    with db.connect() as conn:
        init_database(conn)
    logger.info("数据库初始化完成")


def cmd_parse(args: argparse.Namespace) -> None:
    """解析日志文件入库。"""
    config = load_config(args.config)
    db_path = get_db_path(config)
    db = DatabaseConnection(db_path)
    repo = MetricsRepository(db)
    parser = LogParser()

    # 确保数据库已初始化
    with db.connect() as conn:
        init_database(conn)

    # 收集待解析文件列表
    file_paths: list[str] = []

    if args.file:
        # 单文件模式
        abs_path = os.path.abspath(args.file)
        if os.path.exists(abs_path):
            file_paths.append(abs_path)
        else:
            logger.error("文件不存在: %s", abs_path)
            return

    elif args.dir:
        # 目录模式：先解压 ZIP，再扫描日志文件
        from file_watcher import extract_all_zips

        scan_dir = os.path.abspath(args.dir)
        if not os.path.isdir(scan_dir):
            logger.error("目录不存在: %s", scan_dir)
            return

        # 自动解压目录下的所有 ZIP 文件
        logger.info("扫描并解压 %s 下的 ZIP 文件...", scan_dir)
        extract_all_zips(scan_dir)

        extensions = config.get("log_sources", {}).get("file_extensions", [".txt", ".log"])
        for root, _, files in os.walk(scan_dir):
            for fname in files:
                if any(fname.endswith(ext) for ext in extensions):
                    file_paths.append(os.path.join(root, fname))

        logger.info("在 %s 中发现 %d 个日志文件", scan_dir, len(file_paths))
    else:
        logger.error("请指定 --file 或 --dir 参数")
        return

    if not file_paths:
        logger.info("无待解析文件")
        return

    # 逐文件解析入库
    success_count = 0
    fail_count = 0
    skip_count = 0

    for file_path in file_paths:
        file_name = os.path.basename(file_path)
        logger.info("解析: %s", file_name)

        try:
            result = parser.parse_file(file_path)

            with db.connect() as conn:
                # 增量判断
                if repo.is_file_processed(conn, file_path, result.file_size, result.file_mtime):
                    logger.info("跳过（已处理且未变化）: %s", file_name)
                    skip_count += 1
                    continue

                if result.status == "Failed":
                    # 记录失败
                    repo.insert_process_log(
                        conn,
                        file_path=file_path,
                        file_size=result.file_size,
                        file_mtime=result.file_mtime,
                        action="failed",
                        error_message=result.error,
                    )
                    fail_count += 1
                    logger.error("解析失败: %s - %s", file_name, result.error)
                    continue

                # 插入主表
                import json as _json
                summary_id = repo.insert_summary(
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
                repo.insert_metrics_batch(conn, summary_id, metric_tuples)

                # 记录处理日志
                repo.insert_process_log(
                    conn,
                    file_path=file_path,
                    file_size=result.file_size,
                    file_mtime=result.file_mtime,
                    action="parsed",
                    summary_id=summary_id,
                )

            success_count += 1
            logger.info(
                "入库成功: %s | 指标数=%d | 结果=%s",
                file_name, len(result.metrics), result.overall_result,
            )

        except Exception as exc:
            fail_count += 1
            logger.error("解析异常: %s - %s", file_name, exc, exc_info=True)

    logger.info(
        "解析完成: 成功=%d, 失败=%d, 跳过=%d, 总计=%d",
        success_count, fail_count, skip_count, len(file_paths),
    )


def cmd_query(args: argparse.Namespace) -> None:
    """查询数据。"""
    config = load_config(args.config)
    db_path = get_db_path(config)
    db = DatabaseConnection(db_path)
    repo = MetricsRepository(db)

    with db.connect() as conn:
        if args.result or args.device or args.fw:
            # 主表查询
            summaries = repo.get_summaries(
                conn,
                device_name=args.device,
                fw_version=args.fw,
                overall_result=args.result,
            )
            if not summaries:
                print("未找到匹配的记录")
                return

            print(f"\n{'='*80}")
            print(f"{'ID':>4} | {'设备名':<20} | {'固件版本':<30} | {'结果':<6} | {'WAI':>8}")
            print(f"{'-'*80}")
            for s in summaries:
                print(
                    f"{s['id']:>4} | {s.get('device_name',''):<20} | "
                    f"{s.get('fw_version',''):<30} | "
                    f"{s.get('overall_result',''):<6} | "
                    f"{s.get('wai','') or '':>8}"
                )

            # 如果指定了 section 或 metric_key，进一步查询指标
            if args.section or args.key:
                for s in summaries:
                    metrics = repo.get_metrics(
                        conn,
                        summary_id=s["id"],
                        section=args.section,
                        metric_key=args.key,
                    )
                    if metrics:
                        print(f"\n--- 设备 {s.get('device_name', '')} (ID={s['id']}) 的指标 ---")
                        print(f"{'Section':<35} | {'指标名':<25} | {'原始值':<20} | {'数值':>10}")
                        print(f"{'-'*95}")
                        for m in metrics:
                            print(
                                f"{m['section']:<35} | {m['metric_key_raw']:<25} | "
                                f"{m['raw_value']:<20} | "
                                f"{m.get('num_value','') or '':>10}"
                            )
        else:
            print("请指定查询条件：--device / --fw / --result / --section / --key")


def cmd_compare(args: argparse.Namespace) -> None:
    """对比分析。"""
    config = load_config(args.config)
    db_path = get_db_path(config)
    db = DatabaseConnection(db_path)
    repo = MetricsRepository(db)

    summary_ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
    if len(summary_ids) < 2:
        print("对比需要至少 2 个 ID")
        return

    with db.connect() as conn:
        all_metrics = repo.compare_metrics(conn, summary_ids, section=args.section)

    if not all_metrics:
        print("未找到匹配的指标数据")
        return

    # 按 metric_key 分组展示
    from collections import defaultdict
    grouped: dict[str, dict] = defaultdict(dict)
    for m in all_metrics:
        key = f"{m['section']}/{m['metric_key_raw']}"
        grouped[key][m["summary_id"]] = m

    print(f"\n{'='*100}")
    print(f"{'Section/指标':<45} |", end="")
    for sid in summary_ids:
        print(f" ID={sid:<15} |", end="")
    print(f" {'差异':>10}")
    print(f"{'-'*100}")

    for key, sid_map in grouped.items():
        values = []
        print(f"{key:<45} |", end="")
        for sid in summary_ids:
            if sid in sid_map:
                val = sid_map[sid]["raw_value"]
                num = sid_map[sid].get("num_value")
                values.append(num)
                print(f" {val:<18}|", end="")
            else:
                values.append(None)
                print(f" {'N/A':<18}|", end="")

        # 计算差异
        nums = [v for v in values if v is not None]
        if len(nums) >= 2:
            diff = nums[-1] - nums[0]
            print(f" {diff:>10.2f}")
        else:
            print(f" {'---':>10}")


def cmd_report(args: argparse.Namespace) -> None:
    """导出 RMA 报告。"""
    from rma_report import RMAReportGenerator

    config = load_config(args.config)
    db_path = get_db_path(config)
    db = DatabaseConnection(db_path)

    output_path = args.output
    if not os.path.isabs(output_path):
        report_dir = config.get("export", {}).get("report_dir", "reports")
        if not os.path.isabs(report_dir):
            report_dir = os.path.join(_SCRIPT_DIR, report_dir)
        os.makedirs(report_dir, exist_ok=True)
        output_path = os.path.join(report_dir, output_path)

    generator = RMAReportGenerator(db)
    result_path = generator.generate(
        output_path=output_path,
        device_name=args.device,
        fw_version=args.fw,
    )
    print(f"报告已生成: {result_path}")


def cmd_watch(args: argparse.Namespace) -> None:
    """启动信号文件监听服务。"""
    from file_watcher import FileWatcher

    config = load_config(args.config)
    db_path = get_db_path(config)

    signal_dir = args.signal_dir
    if not signal_dir:
        signal_dir = config.get("signal", {}).get("signal_dir", "signals")
    if not os.path.isabs(signal_dir):
        signal_dir = os.path.join(_SCRIPT_DIR, signal_dir)

    poll_interval = config.get("signal", {}).get("poll_interval_seconds", 5)

    watcher = FileWatcher(
        db_path=db_path,
        signal_dir=signal_dir,
        config=config,
    )
    logger.info("启动信号文件监听，目录: %s，轮询间隔: %ds", signal_dir, poll_interval)
    watcher.watch_loop(poll_interval=poll_interval)


# ============================================================
# CLI 参数解析
# ============================================================

def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        description="EMMC 测试日志解析与分析系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-c", "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"配置文件路径（默认: {DEFAULT_CONFIG_PATH}）",
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # init-db
    subparsers.add_parser("init-db", help="初始化数据库（建表建索引）")

    # parse
    parse_parser = subparsers.add_parser("parse", help="解析日志文件入库")
    parse_parser.add_argument("--file", help="单个日志文件路径")
    parse_parser.add_argument("--dir", help="日志文件目录")

    # query
    query_parser = subparsers.add_parser("query", help="查询数据")
    query_parser.add_argument("--device", help="按设备名过滤")
    query_parser.add_argument("--fw", help="按固件版本过滤")
    query_parser.add_argument("--result", help="按综合结果过滤（Pass/Fail）")
    query_parser.add_argument("--section", help="按 Section 过滤")
    query_parser.add_argument("--key", help="按指标名过滤")

    # compare
    compare_parser = subparsers.add_parser("compare", help="对比分析")
    compare_parser.add_argument("--ids", required=True, help="主表 ID 列表，逗号分隔")
    compare_parser.add_argument("--section", help="按 Section 过滤")

    # report
    report_parser = subparsers.add_parser("report", help="导出 RMA 报告")
    report_parser.add_argument("--output", default="rma_report.xlsx", help="输出文件路径")
    report_parser.add_argument("--device", help="按设备名过滤")
    report_parser.add_argument("--fw", help="按固件版本过滤")

    # watch
    watch_parser = subparsers.add_parser("watch", help="启动信号文件监听服务")
    watch_parser.add_argument("--signal-dir", help="信号文件目录")

    return parser


# 命令路由表
_COMMAND_MAP = {
    "init-db": cmd_init_db,
    "parse": cmd_parse,
    "query": cmd_query,
    "compare": cmd_compare,
    "report": cmd_report,
    "watch": cmd_watch,
}


def main() -> None:
    """CLI 主入口。"""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    handler = _COMMAND_MAP.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
