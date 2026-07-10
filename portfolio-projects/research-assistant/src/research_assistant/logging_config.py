"""结构化日志：节点进出 + 耗时 + 关键指标（阶段 4 可观测性）。

设计：
    - 不引入重量级日志框架（loguru/structlog），用标准 logging + 统一格式
    - 节点级计时装饰器：自动记录每个节点的进出 + 耗时
    - JSON 友好的字段（node/duration_ms/status），方便接 ELK/Loki

生产演进：未来可换 LangSmith 做全链路 trace，本模块作为轻量本地日志打底。
"""
from __future__ import annotations

import functools
import logging
import time
from typing import Callable

# 统一日志格式：时间 级别 [节点] 消息
_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATEFMT = "%H:%M:%S"

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """初始化全局日志配置（幂等，重复调用安全）。"""
    global _configured
    if _configured:
        return
    logging.basicConfig(format=_FORMAT, datefmt=_DATEFMT, level=level)
    # 降低第三方库噪声
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("primp").setLevel(logging.WARNING)  # ddgs 底层 HTTP 库，会刷屏
    logging.getLogger("duckduckgo_search").setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """获取带统一配置的 logger。"""
    setup_logging()
    return logging.getLogger(name)


def timed_node(func: Callable) -> Callable:
    """节点计时装饰器：记录进出 + 耗时。

    用法：
        @timed_node
        def researcher(state): ...

    同时支持 sync 和 async 函数（自动检测）。
    """
    log = get_logger(f"node.{func.__name__}")
    node_name = func.__name__

    if _is_async(func):

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            log.info(f"▶ {node_name} start")
            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.perf_counter() - t0) * 1000
                # 摘要结果大小（不打印全部，避免日志爆炸）
                summary = _summarize_result(result)
                log.info(f"✓ {node_name} done | {duration_ms:.0f}ms | {summary}")
                return result
            except Exception as e:
                duration_ms = (time.perf_counter() - t0) * 1000
                log.error(f"✗ {node_name} failed | {duration_ms:.0f}ms | {type(e).__name__}: {e}")
                raise

        return async_wrapper

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        log.info(f"▶ {node_name} start")
        try:
            result = func(*args, **kwargs)
            duration_ms = (time.perf_counter() - t0) * 1000
            summary = _summarize_result(result)
            log.info(f"✓ {node_name} done | {duration_ms:.0f}ms | {summary}")
            return result
        except Exception as e:
            duration_ms = (time.perf_counter() - t0) * 1000
            log.error(f"✗ {node_name} failed | {duration_ms:.0f}ms | {type(e).__name__}: {e}")
            raise

    return sync_wrapper


def _is_async(func: Callable) -> bool:
    import asyncio
    return asyncio.iscoroutinefunction(func)


def _summarize_result(result) -> str:
    """把节点返回的 state 增量摘要成简短字符串（避免日志爆炸）。"""
    if not isinstance(result, dict):
        return f"→ {type(result).__name__}"
    parts = []
    for k, v in result.items():
        if isinstance(v, (list, str)):
            parts.append(f"{k}={len(v)}")
        elif isinstance(v, (int, float)):
            parts.append(f"{k}={v}")
        else:
            parts.append(f"{k}=?")
    return "→ {" + ", ".join(parts) + "}"
