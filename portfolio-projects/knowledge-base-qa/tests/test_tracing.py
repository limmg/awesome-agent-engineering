"""tracing 单测：trace/span/generation 树 + 成本核算 + 降级（LLMOps L02）。

全程不打真实 API，也不依赖 langfuse 包（验证的是降级 ConsoleTracer 路径）。
"""
from __future__ import annotations

from kb_qa import tracing
from kb_qa.tracing import (
    _ConsoleBackend,
    compute_cost,
    init_tracing,
    is_langfuse_active,
    start_trace,
    trace_generation,
    trace_span,
)


def test_compute_cost_glm4_and_flash():
    """glm-4 按 50 元/百万 token 算；flash 免费。"""
    cost = compute_cost("glm-4", {"input": 820, "output": 210})
    # (820+210) * 50 / 1e6 = 0.0515
    assert cost == 0.0515
    # flash 免费
    assert compute_cost("glm-4-flash", {"input": 1000, "output": 1000}) == 0.0


def test_compute_cost_unknown_model_zero():
    """未知模型不计费（防御：不崩，返回 0）。"""
    assert compute_cost("unknown-model", {"input": 999, "output": 999}) == 0.0


def test_init_tracing_defaults_to_console():
    """未配置 langfuse 时降级到 ConsoleTracer（不依赖外部包）。"""
    # 重置单例，强制重新探测
    tracing._backend = None
    init_tracing()
    assert not is_langfuse_active()
    assert isinstance(tracing._backend, _ConsoleBackend)


def test_span_nesting_tree_structure():
    """trace_span 内再开 trace_span → 自动成父子（树形）。"""
    backend = _ConsoleBackend()
    with backend.trace("root") as t:
        with backend.span("parent") as p:
            with backend.span("child") as c:
                c.output = "ok"
    # parent 是根 span，child 挂在 parent 下
    assert len(t.spans) == 1
    parent = t.spans[0]
    assert parent.name == "parent"
    assert len(parent.children) == 1
    assert parent.children[0].name == "child"


def test_generation_records_cost_on_exit():
    """generation 退出时根据 usage 自动算 cost 并挂在 span 上。"""
    backend = _ConsoleBackend()
    with backend.trace("root"):
        with backend.generation("answer", model="glm-4") as g:
            g.usage = {"input": 1000, "output": 200, "unit": "TOKENS"}
    # (1000+200)*50/1e6 = 0.06
    assert g.cost == 0.06


def test_trace_total_cost_sums_all_generations():
    """trace 总成本 = 所有 generation（含嵌套）的 cost 之和。"""
    backend = _ConsoleBackend()
    with backend.trace("root") as t:
        with backend.generation("g1", model="glm-4-flash") as g1:  # 免费
            g1.usage = {"input": 100, "output": 10}
        with backend.span("retrieve"):
            with backend.generation("g2", model="glm-4") as g2:   # 嵌套也要算
                g2.usage = {"input": 500, "output": 100}
    # 只有 g2 计费：(500+100)*50/1e6 = 0.03
    assert t.total_cost() == 0.03


def test_start_trace_trace_span_trace_generation_public_api(capsys):
    """对外门面：start_trace / trace_span / trace_generation 可串联且打印树。"""
    tracing._backend = None
    init_tracing()
    with start_trace("kb_qa.ask", question="q") as _:
        with trace_generation("condense", model="glm-4-flash") as g:
            g.usage = {"input": 10, "output": 5, "unit": "TOKENS"}
        with trace_span("retrieve", query="q") as r:
            r.output = "3 条"
        with trace_generation("answer", model="glm-4") as gen:
            gen.usage = {"input": 100, "output": 50, "unit": "TOKENS"}
    # 降级模式会打印 trace 树到 stderr
    captured = capsys.readouterr()
    assert "trace" in captured.err
    assert "GENERATION" in captured.err
    assert "SPAN" in captured.err
