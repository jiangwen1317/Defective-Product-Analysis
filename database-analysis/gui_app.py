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

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

# 将脚本目录加入 Python 路径
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from config import load_config, get_db_path, get_file_extensions, PROJECT_DIR
from database import DatabaseConnection, MetricsRepository
from parse_service import ParseService
from schema import init_database

logger = logging.getLogger(__name__)

# 主题配置
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    """主应用窗口。"""

    def __init__(self) -> None:
        super().__init__()

        self.title("EMMC 测试日志分析系统")
        self.geometry("1280x720")
        self.minsize(900, 600)

        # 数据库初始化
        self._db_path = get_db_path()
        self._db = DatabaseConnection(self._db_path)
        self._repo = MetricsRepository(self._db)
        self._parse_service = ParseService(self._db, self._repo)
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
        self._build_wear_tab(self._tabview.add("📈 图表绘制"))
        self._build_compare_tab(self._tabview.add("⚖️ 指标对比"))
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
        """向日志区追加消息（线程安全）。

        通过 self.after 将 UI 操作调度回主线程，
        避免后台线程直接访问 Tkinter 控件。
        """
        ts = datetime.now().strftime("%H:%M:%S")
        self.after(0, self._append_parse_log, f"[{ts}] {msg}")

    def _append_parse_log(self, text: str) -> None:
        """在主线程中向日志区追加文本（仅由 _log_parse 调用）。"""
        self._parse_log.insert("end", text + "\n")
        self._parse_log.see("end")

    def _parse_single(self) -> None:
        file_path = self._parse_file_var.get().strip()
        if not file_path or not os.path.exists(file_path):
            messagebox.showwarning("提示", "请先选择有效的日志文件")
            return

        def _run() -> None:
            self._parse_service.process_files([file_path], on_log=self._log_parse)
            self._update_status()

        threading.Thread(target=_run, daemon=True).start()

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
            extensions = get_file_extensions()
            files = discover_log_files(directory, extensions)
            self._log_parse(f"发现 {len(files)} 个日志文件")
            # 解析
            self._parse_service.process_files(files, on_log=self._log_parse)
            self._update_status()

        threading.Thread(target=_run, daemon=True).start()

    def _clear_database(self) -> None:
        if not messagebox.askyesno("确认", "确定要清空数据库中所有数据吗？此操作不可撤销！"):
            return
        with self._db.connect() as conn:
            # 清理可能残留的迁移临时表
            conn.execute("DROP TABLE IF EXISTS _test_summary_old")
            # 删除主表，子表通过 ON DELETE CASCADE 自动级联删除
            conn.execute("DELETE FROM test_summary")
        self._log_parse("数据库已清空")
        self._update_status()

    def _update_status(self) -> None:
        """更新状态栏中的记录数（线程安全）。

        通过 self.after 将 UI 操作调度回主线程。
        """
        try:
            with self._db.connect() as conn:
                count = conn.execute("SELECT COUNT(*) FROM test_summary").fetchone()[0]
            self.after(
                0,
                lambda: self._status_label.configure(
                    text=f"  数据库: {os.path.basename(self._db_path)}  |  已导入: {count} 条记录"
                ),
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

        # 行 3
        self._q_flash_id = ctk.StringVar()
        self._q_capacity = ctk.StringVar()
        self._q_controller = ctk.StringVar()

        ctk.CTkLabel(grid, text="Flash ID:").grid(row=2, column=0, padx=(0, 5), pady=3, sticky="e")
        ctk.CTkEntry(grid, textvariable=self._q_flash_id, width=180,
                     placeholder_text="0x454335...").grid(row=2, column=1, padx=(0, 15), pady=3)

        ctk.CTkLabel(grid, text="容量:").grid(row=2, column=2, padx=(0, 5), pady=3, sticky="e")
        ctk.CTkEntry(grid, textvariable=self._q_capacity, width=180,
                     placeholder_text="MB 或 扇区数").grid(row=2, column=3, padx=(0, 15), pady=3)

        ctk.CTkLabel(grid, text="主控:").grid(row=2, column=4, padx=(0, 5), pady=3, sticky="e")
        ctk.CTkEntry(grid, textvariable=self._q_controller, width=100).grid(row=2, column=5, padx=(0, 5), pady=3, sticky="w")

        ctk.CTkButton(grid, text="🔍 查询", width=100, command=self._do_query).grid(row=2, column=6, pady=3, padx=(10, 0))

        # 结果表格
        result_frame = ctk.CTkFrame(parent)
        result_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        # 标题行 + 删除按钮
        header_bar = ctk.CTkFrame(result_frame, fg_color="transparent")
        header_bar.pack(fill="x", padx=15, pady=(10, 5))

        self._query_count_label = ctk.CTkLabel(header_bar, text="查询结果", font=ctk.CTkFont(size=14, weight="bold"))
        self._query_count_label.pack(side="left")

        ctk.CTkButton(
            header_bar, text="🗑️ 删除整条记录", width=140,
            fg_color="darkred", hover_color="red",
            command=self._delete_selected,
        ).pack(side="right")

        # Treeview
        tree_frame = ctk.CTkFrame(result_frame, fg_color="transparent")
        tree_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        columns = ("id", "device", "fw_version", "flash_id", "capacity", "section", "key", "value", "num_value", "result")
        self._query_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=20, selectmode="extended")

        headers = {
            "id": ("ID", 50), "device": ("设备名", 130), "fw_version": ("固件版本", 180),
            "flash_id": ("Flash ID", 160), "capacity": ("容量", 90),
            "section": ("Section", 160), "key": ("指标名", 140), "value": ("原始值", 120),
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
        repo = self._repo

        # 解析容量值（支持 MB 和扇区数两种格式）
        capacity_mb = None
        capacity_sectors = None
        cap_str = self._q_capacity.get().strip()
        if cap_str:
            try:
                cap_val = int(cap_str)
                # 扇区数通常 > 1000000，MB 值通常 < 1000000
                if cap_val > 1_000_000:
                    capacity_sectors = cap_val
                else:
                    capacity_mb = cap_val
            except ValueError:
                pass

        with self._db.connect() as conn:
            summaries = repo.get_summaries(
                conn,
                device_name=self._q_device.get() or None,
                fw_version=self._q_fw.get() or None,
                flash_id=self._q_flash_id.get() or None,
                overall_result=self._q_result.get() or None,
                capacity_mb=capacity_mb,
                capacity_sectors=capacity_sectors,
                controller=self._q_controller.get() or None,
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
            # 批量查询所有 summary 的 metrics（解决 N+1 问题）
            summary_ids = [s["id"] for s in summaries]
            all_metrics = repo.get_metrics_by_summary_ids(
                conn, summary_ids,
                section=section_filter, metric_key=key_filter,
            )

            # 构建 summary_id → summary 的映射
            summary_map = {s["id"]: s for s in summaries}

            for m in all_metrics:
                s = summary_map.get(m["summary_id"])
                if s is None:
                    continue

                # 容量显示：优先 MB，其次扇区
                cap_display = ""
                if s.get("capacity_mb"):
                    cap_display = f"{s['capacity_mb']} MB"
                elif s.get("capacity_sectors"):
                    cap_display = f"{s['capacity_sectors']} Sec"

                self._query_tree.insert("", "end", values=(
                    s["id"],
                    s.get("device_name", ""),
                    s.get("fw_version", ""),
                    s.get("flash_id", ""),
                    cap_display,
                    m["section"],
                    m["metric_key_raw"],
                    m["raw_value"],
                    m.get("num_value", "") or "",
                    s.get("overall_result", ""),
                ))
                row_count += 1

        self._query_count_label.configure(text=f"查询结果: {row_count} 条指标（来自 {len(summaries)} 条记录）")

    def _delete_selected(self) -> None:
        """删除查询结果中选中的整条记录。

        选中任意指标行即可定位其所属的 summary 记录，
        删除该记录及其全部关联指标（ON DELETE CASCADE）。
        """
        selected_items = self._query_tree.selection()
        if not selected_items:
            messagebox.showwarning("提示", "请先在查询结果中选择要删除的行\n（选中任意一行即可定位所属记录）")
            return

        # 从选中行提取唯一的 summary ID
        summary_ids: set[int] = set()
        for item in selected_items:
            values = self._query_tree.item(item, "values")
            if values:
                try:
                    summary_ids.add(int(values[0]))
                except (ValueError, IndexError):
                    pass

        if not summary_ids:
            messagebox.showwarning("提示", "未找到有效的记录 ID")
            return

        id_list = sorted(summary_ids)
        id_display = ", ".join(str(i) for i in id_list[:10])
        if len(id_list) > 10:
            id_display += "..."

        if not messagebox.askyesno(
            "确认删除整条记录",
            f"即将删除 {len(id_list)} 条设备记录及其全部指标数据\n\n"
            f"记录 ID: {id_display}\n"
            f"选中了 {len(selected_items)} 行指标，涉及 {len(id_list)} 条记录\n\n"
            f"⚠️ 每条记录包含数百条指标，删除后不可恢复！\n"
            f"确认要继续吗？",
        ):
            return

        repo = self._repo
        with self._db.connect() as conn:
            deleted = repo.delete_summaries_by_ids(conn, id_list)

        messagebox.showinfo("完成", f"已删除 {deleted} 条记录及其全部关联指标")

        # 从表格中移除已删除的行
        for item in selected_items:
            self._query_tree.delete(item)

        self._update_status()

    # ================================================================
    # Tab: 通用图表绘制
    # ================================================================

    _CHART_COLORS = [
        '#2ecc71', '#3498db', '#e74c3c', '#f39c12', '#9b59b6',
        '#1abc9c', '#e67e22', '#2980b9', '#c0392b', '#27ae60',
    ]
    _CHART_TYPES = ["自动", "折线图", "柱状图", "散点图", "阶梯图", "面积图"]

    def _build_wear_tab(self, parent: ctk.CTkFrame) -> None:
        """构建通用图表绘制标签页。"""
        # 输入区
        input_frame = ctk.CTkFrame(parent)
        input_frame.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(input_frame, text="通用指标图表绘制",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=15, pady=(10, 5))

        # 单行控制
        ctrl = ctk.CTkFrame(input_frame, fg_color="transparent")
        ctrl.pack(fill="x", padx=15, pady=(0, 5))

        ctk.CTkLabel(ctrl, text="记录 ID:").pack(side="left", padx=(0, 5))
        self._wear_id = ctk.StringVar()
        ctk.CTkEntry(ctrl, textvariable=self._wear_id, width=140,
                     placeholder_text="8 或 8,9,10").pack(side="left", padx=(0, 12))

        ctk.CTkLabel(ctrl, text="指标名:").pack(side="left", padx=(0, 5))
        self._chart_metric_key = ctk.StringVar(value="dwBlockPECycle")
        ctk.CTkEntry(ctrl, textvariable=self._chart_metric_key, width=200,
                     placeholder_text="输入指标关键字").pack(side="left", padx=(0, 12))

        ctk.CTkLabel(ctrl, text="图表:").pack(side="left", padx=(0, 5))
        self._chart_type = ctk.StringVar(value="自动")
        ctk.CTkComboBox(ctrl, variable=self._chart_type,
                        values=self._CHART_TYPES, width=90).pack(side="left", padx=(0, 12))

        ctk.CTkButton(ctrl, text="📈 绘制", width=90, command=self._draw_chart).pack(side="left", padx=(0, 8))
        ctk.CTkButton(ctrl, text="🗑️ 清除", width=70, command=self._clear_chart).pack(side="left")

        self._chart_info_label = ctk.CTkLabel(
            input_frame,
            text="提示: 输入记录 ID 和指标名，点击绘制。支持索引序列(dwBlockPECycle[N])和标量值(WAI)两种数据模式",
            font=ctk.CTkFont(size=12), text_color="gray")
        self._chart_info_label.pack(anchor="w", padx=15, pady=(0, 10))

        # 图表区
        chart_frame = ctk.CTkFrame(parent)
        chart_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self._chart_fig = Figure(figsize=(10, 5), dpi=100)
        self._chart_ax = self._chart_fig.add_subplot(111)
        self._chart_ax.set_xlabel("Index")
        self._chart_ax.set_ylabel("Value")
        self._chart_ax.set_title("Metric Chart")
        self._chart_ax.grid(True, alpha=0.3)

        self._chart_canvas = FigureCanvasTkAgg(self._chart_fig, master=chart_frame)
        self._chart_canvas.get_tk_widget().pack(fill="both", expand=True, padx=5, pady=5)

        toolbar_frame = ctk.CTkFrame(chart_frame, height=40, fg_color="transparent")
        toolbar_frame.pack(fill="x", padx=5, pady=(0, 5))
        self._chart_toolbar = NavigationToolbar2Tk(self._chart_canvas, toolbar_frame)
        self._chart_toolbar.update()

    def _parse_ids(self, raw: str) -> list[int]:
        """解析逗号分隔的 ID 字符串。"""
        ids: list[int] = []
        for part in raw.replace("，", ",").split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
        return ids

    @staticmethod
    def _resolve_draw_mode(chart_type: str, has_indexed: bool, multi: bool) -> str:
        """确定实际绘图模式。"""
        if chart_type == "自动":
            if has_indexed and multi:
                return "line"
            return "bar"
        type_map = {
            "折线图": "line", "柱状图": "bar", "散点图": "scatter",
            "阶梯图": "step", "面积图": "area",
        }
        return type_map.get(chart_type, "line")

    def _plot_indexed_series(self, ax, xs, ys, color, label, draw_mode, max_v, avg_v, multi, idx, total_recs):
        """绘制单条索引序列数据。"""
        if draw_mode == "line":
            ax.plot(xs, ys, color=color, linewidth=1.2, alpha=0.85, label=label)
            if avg_v > 0:
                ax.axhline(y=avg_v, color=color, linestyle='--', linewidth=1, alpha=0.5)
        elif draw_mode == "step":
            ax.step(xs, ys, color=color, linewidth=1.2, alpha=0.85, where='post', label=label)
            if avg_v > 0:
                ax.axhline(y=avg_v, color=color, linestyle='--', linewidth=1, alpha=0.5)
        elif draw_mode == "area":
            ax.fill_between(xs, ys, alpha=0.3, color=color, label=label)
            ax.plot(xs, ys, color=color, linewidth=1, alpha=0.8)
        elif draw_mode == "scatter":
            ax.scatter(xs, ys, color=color, s=12, alpha=0.7, label=label)
        else:  # bar
            bar_colors = ['#e74c3c' if v == max_v and v > 0 else
                          color if v > 0 else '#bdc3c7' for v in ys]
            width = 0.8 if not multi else max(0.1, 0.8 / total_recs)
            offset = idx * width if multi else 0
            ax.bar([x + offset for x in xs], ys, color=bar_colors,
                   width=width, alpha=0.85, label=label)
            if avg_v > 0 and not multi:
                ax.axhline(y=avg_v, color='#f39c12', linestyle='--',
                          linewidth=1.5, label=f'Avg: {avg_v:.2f}')

    def _draw_chart(self) -> None:
        """通用图表绘制，支持索引序列和标量两种数据模式， 6 种图表类型。"""
        ids = self._parse_ids(self._wear_id.get().strip())
        metric_key = self._chart_metric_key.get().strip()
        chart_type = self._chart_type.get()

        if not ids:
            messagebox.showwarning("提示", "请输入记录 ID")
            return
        if not metric_key:
            messagebox.showwarning("提示", "请输入指标名")
            return

        repo = self._repo

        # 收集数据
        records: list[dict] = []
        with self._db.connect() as conn:
            all_summaries = {s["id"]: s for s in repo.get_summaries(conn, limit=500)}

            for sid in ids:
                summary = all_summaries.get(sid)
                if summary is None:
                    continue
                metrics = repo.get_metrics(conn, summary_id=sid, metric_key=metric_key)

                indexed: list[tuple[int, float]] = []
                scalar_val: float | None = None

                for m in metrics:
                    nv = m.get("num_value")
                    if nv is None:
                        continue
                    if m.get("array_index") is not None:
                        try:
                            idx = int(m["array_index"])
                            indexed.append((idx, float(nv)))
                        except (ValueError, TypeError):
                            pass
                    elif scalar_val is None:
                        scalar_val = float(nv)

                if indexed:
                    indexed.sort(key=lambda x: x[0])
                    records.append({"summary": summary, "mode": "indexed", "data": indexed})
                elif scalar_val is not None:
                    records.append({"summary": summary, "mode": "scalar", "data": scalar_val})

        if not records:
            messagebox.showinfo("提示", f"未找到指标 '{metric_key}' 的有效数据")
            return

        has_indexed = any(r["mode"] == "indexed" for r in records)
        multi = len(records) > 1
        draw_mode = self._resolve_draw_mode(chart_type, has_indexed, multi)

        # 绘制
        self._chart_ax.clear()
        self._chart_ax.grid(True, alpha=0.3)
        info_parts: list[str] = []

        if has_indexed:
            # === 索引序列模式 ===
            self._chart_ax.set_xlabel("Index", fontsize=11)
            self._chart_ax.set_ylabel(metric_key, fontsize=11)
            indexed_recs = [r for r in records if r["mode"] == "indexed"]

            for i, rec in enumerate(indexed_recs):
                s = rec["summary"]
                data = rec["data"]
                xs = [d[0] for d in data]
                ys = [d[1] for d in data]
                color = self._CHART_COLORS[i % len(self._CHART_COLORS)]

                dev = s.get("device_name", "") or ""
                fw = (s.get("fw_version", "") or "")[:20]
                label = f"ID={s['id']} {dev} ({fw})"

                total = len(ys)
                max_v = max(ys)
                min_v = min(ys)
                avg_v = sum(ys) / total
                non_zero = sum(1 for v in ys if v > 0)

                self._plot_indexed_series(
                    self._chart_ax, xs, ys, color, label, draw_mode,
                    max_v, avg_v, multi, i, len(indexed_recs))

                info_parts.append(
                    f"[{s['id']}] {dev}  n={total} 非零={non_zero}  "
                    f"Max={max_v:.4g} Min={min_v:.4g} Avg={avg_v:.4g}"
                )

            title_suffix = f"({len(records)} records)" if multi else \
                f"— {records[0]['summary'].get('device_name', '')}"
            self._chart_ax.set_title(f"{metric_key} {title_suffix}", fontsize=12)

        else:
            # === 标量对比模式 ===
            self._chart_ax.set_xlabel("Record", fontsize=11)
            self._chart_ax.set_ylabel(metric_key, fontsize=11)

            labels: list[str] = []
            values: list[float] = []
            colors: list[str] = []

            for i, rec in enumerate(records):
                s = rec["summary"]
                dev = s.get("device_name", "") or ""
                labels.append(f"ID={s['id']}\n{dev}")
                values.append(rec["data"])
                colors.append(self._CHART_COLORS[i % len(self._CHART_COLORS)])
                info_parts.append(f"[{s['id']}] {dev}  {metric_key}={rec['data']:.4g}")

            x_pos = list(range(len(values)))
            if draw_mode == "scatter":
                self._chart_ax.scatter(x_pos, values, color=colors, s=80, zorder=3)
            elif draw_mode in ("line", "step"):
                style = 'steps-mid' if draw_mode == "step" else 'default'
                self._chart_ax.plot(x_pos, values, color=self._CHART_COLORS[0],
                                    marker='o', linewidth=1.5, markersize=8,
                                    drawstyle=style)
            elif draw_mode == "area":
                self._chart_ax.bar(x_pos, values, color=colors, alpha=0.5, width=0.6)
                self._chart_ax.plot(x_pos, values, color=self._CHART_COLORS[0],
                                    marker='o', linewidth=1.5, markersize=6)
            else:  # bar
                self._chart_ax.bar(x_pos, values, color=colors, alpha=0.85, width=0.6)

            self._chart_ax.set_xticks(x_pos)
            self._chart_ax.set_xticklabels(labels, fontsize=9)
            self._chart_ax.set_title(f"{metric_key} Comparison", fontsize=12)

        self._chart_ax.legend(loc='best', fontsize=9, framealpha=0.8)
        self._chart_fig.tight_layout()
        self._chart_canvas.draw()
        self._chart_info_label.configure(text="\n".join(info_parts))

    def _clear_chart(self) -> None:
        """清除图表。"""
        self._chart_ax.clear()
        self._chart_ax.set_xlabel("Index")
        self._chart_ax.set_ylabel("Value")
        self._chart_ax.set_title("Metric Chart")
        self._chart_ax.grid(True, alpha=0.3)
        self._chart_fig.tight_layout()
        self._chart_canvas.draw()
        self._chart_info_label.configure(
            text="提示: 输入记录 ID 和指标名，点击绘制。支持索引序列和标量值两种数据模式")

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
    # Tab 4: 报告导出
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
    try:
        app.mainloop()
    except KeyboardInterrupt:
        # Ctrl+C 时优雅退出，避免 Tkinter 回调中的 traceback
        app.destroy()


if __name__ == "__main__":
    main()
