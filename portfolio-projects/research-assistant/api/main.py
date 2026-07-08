"""FastAPI 应用：把研究系统包成 HTTP 服务。

路由：
    POST /api/research   —— SSE 流式研究（progress + token + done 事件）
    GET  /api/health     —— 健康检查
    GET  /               —— 极简聊天前端（static/index.html）

lifespan：启动时不预建图（按请求建，因为 saver 是 contextmanager）；
         这里留扩展点（未来预热、连外部 DB 等）。

运行：
    uvicorn api.main:app --reload --port 8000
    或  python -m api.main
"""
from __future__ import annotations

import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

# 让 api 包能 import 顶层 src（无论从哪启动）
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from research_assistant.config import settings
from research_assistant.persist import is_persistent
from research_assistant.service import stream_research

from .schemas import HealthResponse, ResearchRequest, ResearchResult


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动/关闭钩子。

    当前 saver 按请求建（contextmanager），无需全局持有。
    lifespan 留作扩展：未来预热模型、连外部 DB、预热图等。
    """
    # 启动
    app.state.persistent = is_persistent()
    yield
    # 关闭（目前无资源需清理）


app = FastAPI(
    title="AI 研究分析助手",
    description="基于 LangGraph 的多智能体并行研究系统（生产级）",
    version="0.1.0",
    lifespan=lifespan,
)

# 静态资源（前端页面）
_STATIC = Path(__file__).resolve().parent.parent / "static"
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """健康检查 + 配置概览。"""
    return HealthResponse(
        persistent=is_persistent(),
        smart_model=settings.smart_model,
        fast_model=settings.fast_model,
    )


@app.post("/api/research")
async def research(req: ResearchRequest):
    """SSE 流式研究。返回 text/event-stream。

    事件流（前端用 EventSource 监听）：
        progress —— {node, label, status, ...} 节点进度
        token    —— {node, content} writer 逐 token 输出
        done     —— {report, findings, review_decision, rewrite_count} 最终结果
        error    —— {message} 异常

    客户端示例见 static/index.html。
    """
    thread_id = req.thread_id or f"api-{uuid.uuid4().hex[:8]}"

    async def event_generator():
        try:
            async for event in stream_research(req.topic, thread_id):
                yield event
        except Exception as e:
            import json
            yield {
                "event": "error",
                "data": json.dumps({"message": str(e)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator())


@app.get("/")
async def index():
    """根路径返回聊天前端页面。"""
    index_html = _STATIC / "index.html"
    if index_html.exists():
        return FileResponse(str(index_html))
    raise HTTPException(status_code=404, detail="前端未构建（static/index.html 缺失）")


def main() -> None:
    """直接 python -m api.main 启动。"""
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
