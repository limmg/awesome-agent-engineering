"""配置中心：所有可配置项集中在这里，用 pydantic-settings 从 .env 读取。

设计原则（沿用 research-assistant）：
    - 所有"会变的值"（模型名、路径、阈值、开关）不写死在业务代码里
    - 环境变量可覆盖，方便 Docker / 评估脚本切换配置
    - 一处定义，全项目 `from kb_qa.config import settings` 复用
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py 在 src/kb_qa/ 下：parents[0]=kb_qa, [1]=src, [2]=项目根, [3]=portfolio-projects, [4]=仓库根
_HERE = Path(__file__).resolve().parent
PROJECT_ROOT = _HERE.parents[1]


def _env_files() -> tuple[str, ...]:
    """候选 .env 路径：当前目录 → 项目根 → 仓库根（兼容从任意目录启动/测试）。"""
    candidates = [
        Path(".env"),
        PROJECT_ROOT / ".env",
        _HERE.parents[3] / ".env",  # portfolio-projects/
        _HERE.parents[4] / ".env",  # 仓库根 RAG-test/
    ]
    return tuple(str(p) for p in candidates)


class Settings(BaseSettings):
    """应用配置。优先从 .env 读取，缺省值保证开箱即用。"""

    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 智谱 API ──────────────────────────────────────────────
    # 默认空串：允许 import 时不崩；运行前由 cli/api 校验非空。
    zhipuai_api_key: str = Field(default="", description="智谱 API Key，必填")

    embedding_model: str = "embedding-3"
    answer_model: str = "glm-4"          # 回答生成（质量关键）
    rewrite_model: str = "glm-4-flash"   # 查询改写（量大、免费）
    rerank_model: str = "rerank"         # 智谱 cross-encoder 重排
    llm_temperature: float = 0.1         # 知识库问答要克制，低温减少发挥

    # ── 数据层（Ingest）───────────────────────────────────────
    docs_dir: str = str(PROJECT_ROOT / "data" / "docs")
    chroma_path: str = str(PROJECT_ROOT / "chroma_kb")
    collection_name: str = "kb_qa"
    chunk_size: int = 500
    chunk_overlap: int = 80
    embed_batch_size: int = 32           # 智谱 embedding 单请求上限 64 条，留余量

    # ── 检索层（阶段 2）───────────────────────────────────────
    retrieve_k: int = 8                  # 混合召回条数（rerank 前）
    final_k: int = 4                     # 最终送入 prompt 的材料条数
    bm25_weight: float = 0.4             # EnsembleRetriever 权重（与向量检索互补）
    vector_weight: float = 0.6
    enable_rerank: bool = True           # 可开关：评估阶段跑有/无 reranker 对比
    enable_multi_query: bool = False     # 查询改写（默认关，延迟敏感场景不开）

    # ── 服务（阶段 3）─────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8001                     # 避开研究助手的 8000
    sqlite_db_path: str = str(PROJECT_ROOT / "kb_qa.db")
    upload_max_mb: int = 5               # 上传文档大小上限

    # ── 可观测性（LLMOps L01）────────────────────────────────────
    # log_json=True 生产用（机器可消费的 JSON 行）；False 开发期看人类可读文本。
    # log_level 调到 DEBUG 可看检索分词/中间状态（默认 INFO 只打关键业务节点）。
    log_json: bool = True
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """单例配置。lru_cache 保证全进程只读一次 .env。"""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
