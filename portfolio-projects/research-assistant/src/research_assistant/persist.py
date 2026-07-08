"""持久化工厂：Checkpointer 的生命周期管理。

生产化关键升级（对比 L09 的 InMemorySaver）：
    - InMemorySaver：进程退出即丢，重启后追问失忆
    - SqliteSaver/AsyncSqliteSaver：写本地 sqlite 文件，跨进程/跨重启记忆

⚠️ 重要约束：本项目的图走 async 路径（researcher 节点真实联网是 async），
所以必须用 AsyncSqliteSaver（同步 SqliteSaver 不支持 aget_tuple 等 async 方法）。
AsyncSqliteSaver 依赖 aiosqlite。

提供两个工厂：
    - get_saver_context()：同步 contextmanager，纯 sync 调用场景 / 测试
    - get_async_saver_context()：异步 contextmanager，生产 async 图用
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncIterator, Iterator

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from .config import settings


@contextmanager
def get_saver_context() -> Iterator:
    """同步 contextmanager：yield 一个【同步】checkpointer。

    用于纯 sync 调用场景（如部分单元测试）。生产 async 图请用 get_async_saver_context。

    行为：
        - sqlite_db_path 非空 → SqliteSaver（持久化）
        - sqlite_db_path 为空 → InMemorySaver（纯内存，测试用）
    """
    db_path = settings.sqlite_db_path.strip()
    if not db_path:
        yield InMemorySaver()
        return

    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)

    with SqliteSaver.from_conn_string(db_path) as saver:
        saver.setup()
        yield saver


@asynccontextmanager
async def get_async_saver_context() -> AsyncIterator:
    """异步 contextmanager：yield 一个【异步】checkpointer。

    生产用这个——async 图（ainvoke/astream）必须配 async checkpointer。
    内部用 AsyncSqliteSaver（基于 aiosqlite）。

    行为：
        - sqlite_db_path 非空 → AsyncSqliteSaver（持久化）
        - sqlite_db_path 为空 → InMemorySaver（纯内存；async API 也能用）
    """
    db_path = settings.sqlite_db_path.strip()
    if not db_path:
        yield InMemorySaver()
        return

    # 延迟 import：aiosqlite 是可选依赖，只在 async 持久化时需要
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)

    async with AsyncSqliteSaver.from_conn_string(db_path) as saver:
        await saver.setup()
        yield saver


def is_persistent() -> bool:
    """当前配置是否走持久化（供日志/诊断用）。"""
    return bool(settings.sqlite_db_path.strip())
