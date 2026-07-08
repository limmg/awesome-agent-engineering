# ── Dockerfile：多阶段构建，产出精简生产镜像 ──────────────
# 用法：docker build -t research-assistant .
#       docker run -p 8000:8000 -v $(pwd)/data:/app/data research-assistant

# ---- 构建阶段：装依赖（利用 layer cache）----
FROM python:3.11-slim AS builder

# 系统依赖（sqlite3 头文件等；slim 基础镜像精简了 build-essential）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# 先只拷 requirements，利用 Docker layer cache（依赖不变时不重装）
COPY requirements.txt .
# 装到独立目录，便于多阶段复制
RUN pip install --user --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

# ---- 运行阶段：精简镜像 ----
FROM python:3.11-slim

# 从构建阶段复制已装的依赖
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 复制项目源码
COPY src/ ./src/
COPY api/ ./api/
COPY static/ ./static/
COPY cli.py pytest.ini ./

# 数据目录（sqlite db 持久化挂载点）
RUN mkdir -p /app/data
ENV SQLITE_DB_PATH=/app/data/research_assistant.db

# 健康检查（容器编排用）
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

EXPOSE 8000

# 启动 FastAPI 服务（生产用 gunicorn 多 worker 也可，此处单 worker 够演示）
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
