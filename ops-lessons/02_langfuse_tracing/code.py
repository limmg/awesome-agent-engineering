"""
Lesson 02 — 全链路追踪：接入 Langfuse
======================================
本脚本【零外部依赖】实现一个 ConsoleTracer，让你看清 trace/span/generation
的数据模型——这正是 Langfuse（及所有 tracing 系统）的核心抽象。

学完这个，再去看 Langfuse SDK 的 start_as_current_observation 就秒懂了：
它们做的事一模一样，只是 ConsoleTracer 打印到屏幕、Langfuse 上报到面板。

运行：python code.py
依赖：仅标准库
"""
from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

# Windows GBK 控制台坑：中文会崩，统一 utf-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ════════════════════════════════════════════════════════════════
# 1. 数据模型：trace / span / generation
# ════════════════════════════════════════════════════════════════
@dataclass
class Span:
    """一个操作步骤。generation 是它的特化（多出 model/usage/cost）。"""
    name: str
    kind: str = "span"            # "span" | "generation"
    input: Any = None
    output: Any = None
    start: float = 0.0
    end: float = 0.0
    metadata: dict = field(default_factory=dict)
    # generation 专属
    model: str | None = None
    usage: dict | None = None     # {"input":..,"output":..,"unit":"TOKENS"}
    cost: float = 0.0
    children: list["Span"] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        return round((self.end - self.start) * 1000) if self.end else 0


@dataclass
class Trace:
    """一次完整请求的根。挂在它名下的 span 组成一棵树。"""
    name: str
    input: Any = None
    output: Any = None
    metadata: dict = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)  # 顶层 span

    def total_cost(self) -> float:
        """递归汇总整棵树里所有 generation 的成本。"""
        total = 0.0

        def walk(spans: list[Span]) -> None:
            for s in spans:
                total_ref[0] += s.cost
                walk(s.children)

        total_ref = [0.0]
        walk(self.spans)
        return total_ref[0]


# ════════════════════════════════════════════════════════════════
# 2. ConsoleTracer：用「栈」管理父子关系，with 自动嵌套
# ════════════════════════════════════════════════════════════════
class ConsoleTracer:
    """不依赖 Langfuse 的 trace 记录器，效果等价：树形 + 成本汇总。

    设计精髓：用一个 _stack 记录「当前所在的 span」。
    with trace_span("retrieve") 进来时压栈 → 它的子 with 自动挂到 retrieve 下。
    这正是 Langfuse/OTel 用 context 管理父子关系的简化版。
    """

    def __init__(self) -> None:
        self._stack: list[Span] = []
        self.trace: Trace | None = None

    @contextmanager
    def start_trace(self, name: str, **meta) -> Iterator[Trace]:
        """开一个 trace（一次请求的根）。"""
        self.trace = Trace(name=name, metadata=meta)
        self._stack.clear()
        yield self.trace
        # trace 结束时打印（main 里手动调 render 更可控，这里不自动打）

    @contextmanager
    def span(self, name: str, **meta) -> Iterator[Span]:
        """开一个普通 span（检索/rerank 等操作步骤）。"""
        s = Span(name=name, kind="span", metadata=meta, start=time.perf_counter())
        self._attach(s)
        self._stack.append(s)
        try:
            yield s
        finally:
            s.end = time.perf_counter()
            self._stack.pop()

    @contextmanager
    def generation(self, name: str, model: str, **meta) -> Iterator[Span]:
        """开一个 generation span（LLM 调用，带 model/usage/cost）。

        为什么 generation 单独有方法？因为只有它需要算钱——
        退出时根据 usage 和价目表自动算 cost。
        """
        g = Span(name=name, kind="generation", model=model, metadata=meta,
                 start=time.perf_counter())
        self._attach(g)
        self._stack.append(g)
        try:
            yield g
        finally:
            g.end = time.perf_counter()
            if g.usage:
                g.cost = compute_cost(g.model, g.usage)
            self._stack.pop()

    def _attach(self, s: Span) -> None:
        """把新 span 挂到当前栈顶（成为它的子节点），栈空则挂到 trace 根。"""
        if self._stack:
            self._stack[-1].children.append(s)
        elif self.trace is not None:
            self.trace.spans.append(s)


# ════════════════════════════════════════════════════════════════
# 3. 成本核算：token → 钱
# ════════════════════════════════════════════════════════════════
# 智谱公开价（元/百万 token），写死在 demo 里；生产版从 config 读
PRICE_TABLE = {
    "glm-4":       {"input": 50.0, "output": 50.0},
    "glm-4-flash": {"input": 0.0,  "output": 0.0},   # flash 免费
}


def compute_cost(model: str, usage: dict) -> float:
    """按 token 用量和模型单价算成本（元）。

    generation 退出时自动调用；面板的「成本汇总」就是把所有 generation 的 cost 加起来。
    """
    price = PRICE_TABLE.get(model, {"input": 0.0, "output": 0.0})
    in_tok = usage.get("input", 0)
    out_tok = usage.get("output", 0)
    return round((in_tok * price["input"] + out_tok * price["output"]) / 1_000_000, 6)


# ════════════════════════════════════════════════════════════════
# 4. 渲染：把 trace 树打印成可视化结构
# ════════════════════════════════════════════════════════════════
def render(trace: Trace) -> None:
    """ASCII 打印 trace 树（模仿 Langfuse 面板的树形视图）。"""
    print(f"\n┌─ trace: {trace.name}")
    print(f"│  input : {trace.metadata.get('question', '')}")

    def walk(spans: list[Span], prefix: str = "│") -> None:
        for i, s in enumerate(spans):
            last = (i == len(spans) - 1)
            branch = "└─" if last else "├─"
            child_prefix = prefix.replace("├", "│").replace("└", " ") + ("  " if last else "│ ")
            tag = s.kind.upper()
            extra = ""
            if s.kind == "generation":
                extra = f" | model={s.model} usage={s.usage} cost=¥{s.cost:.6f}"
            print(f"{prefix}{branch} {tag} {s.name} ({s.duration_ms}ms){extra}")
            if s.children:
                walk(s.children, child_prefix)

    walk(trace.spans)
    total = trace.total_cost()
    print(f"└─ 💰 本次问答总成本: ¥{total:.6f}")


# ════════════════════════════════════════════════════════════════
# 5. 模拟一次 kb-qa 问答，用 tracer 埋点
# ════════════════════════════════════════════════════════════════
def fake_condense(tracer: ConsoleTracer, question: str) -> str:
    """模拟追问改写（glm-4-flash，免费）。"""
    with tracer.generation("condense", model="glm-4-flash") as g:
        time.sleep(0.05)
        rewritten = f"独立问题：{question}"
        g.output = rewritten
        g.usage = {"input": 180, "output": 25, "unit": "TOKENS"}  # flash 免费
    return rewritten


def fake_retrieve(tracer: ConsoleTracer, query: str) -> list[str]:
    """模拟检索 + rerank（rerank 嵌套在 retrieve 下 → 演示树形）。"""
    with tracer.span("retrieve", query=query) as r:
        time.sleep(0.08)
        docs = ["试用期 3 个月（云帆科技员工手册）", "转正工资 100%"]
        r.output = f"{len(docs)} 条材料"
        r.metadata["hits"] = len(docs)

        # rerank 作为 retrieve 的子 span —— 这就是「树」的来源
        with tracer.span("rerank") as rk:
            time.sleep(0.04)
            rk.output = f"保留 {min(2, len(docs))} 条"
            rk.metadata["model"] = "zhipu-rerank"
    return docs


def fake_generate(tracer: ConsoleTracer, question: str, docs: list[str]) -> str:
    """模拟最终生成（glm-4，要算钱）。"""
    with tracer.generation("answer", model="glm-4") as gen:
        time.sleep(0.12)
        answer = "云帆科技试用期 3 个月，转正后工资为基本工资的 100%。"
        gen.output = answer
        # 估算 usage（in=材料+问题，out=答案）
        gen.usage = {"input": 820, "output": 210, "unit": "TOKENS"}
    return answer


def handle_ask(tracer: ConsoleTracer, question: str) -> str:
    """一次完整问答：开 trace，各步骤包成 span/generation。"""
    with tracer.start_trace("kb_qa.ask", question=question, thread_id="demo"):
        q = fake_condense(tracer, question)
        docs = fake_retrieve(tracer, q)
        answer = fake_generate(tracer, question, docs)
        tracer.trace.output = answer  # type: ignore[union-attr]
    return answer


# ════════════════════════════════════════════════════════════════
# 6. main
# ════════════════════════════════════════════════════════════════
def main() -> None:
    print("=" * 64)
    print("演示：用 ConsoleTracer 记录一次问答的 trace 树（零依赖）")
    print("这棵树 = Langfuse 面板上你会看到的东西的文本版")
    print("=" * 64)

    tracer = ConsoleTracer()
    handle_ask(tracer, "云帆科技试用期多久？")
    render(tracer.trace)  # type: ignore[arg-type]

    print("\n" + "=" * 64)
    print("对照：同样的埋点，接 Langfuse SDK 长这样（需 pip install langfuse）")
    print("=" * 64)
    print("""
from langfuse import get_client
lf = get_client()  # 从环境变量读 host/key，没配则 no-op

with lf.start_as_current_observation(as_type="span", name="kb_qa.ask") as trace:
    trace.update(input=question)
    with lf.start_as_current_observation(as_type="generation", name="condense", model="glm-4-flash") as g:
        rewritten = condense(...)
        g.update(output=rewritten, usage={"input":180,"output":25,"unit":"TOKENS"})
    with lf.start_as_current_observation(as_type="span", name="retrieve") as r:
        docs = retrieve(...)
        r.update(output=len(docs))
    with lf.start_as_current_observation(as_type="generation", name="answer", model="glm-4") as gen:
        answer = generate(...)
        gen.update(output=answer, usage={"input":820,"output":210,"unit":"TOKENS"})
lf.flush()
# → 打开 Langfuse 面板，看到的是上面那棵树的可视化版 + 成本自动汇总
""")
    print("💡 关键：ConsoleTracer 和 Langfuse SDK 做的事【完全一样】——")
    print("   都是「开 trace → 嵌套 span/generation → 记录 input/output/usage」。")
    print("   区别只是 ConsoleTracer 打屏幕、Langfuse 上报面板。原理懂了，工具随便换。")


if __name__ == "__main__":
    main()
