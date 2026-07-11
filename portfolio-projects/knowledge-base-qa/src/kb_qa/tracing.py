"""全链路追踪：Langfuse 接入 + 控制台降级（LLMOps L02）。

设计目标：
    - 装了 langfuse 且配了服务 → 真实上报 trace 树到 Langfuse 面板
    - 没装 / 没配 → 降级为 ConsoleTracer，把等价的 trace 树打印到 stdout
    - 对 service.py 透明：业务代码只调 trace_span / trace_generation，不关心后端

为什么这样设计：
    本课程要求「外部服务不具备时优雅降级」。Langfuse 是可选增强，
    不能因为没装它就让 kb-qa 跑不起来。降级路径保证 L01–L12 任何环境都能演示。

对外接口（service.py 只用这四个）：
    init_tracing()                      进程启动时初始化（探测 langfuse）
    trace_span(name, **meta)            with 上下文：开一个普通 span
    trace_generation(name, model, ...)  with 上下文：开一个 LLM 调用 span
    flush()                             退出前调用，确保 trace 不丢
"""
from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from .config import settings
from .observability import get_logger

_log = get_logger("kb_qa.tracing")

def compute_cost(model: str, usage: dict) -> float:
    """按 token 用量 + 模型单价算成本（元）。generation 退出时自动调用。

    单价集中在 settings.model_price_table（来源与更新说明见 config.py）。
    """
    price = settings.model_price_table.get(model, {"input": 0.0, "output": 0.0})
    in_tok = usage.get("input", 0)
    out_tok = usage.get("output", 0)
    return round((in_tok * price["input"] + out_tok * price["output"]) / 1_000_000, 6)


# ════════════════════════════════════════════════════════════════
# 降级实现：ConsoleTracer（不依赖 langfuse）
# ════════════════════════════════════════════════════════════════
@dataclass
class _Span:
    name: str
    kind: str = "span"            # "span" | "generation"
    input: Any = None
    output: Any = None
    start: float = 0.0
    end: float = 0.0
    metadata: dict = field(default_factory=dict)
    model: str | None = None
    usage: dict | None = None
    cost: float = 0.0
    children: list["_Span"] = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        return round((self.end - self.start) * 1000) if self.end else 0


@dataclass
class _Trace:
    name: str
    input: Any = None
    output: Any = None
    metadata: dict = field(default_factory=dict)
    spans: list[_Span] = field(default_factory=list)

    def total_cost(self) -> float:
        total = 0.0

        def walk(spans: list[_Span]) -> None:
            for s in spans:
                total_ref[0] += s.cost
                walk(s.children)

        total_ref = [0.0]
        walk(self.spans)
        return total_ref[0]


class _ConsoleBackend:
    """降级后端：用栈管理父子关系，结束时打印 trace 树。

    与 L02 教学 code.py 的 ConsoleTracer 同构；这里作为生产模块。
    """

    def __init__(self) -> None:
        self._stack: list[_Span] = []
        self._trace: _Trace | None = None

    @contextmanager
    def trace(self, name: str, **meta) -> Iterator[_Trace]:
        self._trace = _Trace(name=name, metadata=meta)
        self._stack.clear()
        try:
            yield self._trace
        finally:
            self._render()
            self._trace = None

    @contextmanager
    def span(self, name: str, **meta) -> Iterator[_Span]:
        s = _Span(name=name, kind="span", metadata=meta, start=time.perf_counter())
        self._attach(s)
        self._stack.append(s)
        try:
            yield s
        finally:
            s.end = time.perf_counter()
            self._stack.pop()

    @contextmanager
    def generation(self, name: str, model: str, **meta) -> Iterator[_Span]:
        g = _Span(name=name, kind="generation", model=model, metadata=meta,
                  start=time.perf_counter())
        self._attach(g)
        self._stack.append(g)
        try:
            yield g
        finally:
            g.end = time.perf_counter()
            if g.usage:
                g.cost = compute_cost(g.model or "", g.usage)
            self._stack.pop()

    def _attach(self, s: _Span) -> None:
        if self._stack:
            self._stack[-1].children.append(s)
        elif self._trace is not None:
            self._trace.spans.append(s)

    def _render(self) -> None:
        if not self._trace:
            return
        t = self._trace
        print(f"\n┌─ [trace] {t.name}", file=sys.stderr)
        if t.metadata:
            print(f"│  meta: {t.metadata}", file=sys.stderr)

        def walk(spans: list[_Span], prefix: str = "│") -> None:
            for i, s in enumerate(spans):
                last = (i == len(spans) - 1)
                branch = "└─" if last else "├─"
                child_prefix = prefix.replace("├", "│").replace("└", " ") + ("  " if last else "│ ")
                tag = s.kind.upper()
                extra = ""
                if s.kind == "generation":
                    extra = f" | model={s.model} cost=¥{s.cost:.6f}"
                print(f"{prefix}{branch} {tag} {s.name} ({s.duration_ms}ms){extra}",
                      file=sys.stderr)
                if s.children:
                    walk(s.children, child_prefix)

        walk(t.spans)
        print(f"└─ 💰 本次问答估算成本: ¥{t.total_cost():.6f}", file=sys.stderr)

    def flush(self) -> None:
        pass  # 控制台即时打印，无需 flush


# ════════════════════════════════════════════════════════════════
# Langfuse 后端（装了 langfuse 且启用时才用）
# ════════════════════════════════════════════════════════════════
class _LangfuseBackend:
    """真实 Langfuse 后端：用 SDK v3 的 start_as_current_observation。

    父子关系由 OTel context 自动管理（内层 with 自动成为外层的子节点），
    和 _ConsoleBackend 的栈机制等价，只是上报到面板而非打印。
    """

    def __init__(self) -> None:
        from langfuse import get_client  # 延迟导入：没装时不会在模块加载就崩
        self._lf = get_client()

    @contextmanager
    def trace(self, name: str, **meta) -> Iterator[Any]:
        with self._lf.start_as_current_observation(as_type="span", name=name) as obs:
            obs.update(metadata=meta)
            yield obs

    @contextmanager
    def span(self, name: str, **meta) -> Iterator[Any]:
        with self._lf.start_as_current_observation(as_type="span", name=name) as obs:
            if meta:
                obs.update(metadata=meta)
            yield obs

    @contextmanager
    def generation(self, name: str, model: str, **meta) -> Iterator[Any]:
        with self._lf.start_as_current_observation(
            as_type="generation", name=name, model=model
        ) as obs:
            if meta:
                obs.update(metadata=meta)
            yield obs

    def flush(self) -> None:
        self._lf.flush()


# ════════════════════════════════════════════════════════════════
# 统一门面：根据配置选后端
# ════════════════════════════════════════════════════════════════
_backend: _ConsoleBackend | _LangfuseBackend | None = None


def init_tracing() -> None:
    """进程启动时调用一次：探测 langfuse，决定用哪个后端。

    启用真实 Langfuse 的条件（全满足才启用，否则降级）：
        1. settings.langfuse_enabled = True
        2. 装了 langfuse 包
        3. 配了 host + public_key + secret_key
    任一不满足 → 用 ConsoleTracer，保证可运行。
    """
    global _backend
    if _backend is not None:
        return

    use_langfuse = (
        settings.langfuse_enabled
        and settings.langfuse_host
        and settings.langfuse_public_key
        and settings.langfuse_secret_key
    )
    if use_langfuse:
        try:
            _backend = _LangfuseBackend()
            _log.info("tracing 启用 Langfuse 后端", extra={
                "event": "tracing.init", "backend": "langfuse",
                "host": settings.langfuse_host,
            })
            return
        except ImportError:
            _log.warning("未安装 langfuse，降级到 ConsoleTracer（pip install langfuse）",
                         extra={"event": "tracing.fallback", "reason": "no_langfuse_pkg"})
        except Exception as e:
            _log.warning(f"Langfuse 初始化失败，降级到 ConsoleTracer: {e}",
                         extra={"event": "tracing.fallback", "reason": str(e)})
    else:
        _log.info("tracing 使用 ConsoleTracer（未配置 Langfuse）",
                  extra={"event": "tracing.init", "backend": "console"})

    _backend = _ConsoleBackend()


def _ensure() -> _ConsoleBackend | _LangfuseBackend:
    if _backend is None:
        init_tracing()
    assert _backend is not None
    return _backend


@contextmanager
def trace_span(name: str, **meta) -> Iterator[Any]:
    """开一个普通 span。with 块内的子 span 自动成为它的子节点。"""
    with _ensure().span(name, **meta) as s:
        yield s


@contextmanager
def trace_generation(name: str, model: str, **meta) -> Iterator[Any]:
    """开一个 generation span（LLM 调用，带 model/usage/cost）。

    退出前给 span 赋 .usage，后端会自动算 cost（ConsoleTracer）或上报（Langfuse）。
    """
    with _ensure().generation(name, model=model, **meta) as g:
        yield g


@contextmanager
def start_trace(name: str, **meta) -> Iterator[Any]:
    """开一个 trace（一次请求的根）。整个问答包在最外层。"""
    with _ensure().trace(name, **meta) as t:
        yield t


def flush() -> None:
    """进程退出 / 请求结束前调用，确保 trace 上报不丢。"""
    if _backend is not None:
        _backend.flush()


def is_langfuse_active() -> bool:
    """当前是否在用真实 Langfuse 后端（测试 / 诊断用）。"""
    return isinstance(_backend, _LangfuseBackend)
