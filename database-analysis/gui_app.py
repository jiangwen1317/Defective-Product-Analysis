"""
EMMC 测试日志解析与分析系统 - GUI 界面

基于 CustomTkinter 构建的现代化桌面应用，
提供数据导入、查询、对比、报告导出等完整功能。
"""
import json
import logging
import os
import sys
import threading
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

# 将脚本目录加入 Python 路径
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from database import DatabaseConnection, MetricsRepository
from log_parser import LogParser
from schema import init_database
from sql_presets import SQL_PRESETS

logger = logging.getLogger(__name__)

# 主题配置
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# 默认配置文件路径
DEFAULT_CONFIG_PATH = os.path.join(_SCRIPT_DIR, "config.json")


def load_config() -> dict:
    """读取配置文件。"""
    if not os.path.exists(DEFAULT_CONFIG_PATH):
        return {"database": {"path": "emmc_analysis.db"}}
    with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_db_path() -> str:
    """获取数据库绝对路径。"""
    config = load_config()
    db_path = config.get("database", {}).get("path", "emmc_analysis.db")
    if not os.path.isabs(db_path):
        db_path = os.path.join(_SCRIPT_DIR, db_path)
    return db_path


class App(ctk.CTk):
    """主应用窗口。"""

    def __init__(self) -> None:
        super().__init__()

        self.title("EMMC 测试日志分析系统")
        self.geometry("1100x720")
        self.minsize(900, 600)

        # 数据库初始化
        self._db_path = get_db_path()
        self._db = DatabaseConnection(self._db_path)
        self._init_db()

        # 构建界面
        self._build_ui()

    def _init_db(self) -> None:
        """确保数据库已初始化。"""
        with self._db.connect() as conn:
            init_database(conn)

    def _build_ui(self) -> None:
        """构建主界面。"""
        # 顶部状态栏
        status_frame = ctk.CTkFrame(self, height=36, corner_radius=0)
        status_frame.pack(fill="x", padx=0, pady=0)
        status_frame.pack_propagate(False)

        self._status_label = ctk.CTkLabel(
            status_frame,
            text=f"  数据库: {os.path.basename(self._db_path)}",
            font=ctk.CTkFont(size=12),
            anchor="w",
        )
        self._status_label.pack(side="left", padx=10)

        # 主标签页
        self._tabview = ctk.CTkTabview(self)
        self._tabview.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        # 创建各标签页
        self._build_parse_tab(self._tabview.add("📥 数据导入"))
        self._build_query_tab(self._tabview.add("🔍 数据查询"))
        self._build_compare_tab(self._tabview.add("⚖️ 指标对比"))
        self._build_sql_tab(self._tabview.add("📋 预设查询"))
        self._build_report_tab(self._tabview.add("📊 报告导出"))

    # ================================================================
    # Tab 1: 数据导入
    # ================================================================

    def _build_parse_tab(self, parent: ctk.CTkFrame) -> None:
        """构建数据导入标签页。"""
        # 文件选择区
        file_frame = ctk.CTkFrame(parent)
        file_frame.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(file_frame, text="解析模式", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=15, pady=(10, 5)
        )

        # 单文件
        row1 = ctk.CTkFrame(file_frame, fg_color="transparent")
        row1.pack(fill="x", padx=15, pady=3)
        self._parse_file_var = ctk.StringVar()
        ctk.CTkEntry(row1, textvariable=self._parse_file_var, placeholder_text="选择日志文件...").pack(
            side="left", fill="x", expand=True, padx=(0, 5)
        )
        ctk.CTkButton(row1, text="浏览", width=80, command=self._browse_parse_file).pack(side="left")

        # 目录
        row2 = ctk.CTkFrame(file_frame, fg_color="transparent")
        row2.pack(fill="x", padx=15, pady=3)
        self._parse_dir_var = ctk.StringVar()
        ctk.CTkEntry(row2, textvariable=self._parse_dir_var, placeholder_text="选择日志目录（自动解压ZIP）...").pack(
            side="left", fill="x", expand=True, padx=(0, 5)
        )
        ctk.CTkButton(row2, text="浏览", width=80, command=self._browse_parse_dir).pack(side="left")

        # 按钮区
        btn_frame = ctk.CTkFrame(file_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=(8, 12))
        ctk.CTkButton(btn_frame, text="📄 解析单文件", width=160, command=self._parse_single).pack(
            side="left", padx=(0, 10)
        )
        ctk.CTkButton(btn_frame, text="📁 解析整个目录", width=160, command=self._parse_directory).pack(
            side="left", padx=(0, 10)
        )
        ctk.CTkButton(btn_frame, text="🗑️ 清空数据库", width=120, fg_color="darkred",
                       hover_color="red", command=self._clear_database).pack(side="right")

        # 日志输出区
        log_frame = ctk.CTkFrame(parent)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        ctk.CTkLabel(log_frame, text="处理日志", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=15, pady=(10, 5)
        )

        self._parse_log = ctk.CTkTextbox(log_frame, font=ctk.CTkFont(family="Consolas", size=12))
        self._parse_log.pack(fill="both", expand=True, padx=15, pady=(0, 15))

    def _browse_parse_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择日志文件",
            filetypes=[("日志文件", "*.txt *.log"), ("所有文件", "*.*")],
        )
        if path:
            self._parse_file_var.set(path)

    def _browse_parse_dir(self) -> None:
        path = filedialog.askdirectory(title="选择日志目录")
        if path:
            self._parse_dir_var.set(path)

    def _log_parse(self, msg: str) -> None:
        """向日志区追加消息（线程安全）。"""
        ts = datetime.now().strftime("%H:%M:%S")
        self._parse_log.insert("end", f"[{ts}] {msg}\n")
        self._parse_log.see("end")

    def _parse_single(self) -> None:
        file_path = self._parse_file_var.get().strip()
        if not file_path or not os.path.exists(file_path):
            messagebox.showwarning("提示", "请先选择有效的日志文件")
            return
        threading.Thread(target=self._do_parse, args=([file_path],), daemon=True).start()

    def _parse_directory(self) -> None:
        from file_watcher import extract_all_zips, discover_log_files

        directory = self._parse_dir_var.get().strip()
        if not directory or not os.path.isdir(directory):
            messagebox.showwarning("提示", "请先选择有效的目录")
            return

        def _run() -> None:
            self._log_parse(f"开始处理目录: {directory}")
            # 解压 ZIP
            self._log_parse("正在解压 ZIP 文件...")
            extract_all_zips(directory)
            # 发现日志文件
            config = load_config()
            extensions = config.get("log_sources", {}).get("file_extensions", [".txt", ".log"])
            files = discover_log_files(directory, extensions)
            self._log_parse(f"发现 {len(files)} 个日志文件")
            # 解析
            self._do_parse(files)

        threading.Thread(target=_run, daemon=True).start()

    def _do_parse(self, file_paths: list[str]) -> None:
        """执行解析入库（在后台线程运行）。"""
        parser = LogParser()
        repo = MetricsRepository(self._db)
        success = failed = skipped = 0

        for file_path in file_paths:
            file_name = os.path.basename(file_path)
            self._log_parse(f"解析: {file_name}")

            try:
                result = parser.parse_file(file_path)

                with self._db.connect() as conn:
                    if repo.is_file_processed(conn, file_path, result.file_size, result.file_mtime):
                        self._log_parse(f"  ⏭️ 跳过（已处理）: {file_name}")
                        skipped += 1
                        continue

                    if result.status == "Failed":
                        repo.insert_process_log(
                            conn, file_path=file_path, file_size=result.file_size,
                            file_mtime=result.file_mtime, action="failed",
                            error_message=result.error,
                        )
                        self._log_parse(f"  ❌ 失败: {file_name} - {result.error}")
                        failed += 1
                        continue

                    summary_id = repo.insert_summary(
                        conn,
                        file_name=result.file_name, file_path=result.file_path,
                        file_size=result.file_size, file_mtime=result.file_mtime,
                        device_name=result.device_name, device_tool_name=result.device_tool_name,
                        device_config_name=result.device_config_name,
                        fw_version=result.fw_version, mp_tool_version=result.mp_tool_version,
                        flash_id=result.flash_id, original_bad_block=result.original_bad_block,
                        cycles=result.cycles, overall_result=result.overall_result,
                        fail_sections=json.dumps(result.fail_sections, ensure_ascii=False),
                        wai=result.wai, slc_pe_min=result.slc_pe_min, slc_pe_max=result.slc_pe_max,
                        tlc_pe_min=result.tlc_pe_min, tlc_pe_max=result.tlc_pe_max,
                        increase_bad_block=result.increase_bad_block,
                    )
                    repo.insert_metrics_batch(conn, summary_id, [m.as_tuple() for m in result.metrics])
                    repo.insert_process_log(
                        conn, file_path=file_path, file_size=result.file_size,
                        file_mtime=result.file_mtime, action="parsed", summary_id=summary_id,
                    )

                success += 1
                self._log_parse(
                    f"  ✅ 入库: {file_name} | 指标={len(result.metrics)} | 结果={result.overall_result}"
                )
            except Exception as exc:
                failed += 1
                self._log_parse(f"  ❌ 异常: {file_name} - {exc}")

        self._log_parse(f"\n{'='*50}")
        self._log_parse(f"处理完成: 成功={success}, 失败={failed}, 跳过={skipped}")
        self._update_status()

    def _clear_database(self) -> None:
        if not messagebox.askyesno("确认", "确定要清空数据库中所有数据吗？此操作不可撤销！"):
            return
        with self._db.connect() as conn:
            conn.execute("DELETE FROM test_metrics")
            conn.execute("DELETE FROM test_summary")
            conn.execute("DELETE FROM process_log")
        self._log_parse("数据库已清空")
        self._update_status()

    def _update_status(self) -> None:
        """更新状态栏中的记录数。"""
        try:
            with self._db.connect() as conn:
                count = conn.execute("SELECT COUNT(*) FROM test_summary").fetchone()[0]
            self._status_label.configure(
                text=f"  数据库: {os.path.basename(self._db_path)}  |  已导入: {count} 条记录"
            )
        except Exception:
            pass

    # ================================================================
    # Tab 2: 数据查询
    # ================================================================

    def _build_query_tab(self, parent: ctk.CTkFrame) -> None:
        """构建数据查询标签页。"""
        # 筛选条件
        filter_frame = ctk.CTkFrame(parent)
        filter_frame.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(filter_frame, text="筛选条件", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=15, pady=(10, 5)
        )

        grid = ctk.CTkFrame(filter_frame, fg_color="transparent")
        grid.pack(fill="x", padx=15, pady=(0, 10))

        # 行 1
        self._q_device = ctk.StringVar()
        self._q_fw = ctk.StringVar()
        self._q_result = ctk.StringVar(value="")

        ctk.CTkLabel(grid, text="设备名:").grid(row=0, column=0, padx=(0, 5), pady=3, sticky="e")
        ctk.CTkEntry(grid, textvariable=self._q_device, width=180).grid(row=0, column=1, padx=(0, 15), pady=3)

        ctk.CTkLabel(grid, text="固件版本:").grid(row=0, column=2, padx=(0, 5), pady=3, sticky="e")
        ctk.CTkEntry(grid, textvariable=self._q_fw, width=180).grid(row=0, column=3, padx=(0, 15), pady=3)

        ctk.CTkLabel(grid, text="结果:").grid(row=0, column=4, padx=(0, 5), pady=3, sticky="e")
        ctk.CTkComboBox(grid, variable=self._q_result, values=["", "Pass", "Fail"], width=100).grid(
            row=0, column=5, pady=3
        )

        # 行 2
        self._q_section = ctk.StringVar()
        self._q_key = ctk.StringVar()

        ctk.CTkLabel(grid, text="Section:").grid(row=1, column=0, padx=(0, 5), pady=3, sticky="e")
        ctk.CTkEntry(grid, textvariable=self._q_section, width=180).grid(row=1, column=1, padx=(0, 15), pady=3)

        ctk.CTkLabel(grid, text="指标名:").grid(row=1, column=2, padx=(0, 5), pady=3, sticky="e")
        ctk.CTkEntry(grid, textvariable=self._q_key, width=180).grid(row=1, column=3, padx=(0, 15), pady=3)

        ctk.CTkButton(grid, text="🔍 查询", width=100, command=self._do_query).grid(row=1, column=5, pady=3)

        # 结果表格
        result_frame = ctk.CTkFrame(parent)
        result_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self._query_count_label = ctk.CTkLabel(result_frame, text="查询结果", font=ctk.CTkFont(size=14, weight="bold"))
        self._query_count_label.pack(anchor="w", padx=15, pady=(10, 5))

        # Treeview
        tree_frame = ctk.CTkFrame(result_frame, fg_color="transparent")
        tree_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        columns = ("id", "device", "fw_version", "section", "key", "value", "num_value", "result")
        self._query_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=20)

        headers = {
            "id": ("ID", 50), "device": ("设备名", 130), "fw_version": ("固件版本", 200),
            "section": ("Section", 180), "key": ("指标名", 150), "value": ("原始值", 120),
            "num_value": ("数值", 80), "result": ("结果", 60),
        }
        for col, (text, width) in headers.items():
            self._query_tree.heading(col, text=text)
            self._query_tree.column(col, width=width, minwidth=40)

        # 滚动条
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self._query_tree.yview)
        self._query_tree.configure(yscrollcommand=scrollbar.set)
        self._query_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _do_query(self) -> None:
        """执行查询。"""
        repo = MetricsRepository(self._db)

        with self._db.connect() as conn:
            summaries = repo.get_summaries(
                conn,
                device_name=self._q_device.get() or None,
                fw_version=self._q_fw.get() or None,
                overall_result=self._q_result.get() or None,
                limit=500,
            )

        # 清空旧数据
        for item in self._query_tree.get_children():
            self._query_tree.delete(item)

        if not summaries:
            self._query_count_label.configure(text="查询结果: 无匹配记录")
            return

        section_filter = self._q_section.get() or None
        key_filter = self._q_key.get() or None

        row_count = 0
        with self._db.connect() as conn:
            for s in summaries:
                metrics = repo.get_metrics(
                    conn, summary_id=s["id"],
                    section=section_filter, metric_key=key_filter,
                )
                for m in metrics:
                    self._query_tree.insert("", "end", values=(
                        s["id"],
                        s.get("device_name", ""),
                        s.get("fw_version", ""),
                        m["section"],
                        m["metric_key_raw"],
                        m["raw_value"],
                        m.get("num_value", "") or "",
                        s.get("overall_result", ""),
                    ))
                    row_count += 1

        self._query_count_label.configure(text=f"查询结果: {row_count} 条指标（来自 {len(summaries)} 条记录）")

    # ================================================================
    # Tab 3: 指标对比
    # ================================================================

    def _build_compare_tab(self, parent: ctk.CTkFrame) -> None:
        """构建指标对比标签页。"""
        input_frame = ctk.CTkFrame(parent)
        input_frame.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(input_frame, text="对比设置", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=15, pady=(10, 5)
        )

        row = ctk.CTkFrame(input_frame, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=(0, 12))

        ctk.CTkLabel(row, text="记录 ID（逗号分隔）:").pack(side="left", padx=(0, 5))
        self._compare_ids = ctk.StringVar()
        ctk.CTkEntry(row, textvariable=self._compare_ids, width=200).pack(side="left", padx=(0, 15))

        ctk.CTkLabel(row, text="Section（可选）:").pack(side="left", padx=(0, 5))
        self._compare_section = ctk.StringVar()
        ctk.CTkEntry(row, textvariable=self._compare_section, width=180).pack(side="left", padx=(0, 15))

        ctk.CTkButton(row, text="⚖️ 对比", width=100, command=self._do_compare).pack(side="left")

        # 对比结果
        result_frame = ctk.CTkFrame(parent)
        result_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self._compare_count_label = ctk.CTkLabel(result_frame, text="对比结果", font=ctk.CTkFont(size=14, weight="bold"))
        self._compare_count_label.pack(anchor="w", padx=15, pady=(10, 5))

        tree_frame = ctk.CTkFrame(result_frame, fg_color="transparent")
        tree_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        columns = ("section", "key", "value_a", "value_b", "diff")
        self._compare_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=20)

        for col, text, width in [
            ("section", "Section", 200), ("key", "指标名", 180),
            ("value_a", "记录A", 150), ("value_b", "记录B", 150), ("diff", "差异", 100),
        ]:
            self._compare_tree.heading(col, text=text)
            self._compare_tree.column(col, width=width, minwidth=40)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self._compare_tree.yview)
        self._compare_tree.configure(yscrollcommand=scrollbar.set)
        self._compare_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _do_compare(self) -> None:
        """执行对比。"""
        from query_engine import QueryEngine

        ids_str = self._compare_ids.get().strip()
        if not ids_str:
            messagebox.showwarning("提示", "请输入要对比的记录 ID")
            return

        summary_ids = [int(x.strip()) for x in ids_str.split(",") if x.strip().isdigit()]
        if len(summary_ids) < 2:
            messagebox.showwarning("提示", "至少需要 2 个 ID 进行对比")
            return

        engine = QueryEngine(self._db)
        section = self._compare_section.get() or None
        results = engine.compare_devices(summary_ids, section=section)

        for item in self._compare_tree.get_children():
            self._compare_tree.delete(item)

        for r in results:
            val_a = r.get(f"value_{summary_ids[0]}", "N/A")
            val_b = r.get(f"value_{summary_ids[1]}", "N/A")
            diff = r.get("diff", "")
            self._compare_tree.insert("", "end", values=(
                r["section"], r["metric_key_raw"], val_a, val_b,
                f"{diff:.2f}" if isinstance(diff, (int, float)) else "",
            ))

        self._compare_count_label.configure(text=f"对比结果: {len(results)} 项指标")

    # ================================================================
    # Tab 4: 预设查询
    # ================================================================

    def _build_sql_tab(self, parent: ctk.CTkFrame) -> None:
        """构建预设查询标签页。"""
        # 预设选择
        select_frame = ctk.CTkFrame(parent)
        select_frame.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(select_frame, text="选择预设查询", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=15, pady=(10, 5)
        )

        row = ctk.CTkFrame(select_frame, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=(0, 12))

        preset_names = list(SQL_PRESETS.keys())
        self._sql_preset = ctk.StringVar(value=preset_names[0] if preset_names else "")

        ctk.CTkComboBox(row, variable=self._sql_preset, values=preset_names, width=250,
                          command=self._on_preset_change).pack(side="left", padx=(0, 10))

        ctk.CTkLabel(row, text="参数:").pack(side="left", padx=(0, 5))
        self._sql_params = ctk.StringVar()
        ctk.CTkEntry(row, textvariable=self._sql_params, width=250).pack(side="left", padx=(0, 10))

        ctk.CTkButton(row, text="▶ 执行", width=100, command=self._do_sql).pack(side="left")

        self._sql_desc_label = ctk.CTkLabel(select_frame, text="", font=ctk.CTkFont(size=12), text_color="gray")
        self._sql_desc_label.pack(anchor="w", padx=15, pady=(0, 10))
        self._on_preset_change(self._sql_preset.get())

        # 结果
        result_frame = ctk.CTkFrame(parent)
        result_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self._sql_count_label = ctk.CTkLabel(result_frame, text="查询结果", font=ctk.CTkFont(size=14, weight="bold"))
        self._sql_count_label.pack(anchor="w", padx=15, pady=(10, 5))

        tree_frame = ctk.CTkFrame(result_frame, fg_color="transparent")
        tree_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        self._sql_tree = ttk.Treeview(tree_frame, show="headings", height=20)
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self._sql_tree.yview)
        self._sql_tree.configure(yscrollcommand=scrollbar.set)
        self._sql_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _on_preset_change(self, name: str) -> None:
        preset = SQL_PRESETS.get(name, {})
        desc = preset.get("description", "")
        params = preset.get("params", [])
        hint = f"需要参数: {', '.join(params)}" if params else "无需参数"
        self._sql_desc_label.configure(text=f"{desc}（{hint}）")

    def _do_sql(self) -> None:
        preset_name = self._sql_preset.get()
        preset = SQL_PRESETS.get(preset_name)
        if not preset:
            return

        sql = preset["sql"]
        params_str = self._sql_params.get().strip()
        params = [p.strip() for p in params_str.split(",")] if params_str else []

        with self._db.connect() as conn:
            try:
                rows = conn.execute(sql, params).fetchall()
            except Exception as exc:
                messagebox.showerror("SQL 执行失败", str(exc))
                return

        # 清空旧数据
        for item in self._sql_tree.get_children():
            self._sql_tree.delete(item)

        if not rows:
            self._sql_count_label.configure(text="查询结果: 无数据")
            return

        # 动态列
        columns = tuple(rows[0].keys())
        self._sql_tree["columns"] = columns
        for col in columns:
            self._sql_tree.heading(col, text=col)
            self._sql_tree.column(col, width=max(80, min(200, len(col) * 12)), minwidth=50)

        for row in rows:
            values = [row[col] if row[col] is not None else "" for col in columns]
            self._sql_tree.insert("", "end", values=values)

        self._sql_count_label.configure(text=f"查询结果: {len(rows)} 条记录")

    # ================================================================
    # Tab 5: 报告导出
    # ================================================================

    def _build_report_tab(self, parent: ctk.CTkFrame) -> None:
        """构建报告导出标签页。"""
        settings_frame = ctk.CTkFrame(parent)
        settings_frame.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(settings_frame, text="报告设置", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=15, pady=(10, 5)
        )

        grid = ctk.CTkFrame(settings_frame, fg_color="transparent")
        grid.pack(fill="x", padx=15, pady=(0, 12))

        # 输出路径
        self._report_output = ctk.StringVar(value="rma_report.xlsx")
        ctk.CTkLabel(grid, text="输出文件:").grid(row=0, column=0, padx=(0, 5), pady=3, sticky="e")
        ctk.CTkEntry(grid, textvariable=self._report_output, width=300).grid(row=0, column=1, padx=(0, 5), pady=3)
        ctk.CTkButton(grid, text="浏览", width=80, command=self._browse_report_output).grid(row=0, column=2, pady=3)

        # 设备名过滤
        self._report_device = ctk.StringVar()
        ctk.CTkLabel(grid, text="设备名:").grid(row=1, column=0, padx=(0, 5), pady=3, sticky="e")
        ctk.CTkEntry(grid, textvariable=self._report_device, width=300).grid(row=1, column=1, padx=(0, 5), pady=3)

        # 固件版本过滤
        self._report_fw = ctk.StringVar()
        ctk.CTkLabel(grid, text="固件版本:").grid(row=2, column=0, padx=(0, 5), pady=3, sticky="e")
        ctk.CTkEntry(grid, textvariable=self._report_fw, width=300).grid(row=2, column=1, padx=(0, 5), pady=3)

        # 导出按钮
        ctk.CTkButton(grid, text="📊 生成报告", width=160, command=self._do_report).grid(
            row=3, column=1, pady=(10, 0)
        )

        # 信息区
        info_frame = ctk.CTkFrame(parent)
        info_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self._report_log = ctk.CTkTextbox(info_frame, font=ctk.CTkFont(family="Consolas", size=12))
        self._report_log.pack(fill="both", expand=True, padx=15, pady=15)

    def _browse_report_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="保存报告",
            defaultextension=".xlsx",
            filetypes=[("Excel 文件", "*.xlsx")],
            initialfile="rma_report.xlsx",
        )
        if path:
            self._report_output.set(path)

    def _do_report(self) -> None:
        from rma_report import RMAReportGenerator

        output = self._report_output.get().strip()
        if not output:
            messagebox.showwarning("提示", "请指定输出文件路径")
            return

        generator = RMAReportGenerator(self._db)
        try:
            result_path = generator.generate(
                output_path=output,
                device_name=self._report_device.get() or None,
                fw_version=self._report_fw.get() or None,
            )
            self._report_log.insert("end", f"✅ 报告已生成: {result_path}\n")
            self._report_log.see("end")
            messagebox.showinfo("成功", f"报告已生成:\n{result_path}")
        except Exception as exc:
            self._report_log.insert("end", f"❌ 生成失败: {exc}\n")
            messagebox.showerror("生成失败", str(exc))


def main() -> None:
    """启动 GUI 应用。"""
    app = App()
    app._update_status()
    app.mainloop()


if __name__ == "__main__":
    main()
