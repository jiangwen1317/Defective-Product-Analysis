"""
file_watcher 模块单元测试

覆盖纯逻辑部分：文件查找、日志发现、ZIP 解压和信号文件处理。
"""
import json
import os
import zipfile

from file_watcher import (
    FileWatcher,
    _extract_single_zip,
    _find_files,
    discover_log_files,
    extract_all_zips,
)


def _make_zip(zip_path: str, entries: dict[str, "str | bytes"]) -> None:
    """创建包含指定文件条目的 ZIP。"""
    with zipfile.ZipFile(zip_path, "w") as z:
        for name, content in entries.items():
            z.writestr(name, content)


# ================================================================
# 文件查找
# ================================================================

class TestFindFiles:
    """测试 _find_files 递归查找。"""

    def test_find_by_extension(self, tmp_path):
        (tmp_path / "a.txt").write_text("1")
        (tmp_path / "b.log").write_text("2")
        (tmp_path / "c.zip").write_text("3")

        result = _find_files(str(tmp_path), ".txt")
        assert len(result) == 1
        assert result[0].endswith("a.txt")

    def test_find_recursive(self, tmp_path):
        sub = tmp_path / "sub" / "deep"
        sub.mkdir(parents=True)
        (tmp_path / "a.txt").write_text("1")
        (sub / "b.txt").write_text("2")

        result = _find_files(str(tmp_path), ".txt")
        assert len(result) == 2

    def test_find_with_prefix(self, tmp_path):
        (tmp_path / "DM3720_a.txt").write_text("1")
        (tmp_path / "other.txt").write_text("2")

        result = _find_files(str(tmp_path), ".txt", prefix="DM3720")
        assert len(result) == 1
        assert os.path.basename(result[0]).startswith("DM3720")

    def test_find_empty_dir(self, tmp_path):
        assert _find_files(str(tmp_path), ".txt") == []


class TestDiscoverLogFiles:
    """测试 discover_log_files 多扩展名发现。"""

    def test_multiple_extensions(self, tmp_path):
        (tmp_path / "a.txt").write_text("1")
        (tmp_path / "b.log").write_text("2")
        (tmp_path / "c.zip").write_text("3")

        result = discover_log_files(str(tmp_path), [".txt", ".log"])
        assert len(result) == 2

    def test_empty_extensions(self, tmp_path):
        (tmp_path / "a.txt").write_text("1")
        assert discover_log_files(str(tmp_path), []) == []


# ================================================================
# ZIP 解压
# ================================================================

class TestExtractSingleZip:
    """测试单个 ZIP 解压。"""

    def test_extract_success_and_remove_zip(self, tmp_path):
        zip_path = str(tmp_path / "data.zip")
        _make_zip(zip_path, {"inner.txt": "hello"})

        success, name, error = _extract_single_zip(zip_path)
        assert success is True
        assert name == "data.zip"
        assert error is None
        # 解压出内容且原 ZIP 已删除
        assert (tmp_path / "inner.txt").read_text() == "hello"
        assert not os.path.exists(zip_path)

    def test_extract_nonexistent_path(self, tmp_path):
        success, name, error = _extract_single_zip(str(tmp_path / "no.zip"))
        assert success is False
        assert name == ""
        assert error is None

    def test_extract_corrupt_zip(self, tmp_path):
        bad_zip = tmp_path / "bad.zip"
        bad_zip.write_bytes(b"not a zip file")

        success, name, error = _extract_single_zip(str(bad_zip))
        assert success is False
        assert name == "bad.zip"
        assert error is not None


class TestExtractAllZips:
    """测试多轮迭代批量解压。"""

    def test_no_zip_returns_zero(self, tmp_path):
        (tmp_path / "a.txt").write_text("1")
        assert extract_all_zips(str(tmp_path)) == 0

    def test_extract_flat_zips(self, tmp_path):
        _make_zip(str(tmp_path / "z1.zip"), {"f1.txt": "1"})
        _make_zip(str(tmp_path / "z2.zip"), {"f2.txt": "2"})

        count = extract_all_zips(str(tmp_path))
        assert count == 2
        assert (tmp_path / "f1.txt").exists()
        assert (tmp_path / "f2.txt").exists()

    def test_extract_nested_zip(self, tmp_path):
        """ZIP 内嵌 ZIP 应在第二轮迭代中被解压。"""
        inner_zip = tmp_path / "inner.zip"
        _make_zip(str(inner_zip), {"deep.txt": "deep"})
        _make_zip(str(tmp_path / "outer.zip"), {"inner.zip": inner_zip.read_bytes()})
        inner_zip.unlink()

        count = extract_all_zips(str(tmp_path), max_iterations=2)
        assert count == 2
        assert (tmp_path / "deep.txt").exists()


# ================================================================
# FileWatcher 信号文件处理
# ================================================================

class TestFileWatcherSignal:
    """测试信号文件的处理与标记（不涉及真实解析）。"""

    def _make_watcher(self, tmp_path) -> FileWatcher:
        return FileWatcher(
            db_path=str(tmp_path / "watch.db"),
            signal_dir=str(tmp_path / "signals"),
            config={},
        )

    def test_mark_signal_done_renames(self, tmp_path):
        watcher = self._make_watcher(tmp_path)
        signal = tmp_path / "task.signal"
        signal.write_text("{}", encoding="utf-8")

        watcher._mark_signal_done(str(signal))
        assert not signal.exists()
        assert (tmp_path / "task.signal.done").exists()

    def test_mark_signal_done_overwrites_existing_done(self, tmp_path):
        watcher = self._make_watcher(tmp_path)
        signal = tmp_path / "task.signal"
        signal.write_text("new", encoding="utf-8")
        done = tmp_path / "task.signal.done"
        done.write_text("old", encoding="utf-8")

        watcher._mark_signal_done(str(signal))
        assert done.read_text(encoding="utf-8") == "new"

    def test_process_signal_invalid_json(self, tmp_path):
        """无效 JSON 信号文件应返回 0 且被标记为 done。"""
        watcher = self._make_watcher(tmp_path)
        signal = tmp_path / "bad.signal"
        signal.write_text("{invalid json", encoding="utf-8")

        assert watcher._process_signal(str(signal)) == 0
        assert (tmp_path / "bad.signal.done").exists()

    def test_process_signal_empty_payload(self, tmp_path):
        """无 files/dirs 字段的信号文件处理数为 0。"""
        watcher = self._make_watcher(tmp_path)
        signal = tmp_path / "empty.signal"
        signal.write_text(json.dumps({"action": "parse"}), encoding="utf-8")

        assert watcher._process_signal(str(signal)) == 0
        assert (tmp_path / "empty.signal.done").exists()

    def test_watch_once_no_signal(self, tmp_path):
        """无信号文件时 watch_once 返回 0 并创建信号目录。"""
        watcher = self._make_watcher(tmp_path)
        assert watcher.watch_once() == 0
        assert (tmp_path / "signals").is_dir()
