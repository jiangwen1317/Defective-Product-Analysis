# -*- coding: utf-8 -*-
"""
主入口模块

提供日志解析、定时监控和报告导出功能。
"""

import glob
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime
from typing import List, Optional

# 添加 src 目录到路径
sys.path.insert(0, os.path.dirname(__file__))

from src.config import Config, load_config, save_default_config
from src.database import Database, get_database
from src.export import ReportExporter, export_report
from src.parser import LogParser, parse_logs
from src.query import QueryBuilder, get_query


def setup_logging(log_file: Optional[str] = None, level: int = logging.INFO):
    """
    设置日志配置。

    Args:
        log_file: 日志文件路径
        level: 日志级别
    """
    handlers = [logging.StreamHandler()]

    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )


class Monitor:
    """日志目录监控器"""

    def __init__(
        self,
        parser: LogParser,
        config: Optional[Config] = None,
    ):
        """
        初始化监控器。

        Args:
            parser: 日志解析器
            config: 配置对象
        """
        self.parser = parser
        self.config = config or load_config()
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None

    def _scan_directory(self) -> List[str]:
        """
        扫描监控目录,返回需要解析的文件列表。

        Returns:
            文件路径列表
        """
        directory = self.config.monitor.directory
        extensions = self.config.monitor.extensions
        trigger_file = os.path.join(directory, self.config.monitor.trigger_file)

        # 检查信号文件
        has_trigger = os.path.exists(trigger_file)
        if has_trigger:
            logging.info(f"检测到信号文件: {trigger_file}")

        files = []
        for ext in extensions:
            pattern = os.path.join(directory, f"*{ext}")
            for file_path in glob.glob(pattern):
                basename = os.path.basename(file_path)
                # 跳过隐藏文件和信号文件
                if basename.startswith("."):
                    continue
                files.append(file_path)

        # 如果有信号文件,解析完成后删除它
        if has_trigger and files:
            try:
                os.remove(trigger_file)
                logging.info(f"已删除信号文件: {trigger_file}")
            except Exception as e:
                logging.warning(f"删除信号文件失败: {e}")

        return files

    def _parse_all(self) -> int:
        """
        解析目录下所有日志文件。

        Returns:
            成功解析的文件数
        """
        files = self._scan_directory()
        if not files:
            logging.debug("未发现新文件或变更文件")
            return 0

        logging.info(f"发现 {len(files)} 个日志文件待解析")

        success_count = 0
        for file_path in files:
            try:
                result = self.parser.parse_and_save(file_path)
                if result.success:
                    success_count += 1
            except Exception as e:
                logging.error(f"解析失败: {file_path}, 错误: {e}")

        return success_count

    def _monitor_loop(self):
        """监控循环"""
        logging.info(
            f"监控线程已启动,目录: {self.config.monitor.directory}, "
            f"间隔: {self.config.monitor.scan_interval}s"
        )

        while not self._stop_event.is_set():
            try:
                success_count = self._parse_all()
                if success_count > 0:
                    logging.info(f"本次解析成功: {success_count} 个文件")
            except Exception as e:
                logging.error(f"监控循环异常: {e}")

            # 等待下次扫描
            self._stop_event.wait(self.config.monitor.scan_interval)

        logging.info("监控线程已停止")

    def start(self):
        """启动监控"""
        if self._monitor_thread and self._monitor_thread.is_alive():
            logging.warning("监控已在运行中")
            return

        self._stop_event.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logging.info("定时监控已启动")

    def stop(self):
        """停止监控"""
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        logging.info("定时监控已停止")


def run_parse(args, config: Config):
    """
    执行单次解析。

    Args:
        args: 命令行参数
        config: 配置对象
    """
    db = get_database(config.database.path)

    parser = LogParser(db=db, config=config)

    if args.file:
        # 解析单个文件
        results = [parser.parse_and_save(args.file)]
    elif args.directory:
        # 解析目录
        results = parser.parse_directory(args.directory)
    else:
        # 使用配置的监控目录
        results = parser.parse_directory(config.monitor.directory)

    # 输出统计
    success = sum(1 for r in results if r.success)
    failed = len(results) - success

    print(f"\n{'='*60}")
    print("解析完成")
    print(f"{'='*60}")
    print(f"总文件数: {len(results)}")
    print(f"成功: {success}")
    print(f"失败: {failed}")
    print("=" * 60)

    if args.export and success > 0:
        export_path = os.path.join(
            config.export.output_dir,
            f"parse_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )
        export_report(export_path, db)
        print(f"\n报告已导出: {export_path}")


def run_watch(args, config: Config):
    """
    启动定时监控。

    Args:
        args: 命令行参数
        config: 配置对象
    """
    db = get_database(config.database.path)

    # 更新扫描间隔
    if args.interval:
        config.monitor.scan_interval = args.interval * 60  # 转换为秒

    parser = LogParser(db=db, config=config)
    monitor = Monitor(parser, config)

    # 设置信号处理
    def signal_handler(signum, frame):
        logging.info("收到停止信号")
        monitor.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 启动监控
    monitor.start()

    print("\n" + "=" * 60)
    print("定时监控已启动")
    print(f"监控目录: {config.monitor.directory}")
    print(f"扫描间隔: {config.monitor.scan_interval}s")
    print("按 Ctrl+C 停止")
    print("=" * 60 + "\n")

    # 保持主线程运行
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        monitor.stop()


def run_export(args, config: Config):
    """
    导出 RMA 报告。

    Args:
        args: 命令行参数
        config: 配置对象
    """
    db = get_database(config.database.path)
    exporter = ReportExporter(db=db, config=config)

    if args.output:
        output_path = args.output
    else:
        output_path = exporter.export_default()

    print(f"\n{'='*60}")
    print("报告导出完成")
    print(f"{'='*60}")
    print(f"文件路径: {output_path}")
    print("=" * 60)


def run_query(args, config: Config):
    """
    执行查询操作。

    Args:
        args: 命令行参数
        config: 配置对象
    """
    db = get_database(config.database.path)
    query = QueryBuilder(db)

    if args.list_devices:
        devices = query.get_unique_devices()
        print(f"\n{'='*60}")
        print(f"设备列表 (共 {len(devices)} 个)")
        print("=" * 60)
        for d in devices:
            print(f"  {d['device_name']} - {d['fw_version']}")

    elif args.list_sections:
        sections = query.get_unique_sections()
        print(f"\n{'='*60}")
        print(f"Section 列表 (共 {len(sections)} 个)")
        print("=" * 60)
        for s in sections:
            print(f"  {s}")

    elif args.list_metrics:
        metrics = query.get_unique_metric_keys(args.section)
        print(f"\n{'='*60}")
        print(f"指标列表 (共 {len(metrics)} 个)" +
              (f", Section: {args.section}" if args.section else ""))
        print("=" * 60)
        for m in metrics:
            print(f"  {m}")

    elif args.stat:
        stats = query.get_statistics(args.stat, args.section)
        print(f"\n{'='*60}")
        print(f"指标统计: {args.stat}" +
              (f", Section: {args.section}" if args.section else ""))
        print("=" * 60)
        print(f"  最小值: {stats['min']:.4f}")
        print(f"  最大值: {stats['max']:.4f}")
        print(f"  平均值: {stats['avg']:.4f}")
        print(f"  样本数: {stats['count']}")

    elif args.show:
        summary = query.get_summary_by_id(args.show)
        if summary:
            print(f"\n{'='*60}")
            print(f"测试记录 ID: {summary.id}")
            print("=" * 60)
            print(f"  设备名称: {summary.device_name}")
            print(f"  固件版本: {summary.fw_version}")
            print(f"  工具版本: {summary.tool_version}")
            print(f"  Flash ID: {summary.flash_id}")
            print(f"  测试循环: {summary.test_cycles}")
            print(f"  测试结果: {summary.test_result}")
            print(f"  解析状态: {summary.parse_status}")
            print(f"  文件名: {summary.file_name}")
            print(f"  创建时间: {datetime.fromtimestamp(summary.created_at)}")
            print("=" * 60)

            # 显示该记录的指标
            metrics = query.get_metrics_by_summary(summary.id)
            if metrics:
                print(f"\n指标列表 (共 {len(metrics)} 个):")
                print("-" * 40)
                current_section = None
                for m in metrics:
                    if m.section != current_section:
                        print(f"\n[{m.section}]")
                        current_section = m.section
                    value = m.num_value if m.num_value is not None else m.raw_value
                    print(f"  {m.metric_key}: {value}")
        else:
            print(f"未找到 ID 为 {args.show} 的记录")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(
        description="EMMC 测试日志数据库分析系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 单次解析日志目录
  python main.py --parse

  # 解析指定目录
  python main.py --parse --directory ./logs

  # 解析单个文件
  python main.py --parse --file ./logs/RTMS_RTMSLOG_0.txt

  # 解析后导出报告
  python main.py --parse --export

  # 启动定时监控
  python main.py --watch

  # 指定监控间隔(分钟)
  python main.py --watch --interval 10

  # 导出报告
  python main.py --export

  # 指定输出路径
  python main.py --export --output ./report.xlsx

  # 查询操作
  python main.py --list-devices
  python main.py --list-sections
  python main.py --list-metrics --section Wear_Detection
  python main.py --stat WAI
  python main.py --show 1
        """,
    )

    # 通用参数
    parser.add_argument(
        "-c", "--config",
        default="config.json",
        help="配置文件路径 (默认: config.json)"
    )
    parser.add_argument(
        "--log",
        help="日志文件路径"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别 (默认: INFO)"
    )

    # 解析模式
    parser.add_argument(
        "--parse",
        action="store_true",
        help="执行单次解析"
    )
    parser.add_argument(
        "-f", "--file",
        help="解析单个文件"
    )
    parser.add_argument(
        "-d", "--directory",
        help="解析指定目录"
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="解析后导出报告"
    )

    # 监控模式
    parser.add_argument(
        "--watch",
        action="store_true",
        help="启动定时监控"
    )
    parser.add_argument(
        "-i", "--interval",
        type=int,
        help="监控间隔(分钟)"
    )

    # 导出模式
    parser.add_argument(
        "-o", "--output",
        help="导出报告路径"
    )

    # 查询模式
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="列出所有设备"
    )
    parser.add_argument(
        "--list-sections",
        action="store_true",
        help="列出所有 Section"
    )
    parser.add_argument(
        "--list-metrics",
        action="store_true",
        help="列出所有指标"
    )
    parser.add_argument(
        "--section",
        help="按 Section 筛选"
    )
    parser.add_argument(
        "--stat",
        metavar="METRIC_KEY",
        help="显示指标统计信息"
    )
    parser.add_argument(
        "--show",
        type=int,
        metavar="ID",
        help="显示指定 ID 的详细信息"
    )

    args = parser.parse_args()

    # 设置日志
    log_level = getattr(logging, args.log_level)
    setup_logging(args.log, log_level)

    # 加载配置
    try:
        config = load_config(args.config)
    except Exception as e:
        logging.error(f"加载配置失败: {e}")
        # 使用默认配置
        config = Config()
        logging.info("使用默认配置")

    # 确保关键目录存在
    os.makedirs(config.monitor.directory, exist_ok=True)
    os.makedirs(config.export.output_dir, exist_ok=True)

    # 执行对应模式
    if args.parse:
        run_parse(args, config)
    elif args.watch:
        run_watch(args, config)
    elif args.export:
        run_export(args, config)
    else:
        # 默认执行查询
        run_query(args, config)


if __name__ == "__main__":
    main()
