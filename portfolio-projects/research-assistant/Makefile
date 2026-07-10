# ── Makefile：常用命令快捷方式 ────────────────────────────
# 用法：make <target>（Windows 下需 make 工具，或直接看下面的命令）
#
# 无 make 环境也可直接用对应命令（见每个 target 的注释）。

PYTHON ?= python

.PHONY: help install run cli test docker docker-up docker-down clean lint

help:  ## 显示所有命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## 安装依赖（pip install -r requirements.txt）
	$(PYTHON) -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

run:  ## 启动 FastAPI 服务（uvicorn api.main:app --reload）
	$(PYTHON) -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

cli:  ## CLI 运行（默认主题；make cli T="主题" 可指定）
	$(PYTHON) cli.py "$(T)"

test:  ## 跑测试（pytest -v）
	$(PYTHON) -m pytest -v

docker:  ## 构建 Docker 镜像
	docker build -t research-assistant .

docker-up:  ## docker compose 启动（后台）
	docker compose up -d

docker-down:  ## docker compose 停止
	docker compose down

clean:  ## 清理临时文件（__pycache__、测试 db）
	-find . -type d -name __pycache__ -exec rm -rf {} +
	-rm -f research_assistant.db *.db
	-rm -rf .pytest_cache

lint:  ## 语法检查（py_compile 所有源码）
	@$(PYTHON) -c "import py_compile, glob; [py_compile.compile(f, doraise=True) for f in glob.glob('src/**/*.py', recursive=True) + glob.glob('api/*.py') + ['cli.py']]; print('lint OK')"
