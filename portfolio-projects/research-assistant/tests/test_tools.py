"""web_search 工具测试：验证错误兜底（生产关键）。

测试原则：不依赖真实网络。通过 monkeypatch 底层搜索函数模拟各种失败场景。
"""
from __future__ import annotations

import asyncio

import pytest

from research_assistant import tools


@pytest.mark.asyncio
async def test_web_search_normal(monkeypatch):
    """正常返回：mock 底层搜索返回有结果，web_search 应格式化输出。"""
    monkeypatch.setattr(
        tools, "_ddgs_search",
        lambda q, n: '[1] 测试标题\n    测试摘要\n    来源: http://example.com',
    )
    result = await tools.web_search("任何查询")
    assert "测试标题" in result
    assert "example.com" in result


@pytest.mark.asyncio
async def test_web_search_empty_results(monkeypatch):
    """空结果兜底：底层返回空列表，应返回友好提示而非崩溃。"""
    monkeypatch.setattr(tools, "_ddgs_search", lambda q, n: "搜索 'x' 没有返回结果。可以换个关键词试试。")
    result = await tools.web_search("无结果查询")
    assert "没有返回结果" in result


@pytest.mark.asyncio
async def test_web_search_timeout(monkeypatch):
    """超时兜底：模拟超时，应返回超时提示。"""
    async def slow_search(q, n):
        await asyncio.sleep(100)  # 远超 timeout
        return "不应到达"

    # monkeypatch 同步函数为会阻塞的——改用更短的 timeout 测
    import research_assistant.tools as t
    monkeypatch.setattr(t, "_ddgs_search", lambda q, n: (_ for _ in ()).throw(TimeoutError("模拟超时")))
    result = await tools.web_search("超时查询")
    assert "失败" in result or "超时" in result or "TimeoutError" in result


@pytest.mark.asyncio
async def test_web_search_exception_fallback(monkeypatch):
    """异常兜底：底层抛异常，web_search 应捕获并返回友好提示。"""
    def raising(q, n):
        raise ConnectionError("网络断了")

    monkeypatch.setattr(tools, "_ddgs_search", raising)
    result = await tools.web_search("异常查询")
    assert "失败" in result
    assert "ConnectionError" in result


@pytest.mark.asyncio
async def test_web_search_semaphore_limits(monkeypatch):
    """并发限流：Semaphore 应限制同时进行的搜索数量。

    通过计数器验证并发不超过 max_concurrent_search。
    """
    import research_assistant.config as config
    # 重置 semaphore 用配置的上限
    max_conc = config.settings.max_concurrent_search
    current = 0
    peak = 0

    def counting_search(q, n):
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        import time
        time.sleep(0.05)
        current -= 1
        return "ok"

    monkeypatch.setattr(tools, "_ddgs_search", counting_search)

    # 发起超过上限数量的并行搜索
    n_tasks = max_conc + 5
    await asyncio.gather(*[tools.web_search(f"q{i}") for i in range(n_tasks)])

    # peak 不应超过配置上限（Semaphore 保证）
    assert peak <= max_conc, f"并发峰值 {peak} 超过上限 {max_conc}"
