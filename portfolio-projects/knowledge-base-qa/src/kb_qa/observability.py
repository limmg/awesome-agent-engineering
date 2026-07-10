"""可观测性地基：结构化（JSON）日志 + trace_id 上下文 + 脱敏工具（LLMOps L01）。

为什么独立成模块：
    - service.py 的问答流程要在「改写/检索/rerank/生成」各节点打事件，
      但不想让业务代码塞满格式化细节 → 抽到本模块，业务侧只调 log_event()
    - trace_id 用 contextvars 隔离，async 安全（一次请求一份，并发不串台）
    - 这是 L02 接 Langfuse、L03 线上评估的共同数据源：trace 字段保持一致

设计取舍：
    - 不引 loguru/structlog，用标准 logging + 自写 JSON formatter（零新依赖）
    - log_json 开关：生产 True（机器消费），开发可关掉看人类可读文本
"""
from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

from .config import settings

# ── trace_id 上下文 ──────────────────────────────────────────────
# contextvars：每个 async 任务/线程一份独立拷贝，并发请求互不串扰。
# 这是一次请求贯穿「检索→生成」全链路的串联 id。
_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")


def new_trace_id() -> str:
    """生成 8 位 hex trace_id（短且足够唯一，便于日志检索）。"""
    return uuid.uuid4().hex[:8]


def set_trace_id(tid: str) -> None:
    """在请求入口调用，把 id 放进当前上下文。"""
    _trace_id.set(tid)


def get_trace_id() -> str:
    """取当前上下文的 trace_id（未设置时返回 '-'，日志仍可打）。"""
    return _trace_id.get()


# ── JSON Formatter ───────────────────────────────────────────────
# 标准库 logging 的「内置字段」白名单，序列化时要跳过这些 record 属性。
_RECORD_BUILTINS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
}


class JsonFormatter(logging.Formatter):
    """每条日志序列化成一行 JSON：字段化、机器可消费、可 jq/grep。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": get_trace_id(),  # 自动注入当前请求的 trace_id
            "msg": record.getMessage(),
        }
        # 调用方用 extra={...} 塞进来的业务字段（event/hits/duration_ms...）
        for key, val in record.__dict__.items():
            if key in payload or key in _RECORD_BUILTINS or key.startswith("_"):
                continue
            payload[key] = val
        return json.dumps(payload, ensure_ascii=False)


class _TextFormatter(logging.Formatter):
    """人类可读文本格式（开发期 log_json=False 时用），仍带 trace_id。"""

    _FMT = "%(asctime)s | %(levelname)-7s | %(name)s | trace=%(trace_id)s | %(message)s"
    _DATEFMT = "%H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        # 注入 trace_id 给 %(trace_id)s 占位符
        record.trace_id = get_trace_id()
        return super().format(record)


_configured = False


def setup_logging() -> None:
    """初始化全局日志配置（幂等，重复调用安全）。

    根据 settings.log_json 决定输出 JSON 还是文本；
    根据 settings.log_level 决定级别。
    """
    global _configured
    if _configured:
        return

    level = getattr(logging, str(settings.log_level).upper(), logging.INFO)
    root = logging.getLogger()

    # 清掉可能的默认 handler，确保用我们的 formatter
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if settings.log_json else _TextFormatter())
    handler.setLevel(level)
    root.addHandler(handler)
    root.setLevel(level)

    # Windows 下 stdout 默认 GBK，中文日志会崩 —— 强制 utf-8
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # 压低第三方库噪声（否则 httpx/chroma 会刷屏，淹没业务日志）
    for noisy in ("httpx", "httpcore", "openai", "chromadb", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """拿一个配好格式的 logger（首次调用触发 setup_logging）。"""
    setup_logging()
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    event: str,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """打一条结构化事件的便捷函数。

    用法：
        log_event(log, "retrieve.done", hits=8, duration_ms=320, mode="rerank")

    会输出（JSON 模式）：
        {"event":"retrieve.done","hits":8,"duration_ms":320,"mode":"rerank",...}
    event 是最值钱的检索键——线上按 event 聚合统计全靠它。
    """
    logger.log(level, event, extra={"event": event, **fields})


# ── 脱敏工具 ─────────────────────────────────────────────────────
def mask_secret(secret: str | None, keep_tail: int = 4) -> str:
    """API key / 密钥落日志前掩码：sk-abcd1234 → ***1234。

    保留尾部 keep_tail 位便于辨认是哪个 key，但绝不暴露主体。
    None/空串返回空串。
    """
    if not secret:
        return ""
    if len(secret) <= keep_tail:
        return "***"
    return "***" + secret[-keep_tail:]


# ── token 估算（成本信号，L02/L12 会用到）────────────────────────
def estimate_tokens(text: str) -> int:
    """粗估 token 数：中文按字、英文按 4 字符 1 token。

    教学近似（真实生产用 tokenizer 精确计数）；让日志/trace 里有成本信号即可。
    L02 接 Langfuse 后会有真实 token 计数，这里作为本地兜底。
    """
    if not text:
        return 0
    zh = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other = len(text) - zh
    return zh + other // 4
