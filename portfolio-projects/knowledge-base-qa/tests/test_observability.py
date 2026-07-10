"""observability 单测：结构化日志 / trace_id 贯穿 / 脱敏 / 配置开关（LLMOps L01）。

全程不打真实 API：只验证日志格式化与上下文行为。
"""
from __future__ import annotations

import json
import logging

from kb_qa import observability as obs
from kb_qa.config import settings


def test_mask_secret_keeps_tail_only():
    """脱敏：只露尾部 4 位，主体用 *** 覆盖。"""
    assert obs.mask_secret("sk-abcd1234efgh5678") == "***5678"
    # 太短的不露明文
    assert obs.mask_secret("ab") == "***"
    assert obs.mask_secret("") == ""
    assert obs.mask_secret(None) == ""  # type: ignore[arg-type]


def test_trace_id_isolation_between_contexts():
    """不同 set_trace_id 后，get_trace_id 返回各自设置的值（上下文隔离基础）。"""
    obs.set_trace_id("aaaa1111")
    assert obs.get_trace_id() == "aaaa1111"
    obs.set_trace_id("bbbb2222")
    assert obs.get_trace_id() == "bbbb2222"


def test_new_trace_id_is_unique_short():
    """trace_id 是 8 位 hex 且大量生成不撞。"""
    ids = {obs.new_trace_id() for _ in range(500)}
    assert len(ids) == 500          # 全唯一
    assert all(len(i) == 8 for i in ids)


def test_json_formatter_emits_event_and_trace_id():
    """JSON 格式器：输出是合法 JSON，含 event/trace_id/level 字段。"""
    # 直接用 formatter 格式化一条手构的 record，绕开全局 handler 状态
    fmt = obs.JsonFormatter()
    obs.set_trace_id("deadbeef")
    record = logging.LogRecord(
        name="kb_qa.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="retrieve.done", args=None, exc_info=None,
    )
    record.event = "retrieve.done"
    record.hits = 8
    record.duration_ms = 320
    line = fmt.format(record)
    data = json.loads(line)
    assert data["event"] == "retrieve.done"
    assert data["trace_id"] == "deadbeef"
    assert data["level"] == "INFO"
    assert data["hits"] == 8
    assert data["duration_ms"] == 320


def test_log_event_writes_structured_fields(caplog):
    """log_event 把 kwargs 作为结构化字段写入（用 caplog 捕获）。"""
    logger = logging.getLogger("kb_qa.test.caplog")
    # setup_logging 会清根 handler；caplog 用 propagate 机制仍能捕获
    logger.propagate = True
    obs.set_trace_id("cafef00d")
    with caplog.at_level(logging.INFO, logger="kb_qa.test.caplog"):
        obs.log_event(logger, "retrieve.done", hits=3, mode="hybrid")
    rec = caplog.records[-1]
    assert rec.event == "retrieve.done"
    assert rec.hits == 3
    assert rec.mode == "hybrid"


def test_estimate_tokens_chinese_and_ascii():
    """token 估算：中文按字、英文按 4 字符 1 token。"""
    assert obs.estimate_tokens("") == 0
    # 3 个中文字 = 3 token
    assert obs.estimate_tokens("云帆科技") == 4
    # 8 个 ASCII ≈ 2 token
    assert obs.estimate_tokens("abcdefgh") == 2


def test_settings_has_log_fields():
    """config 暴露了 log_json / log_level（落地验证配置集中）。"""
    assert hasattr(settings, "log_json")
    assert hasattr(settings, "log_level")
    assert isinstance(settings.log_json, bool)
