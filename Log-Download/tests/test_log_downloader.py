"""log_downloader.py 中不依赖浏览器的纯逻辑函数单元测试。

覆盖范围（均为本地纯逻辑，不发起任何真实网络 / 浏览器请求）：
- 文件名清洗 (_sanitize_filename)
- 从文件名提取任务 ID (_extract_task_id_from_filename)
- 去重记录的读写 (save_downloaded_task / load_downloaded_tasks)
- 配置加载与校验 (_load_config / _validate_config)
- 唯一文件路径生成 (_get_unique_filepath)
- 待下载任务过滤 (filter_pending_tasks)

超出本次范围：登录、页面扫描、右键下载等浏览器端到端流程（依赖 Playwright
的实时页面交互），不在纯逻辑单元测试内验证。
"""

import json
import os

import pytest

from log_downloader import LogDownloader


def _make_config(download_dir: str) -> dict:
    """构造一份字段完整的合法配置字典。"""
    return {
        "lvts_server": {
            "url": "http://example.invalid/taskList",
            "username": "tester",
            "password": "secret",
        },
        "download": {"directory": download_dir},
    }


@pytest.fixture
def downloader(tmp_path):
    """构造一个指向临时目录的下载器实例。

    - 配置文件、下载目录、去重记录文件均落在临时目录，避免污染真实文件。
    - 不初始化浏览器，仅用于测试纯逻辑方法。
    """
    download_dir = tmp_path / "downloads"
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(_make_config(str(download_dir)), ensure_ascii=False),
        encoding="utf-8",
    )

    dl = LogDownloader(str(config_path))
    # 覆盖记录文件路径，避免写入脚本目录下的真实 downloaded_tasks.txt
    dl.record_file = str(tmp_path / "downloaded_tasks.txt")
    return dl


class TestSanitizeFilename:
    """文件名清洗测试。"""

    def test_plain_name_unchanged(self, downloader):
        """无非法字符的普通文件名应原样返回。"""
        assert downloader._sanitize_filename("normal_file-1.txt") == "normal_file-1.txt"

    @pytest.mark.parametrize("char", list('<>:"/\\|?*'))
    def test_illegal_chars_replaced_with_underscore(self, downloader, char):
        """Windows 非法字符应逐个被替换为下划线。"""
        assert downloader._sanitize_filename(f"a{char}b") == "a_b"

    def test_control_chars_removed(self, downloader):
        """控制字符（含 NUL、DEL）应被移除而非替换。"""
        assert downloader._sanitize_filename("a\x00b\x1fc\x7fd") == "abcd"

    def test_length_truncated_to_200(self, downloader):
        """超过 200 字符的文件名应被截断到 200。"""
        result = downloader._sanitize_filename("x" * 250)
        assert len(result) == 200

    def test_boundary_length_200_preserved(self, downloader):
        """恰好 200 字符时不应被截断。"""
        result = downloader._sanitize_filename("y" * 200)
        assert len(result) == 200

    def test_empty_string(self, downloader):
        """空字符串应返回空字符串。"""
        assert downloader._sanitize_filename("") == ""


class TestExtractTaskIdFromFilename:
    """从文件名提取任务 ID 测试。"""

    def test_numeric_id_with_timestamp(self, downloader):
        """标准格式 {id}_{YYYYMMDD}_{HHMMSS}.ext 应提取数字 ID。"""
        assert (
            downloader._extract_task_id_from_filename("316235_20260729_101530.log")
            == "316235"
        )

    def test_task_row_id_with_timestamp(self, downloader):
        """含下划线的 task_row_N 前缀应被完整提取（非贪婪到时间戳前）。"""
        assert (
            downloader._extract_task_id_from_filename("task_row_5_20260729_101530.txt")
            == "task_row_5"
        )

    def test_task_row_fallback_without_timestamp(self, downloader):
        """无标准时间戳但符合 task_row_N_ 的文件名走备用匹配。"""
        assert (
            downloader._extract_task_id_from_filename("task_row_12_extra.txt")
            == "task_row_12"
        )

    def test_numeric_fallback_without_timestamp(self, downloader):
        """无标准时间戳但以数字_开头的文件名走数字备用匹配。"""
        assert downloader._extract_task_id_from_filename("998_something.txt") == "998"

    def test_unrecognized_returns_none(self, downloader):
        """无法识别的文件名应返回 None。"""
        assert downloader._extract_task_id_from_filename("readme.md") is None

    def test_empty_returns_none(self, downloader):
        """空文件名应返回 None。"""
        assert downloader._extract_task_id_from_filename("") is None


class TestDownloadedTaskRecord:
    """去重记录读写测试。"""

    def test_save_then_load_roundtrip(self, downloader):
        """写入的任务 ID 应能被重新加载出来。"""
        downloader.save_downloaded_task("316235")
        downloader.save_downloaded_task("316403")

        assert {"316235", "316403"}.issubset(downloader.load_downloaded_tasks())

    def test_load_empty_when_no_record_file(self, downloader):
        """记录文件不存在且下载目录为空时应返回空集合。"""
        assert downloader.load_downloaded_tasks() == set()

    def test_load_ignores_blank_lines(self, downloader):
        """记录文件中的空行应被忽略。"""
        with open(downloader.record_file, "w", encoding="utf-8") as f:
            f.write("316235\n\n   \n316403\n")

        assert downloader.load_downloaded_tasks() == {"316235", "316403"}

    def test_load_merges_directory_scan(self, downloader):
        """下载目录中已存在文件的任务 ID 也应被纳入去重集合。"""
        # 记录文件写入一个 ID
        downloader.save_downloaded_task("111")
        # 下载目录放入另一个符合命名规则的文件
        log_path = f"{downloader.download_dir}/222_20260729_101530.log"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("data")

        assert {"111", "222"}.issubset(downloader.load_downloaded_tasks())


class TestConfigValidation:
    """配置加载与校验测试。"""

    def test_missing_file_raises(self, tmp_path):
        """配置文件不存在应抛出 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            LogDownloader(str(tmp_path / "does_not_exist.json"))

    def test_invalid_json_raises_value_error(self, tmp_path):
        """配置文件 JSON 格式错误应抛出 ValueError。"""
        bad = tmp_path / "config.json"
        bad.write_text("{ not valid json ", encoding="utf-8")

        with pytest.raises(ValueError):
            LogDownloader(str(bad))

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda c: c["lvts_server"].pop("url"),
            lambda c: c["lvts_server"].pop("username"),
            lambda c: c["lvts_server"].pop("password"),
            lambda c: c["download"].pop("directory"),
        ],
    )
    def test_missing_required_field_raises(self, tmp_path, mutate):
        """缺少任一必需字段应抛出 ValueError。"""
        cfg = _make_config(str(tmp_path / "downloads"))
        mutate(cfg)
        path = tmp_path / "config.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")

        with pytest.raises(ValueError):
            LogDownloader(str(path))

    def test_validate_reports_all_missing_fields(self, downloader):
        """校验空配置时错误信息应列出全部缺失字段。"""
        with pytest.raises(ValueError) as exc_info:
            downloader._validate_config({})

        message = str(exc_info.value)
        for field in (
            "lvts_server.url",
            "lvts_server.username",
            "lvts_server.password",
            "download.directory",
        ):
            assert field in message


class TestUniqueFilepath:
    """唯一文件路径生成测试。"""

    def test_returns_original_when_not_exists(self, downloader):
        """目标文件不存在时应返回原始路径。"""
        expected = os.path.join(downloader.download_dir, "report.log")
        assert downloader._get_unique_filepath("report.log") == expected

    def test_appends_counter_on_conflict(self, downloader):
        """目标文件已存在时应追加计数后缀避免覆盖。"""
        with open(f"{downloader.download_dir}/report.log", "w", encoding="utf-8") as f:
            f.write("existing")

        result = downloader._get_unique_filepath("report.log")
        assert result.replace("\\", "/").endswith("report_1.log")


class TestFilterPendingTasks:
    """待下载任务过滤测试。"""

    def test_filters_out_downloaded(self, downloader):
        """已记录的任务应被排除，仅保留待下载任务。"""
        downloader.save_downloaded_task("111")
        tasks = [
            {"id": "111", "name": "a"},
            {"id": "222", "name": "b"},
            {"id": "333", "name": "c"},
        ]

        pending = downloader.filter_pending_tasks(tasks)

        assert [t["id"] for t in pending] == ["222", "333"]

    def test_empty_input_returns_empty(self, downloader):
        """空任务列表应返回空列表。"""
        assert downloader.filter_pending_tasks([]) == []
