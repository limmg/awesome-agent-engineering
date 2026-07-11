"""locust 版压测脚本（LLMOps L11 生产对照）。

自实现版（run_loadtest.py）零依赖够用；locust 提供可视化 Web 面板 + 分布式压测，
适合正式容量评估。两者逻辑等价，理解了 run_loadtest 再用 locust 是换皮。

用法（需先装 locust：pip install locust）：
    locust -f loadtest/locustfile.py --host http://localhost:8001
    → 打开 http://localhost:8089 配并发数开始压测
    # 无头模式（CI 用）：
    locust -f loadtest/locustfile.py --host http://localhost:8001 \
        --headless -u 10 -r 2 --run-time 60s
"""
from __future__ import annotations

import os

from locust import HttpUser, between, task


class KbQaUser(HttpUser):
    """模拟一个 kb-qa 用户：间歇性地问问题。

    -u N：N 个并发用户；-r R：每秒新增 R 个用户
    wait_time：每个用户两次请求间的思考时间（模拟真人节奏）
    """
    wait_time = between(1, 3)  # 用户思考 1~3 秒再问下一个

    # L04 鉴权：从环境变量读 key（locust 启动时 export API_KEY=xxx）
    _api_key = os.getenv("API_KEY", "")

    def on_start(self):
        """每个虚拟用户启动时设默认头（鉴权）。"""
        if self._api_key:
            self.client.headers.update({"Authorization": f"Bearer {self._api_key}"})

    @task
    def ask(self):
        """问一个问题。/api/ask 是 SSE，locust 会等完整响应。"""
        questions = [
            "云帆科技试用期多久",
            "年假有几天",
            "病假工资怎么算",
            "出差报销限额多少",
            "远程办公可以吗",
        ]
        import random
        q = random.choice(questions)
        with self.client.post(
            "/api/ask",
            json={"question": q},
            name="/api/ask",
            catch_response=True,
        ) as resp:
            # SSE：只要状态码 200 就算成功（流式内容 locust 不解析）
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 429:
                # 限流是预期的（压到瓶颈），标记为预期失败不上报错误率
                resp.failure("429 rate limited (expected at capacity)")
            else:
                resp.failure(f"unexpected status {resp.status_code}")
