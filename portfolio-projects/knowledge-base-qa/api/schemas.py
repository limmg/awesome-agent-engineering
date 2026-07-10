"""API 请求/响应模型（pydantic 输入校验）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="用户问题")
    thread_id: str | None = Field(default=None, max_length=64, description="会话线程 id，不传则新开")
    mode: str | None = Field(
        default=None,
        pattern="^(vector|hybrid|rerank)$",
        description="检索模式，不传用配置默认",
    )


class UploadResponse(BaseModel):
    filename: str
    added_chunks: int
    total_chunks: int


class HealthResponse(BaseModel):
    status: str = "ok"
    answer_model: str
    enable_rerank: bool
    total_chunks: int


class FeedbackRequest(BaseModel):
    """用户对某次问答的反馈（点赞/点踩）—— 线上评估的反馈信号（LLMOps L03）。"""
    thread_id: str | None = Field(default=None, max_length=64, description="会话线程 id")
    question: str = Field(min_length=1, max_length=2000, description="当时的问题")
    answer: str = Field(min_length=0, max_length=8000, description="当时的答案")
    rating: str = Field(pattern="^(up|down)$", description="up=点赞 down=点踩")
    contexts: list[str] | None = Field(default=None, description="当时召回的材料（可选，便于复盘）")


class FeedbackResponse(BaseModel):
    status: str = "ok"
    enqueued: bool = Field(description="是否入队（点踩=True 入队，点赞=False）")
