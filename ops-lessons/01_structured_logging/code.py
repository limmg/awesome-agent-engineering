"""
Lesson 01 — 结构化日志：从 print 到可查询的事件流
==================================================
本脚本【纯标准库实现】一个轻量结构化 logger，演示三个核心概念：
    ① 结构化日志：每条日志是一行 JSON（字段化），而非人类句子
    ② trace_id 贯穿：用 contextvars 给一次「请求」的所有日志带上同一个 id
    ③ 敏感信息脱敏：API key 等秘钥落日志前掩码

运行：python code.py
依赖：仅标准库（logging / json / contextvars / uuid / time）
"""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

# Windows 控制台默认 GBK，中文日志会 UnicodeEncodeError —— 统一改成 utf-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ════════════════════════════════════════════════════════════════
# 1. trace_id 上下文（contextvars：async 安全的「请求级变量」）
# ════════════════════════════════════════════════════════════════
# 为什么用 contextvars 而不是全局变量？
#   全局变量在并发（asyncio/线程）下会被别的请求覆盖；
#   contextvars 为每个「执行上下文」（一次请求）隔离一份拷贝，
#   互不串扰。这正是 async Web 服务里串 trace_id 的标准做法。
_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")


def new_trace_id() -> str:
    """生成一个短 trace_id（8 位 hex，够短也够唯一用于教学）。"""
    return uuid.uuid4().hex[:8]


def set_trace_id(tid: str) -> None:
    """在一次请求开始时调用，把 id 放进当前上下文。"""
    _trace_id.set(tid)


def get_trace_id() -> str:
    return _trace_id.get()


# ════════════════════════════════════════════════════════════════
# 2. JSON Formatter：把 LogRecord 序列化成一行 JSON
# ════════════════════════════════════════════════════════════════
class JsonFormatter(logging.Formatter):
    """结构化日志格式器：输出一行一个 JSON 对象。

    字段约定（机器消费友好）：
        ts        ISO 时间
        level     INFO/WARNING/ERROR...
        logger    logger 名
        event     事件名（如 retrieve.done）—— 最关键的检索键
        trace_id  请求级串联 id
        msg       人类可读说明
        <extra>   调用方额外塞进来的业务字段（hits/duration_ms...）
    """

    def format(self, record: logging.LogRecord) -> str:
        # logger.info("xxx", extra={"event":"retrieve.done","hits":8}) 时，
        # extra 的每个 key 会变成 record 的属性。
        payload: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": get_trace_id(),
            "msg": record.getMessage(),
        }
        # 把 extra 字段合并进来（event / hits / duration_ms 等业务字段）
        for key, val in record.__dict__.items():
            if key in payload or key.startswith("_"):
                continue
            if key in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
            }:
                continue
            payload[key] = val
        return json.dumps(payload, ensure_ascii=False)


def get_logger(name: str = "demo") -> logging.Logger:
    """拿一个配好 JSON 输出的 logger（幂等）。"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False  # 避免重复打印
    return logger


# ════════════════════════════════════════════════════════════════
# 3. 脱敏工具：API key / 密钥落日志前掩码
# ════════════════════════════════════════════════════════════════
def mask_secret(secret: str, keep_tail: int = 4) -> str:
    """把 sk-abcdef1234 → ***1234，保留尾部便于辨认是哪个 key。

    生产场景：日志里只打掩码后的，绝不打全 key。
    """
    if not secret:
        return ""
    if len(secret) <= keep_tail:
        return "***"
    return "***" + secret[-keep_tail:]


# ════════════════════════════════════════════════════════════════
# 4. 模拟一次「检索 → 生成」问答，打出带 trace_id 的事件链
# ════════════════════════════════════════════════════════════════
def fake_retrieve(query: str) -> list[str]:
    """模拟检索：返回几条假材料。"""
    log = get_logger("kb.retrieve")
    t0 = time.perf_counter()
    time.sleep(0.05)  # 假装在查向量库
    docs = ["试用期 3 个月", "转正工资为基本工资 100%"]
    duration_ms = round((time.perf_counter() - t0) * 1000)
    # 关键：event 是最值钱的检索键，业务字段全字段化
    log.info("检索完成", extra={
        "event": "retrieve.done",
        "hits": len(docs),
        "duration_ms": duration_ms,
        "mode": "rerank",
    })
    return docs


def fake_generate(query: str, docs: list[str]) -> str:
    """模拟生成：流式拼答案。"""
    log = get_logger("kb.generate")
    t0 = time.perf_counter()
    time.sleep(0.08)  # 假装 LLM 在吐字
    answer = "云帆科技试用期 3 个月，转正后工资为基本工资 100%。"
    duration_ms = round((time.perf_counter() - t0) * 1000)
    token_est = estimate_tokens(answer)
    log.info("生成完成", extra={
        "event": "generate.done",
        "duration_ms": duration_ms,
        "tokens": token_est,
    })
    return answer


def estimate_tokens(text: str) -> int:
    """粗估 token 数：中文按字、英文按 4 字符 1 token（教学近似）。

    真实生产会用 tokenizer 精确计数，这里近似是为了让日志里有成本信号。
    """
    zh = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other = len(text) - zh
    return zh + other // 4


def handle_ask(question: str) -> str:
    """模拟一次完整问答：贯穿同一个 trace_id。"""
    log = get_logger("kb.service")
    tid = new_trace_id()
    set_trace_id(tid)  # ← 本请求上下文设置，下面所有日志自动带这个 id

    log.info("请求开始", extra={"event": "request.start", "question": question})
    docs = fake_retrieve(question)
    answer = fake_generate(question, docs)
    log.info("请求结束", extra={
        "event": "request.done",
        "answer_preview": answer[:40],
    })
    return answer


# ════════════════════════════════════════════════════════════════
# 5. main：演示
# ════════════════════════════════════════════════════════════════
def main() -> None:
    print("=" * 64)
    print("演示 1：脱敏工具")
    print("=" * 64)
    print(f"原始 key : sk-abcd1234efgh5678")
    print(f"掩码后   : {mask_secret('sk-abcd1234efgh5678')}")

    print()
    print("=" * 64)
    print("演示 2：一次问答的结构化日志（每行一个 JSON，共享 trace_id）")
    print("=" * 64)
    handle_ask("云帆科技试用期多久？")

    print()
    print("=" * 64)
    print("演示 3：再问一次（trace_id 不同，证明上下文隔离）")
    print("=" * 64)
    handle_ask("转正工资多少？")

    print()
    print("=" * 64)
    print("演示 4：模拟「按 trace_id 还原链路」的排障")
    print("=" * 64)
    print("生产里日志会进文件/ELK，这里用 grep 思路说明：")
    print("  grep '\"trace_id\": \"<某id>\"' app.log")
    print("就能捞出那次请求的：request.start → retrieve.done → generate.done → request.done")
    print("→ 一眼看出哪步慢、召回几条、token 多少。")


if __name__ == "__main__":
    main()
