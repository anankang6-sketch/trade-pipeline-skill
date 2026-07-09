"""Tests for llm_parser 的降级路径（P0-3 修复的回归防线）。

三条路径的契约：
  1. API 错误（网络/超时/限流）→ 静默容灾回退规则模式，不打标记
  2. API 成功但响应畸形（非 JSON / 结构错）→ 回退规则模式 + _llm_degraded 标记
  3. API 成功且响应合法 → 正常返回，无标记
"""
import sys
import types

import pytest

from trade_pipeline.extractors.base import ContentBlock, ExtractedDocument
from trade_pipeline.understanding.llm_parser import _parse_with_llm


def _make_doc() -> ExtractedDocument:
    rows = [
        ["序号", "产品描述", "数量", "计量单位"],
        ["1", "HEX BOLT M8x25 DIN 933", "1000", "pcs"],
    ]
    text = "\n".join("\t".join(r) for r in rows)
    return ExtractedDocument(
        content_text=text,
        blocks=[ContentBlock(block_type="table", content=text, rows=rows)],
        meta={"filename": "t.xlsx", "format": "standard"},
        confidence=1.0,
        source_path="t.xlsx",
        extraction_method="openpyxl",
    )


class _FakeAPIError(Exception):
    pass


def _install_fake_anthropic(monkeypatch, create_fn):
    """注入假 anthropic 模块。create_fn 扮演 client.messages.create。"""
    fake = types.ModuleType("anthropic")
    fake.APIError = _FakeAPIError

    class _Messages:
        @staticmethod
        def create(**kwargs):
            return create_fn()

    class _Anthropic:
        def __init__(self, **kwargs):
            self.messages = _Messages()

    fake.Anthropic = _Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)


def _fake_response(text: str):
    block = types.SimpleNamespace(text=text)
    return types.SimpleNamespace(content=[block])


def test_api_error_falls_back_silently_without_degraded_flag(monkeypatch):
    """网络类错误 → 容灾回退，属正常降级路径，不打 _llm_degraded 标记。"""
    def _raise():
        raise _FakeAPIError("connection refused")

    _install_fake_anthropic(monkeypatch, _raise)
    rfq = _parse_with_llm(_make_doc())
    assert isinstance(rfq, dict)
    assert "_llm_degraded" not in rfq


def test_malformed_response_falls_back_with_degraded_flag(monkeypatch):
    """API 成功但返回非 JSON → 回退规则模式，必须带 _llm_degraded 标记。"""
    _install_fake_anthropic(
        monkeypatch, lambda: _fake_response("THIS IS NOT JSON AT ALL")
    )
    rfq = _parse_with_llm(_make_doc())
    assert isinstance(rfq, dict)
    assert rfq.get("_llm_degraded") is True
    assert "_llm_degraded_reason" in rfq


def test_non_dict_json_response_is_degraded(monkeypatch):
    """API 返回合法 JSON 但顶层不是 object（如数组）→ 同样降级打标。"""
    _install_fake_anthropic(monkeypatch, lambda: _fake_response('["not", "a", "dict"]'))
    rfq = _parse_with_llm(_make_doc())
    assert rfq.get("_llm_degraded") is True


def test_empty_content_is_degraded_not_crash(monkeypatch):
    """API 返回空 content 列表 → IndexError 应被捕获为降级，不裸崩。"""
    _install_fake_anthropic(
        monkeypatch, lambda: types.SimpleNamespace(content=[])
    )
    rfq = _parse_with_llm(_make_doc())
    assert rfq.get("_llm_degraded") is True


def test_valid_response_has_no_degraded_flag(monkeypatch):
    """正常路径：合法 JSON object → 原样返回，无降级标记。"""
    _install_fake_anthropic(
        monkeypatch,
        lambda: _fake_response('{"items": [], "currency": "USD"}'),
    )
    rfq = _parse_with_llm(_make_doc())
    assert rfq["currency"] == "USD"
    assert "_llm_degraded" not in rfq


def test_unexpected_exception_still_propagates(monkeypatch):
    """契约边界：非 API、非数据类的异常（如 KeyboardInterrupt 类程序性错误）
    不应被吞——这是与旧版 `except Exception` 的关键差异。"""
    def _raise():
        raise KeyboardInterrupt()

    _install_fake_anthropic(monkeypatch, _raise)
    with pytest.raises(KeyboardInterrupt):
        _parse_with_llm(_make_doc())
