"""Tests for excel_extractor read-size guards (T6)."""
import tempfile
from pathlib import Path

import pytest
from openpyxl import Workbook

from trade_pipeline.extractors import excel_extractor
from trade_pipeline.extractors.excel_extractor import (
    FileTooLargeError,
    MAX_FILE_SIZE_BYTES,
    MAX_ROWS,
    extract,
)


def _make_xlsx(rows: int) -> str:
    """Create a temp xlsx with `rows` data rows (plus a header row)."""
    wb = Workbook()
    ws = wb.active
    ws.append(["COMMODITY DESCRIPTION", "Barcode", "PCS"])
    for i in range(rows):
        ws.append([f"HEX BOLT M8x{i}", f"BC-{i}", 1000])
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    wb.save(path)
    return path


def test_extract_rejects_oversized_file(monkeypatch):
    """超过 20MB 上限的文件应抛 FileTooLargeError（用低阈值模拟，避免造大文件）。"""
    path = _make_xlsx(3)
    try:
        # 把上限临时压到 100 字节，任何真实 xlsx 都会超
        monkeypatch.setattr(excel_extractor, "MAX_FILE_SIZE_BYTES", 100)
        with pytest.raises(FileTooLargeError) as exc:
            extract(path)
        assert "过大" in str(exc.value)
    finally:
        Path(path).unlink(missing_ok=True)


def test_extract_rejects_too_many_rows(monkeypatch):
    """超过行数上限应抛 FileTooLargeError。"""
    path = _make_xlsx(30)
    try:
        monkeypatch.setattr(excel_extractor, "MAX_ROWS", 10)
        with pytest.raises(FileTooLargeError) as exc:
            extract(path)
        assert "行数过多" in str(exc.value)
    finally:
        Path(path).unlink(missing_ok=True)


def test_extract_accepts_normal_file():
    """正常小文件（远低于上限）应成功提取。"""
    path = _make_xlsx(5)
    try:
        doc = extract(path)
        assert doc.meta["rows"] <= MAX_ROWS
        assert Path(path).stat().st_size < MAX_FILE_SIZE_BYTES
        assert "HEX BOLT" in doc.content_text
    finally:
        Path(path).unlink(missing_ok=True)
