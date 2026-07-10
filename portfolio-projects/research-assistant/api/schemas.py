"""API 数据模型：请求/响应的 Pydantic schema。

FastAPI 用这些做请求校验 + 自动生成 OpenAPI 文档（/docs）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    """POST /api/research 请求体。"""
    topic: str = Field(..., min_length=1, max_length=500, description="研究主题")
    thread_id: str | None = Field(
        default=None, description="会话 ID；不传则服务端生成（用于跨轮记忆/隔离）"
    )


class HealthResponse(BaseModel):
    """GET /api/health 响应。"""
    status: str = "ok"
    persistent: bool = Field(description="是否启用持久化（SqliteSaver）")
    smart_model: str
    fast_model: str


class ResearchResult(BaseModel):
    """完整研究结果（invoke 非 SSE 调用的响应）。"""
    report: str
    findings: list[str]
    review_decision: str
    rewrite_count: int
    thread_id: str
