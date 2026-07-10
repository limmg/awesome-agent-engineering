"""ragas 0.4.3 兼容补丁。

坑：ragas 0.4.3 硬 import `langchain_community.chat_models.vertexai`，
但 langchain-community sunset 后 0.4.2 起删掉了该模块，import ragas 直接崩。
ragas 只拿 ChatVertexAI 做 isinstance 分支判断、从不实例化，
所以注入一个空壳 stub 即可安全绕过（已真实验证）。

用法：在任何 `import ragas` 之前 `from kb_qa.ragas_compat import install_vertexai_stub; install_vertexai_stub()`。
"""
from __future__ import annotations

import sys
import types

_MODULE_NAME = "langchain_community.chat_models.vertexai"


def install_vertexai_stub() -> None:
    """幂等注入 vertexai stub 模块。"""
    if _MODULE_NAME in sys.modules:
        return

    stub = types.ModuleType(_MODULE_NAME)

    class ChatVertexAI:  # noqa: D401 —— 仅供 ragas isinstance 判断的空壳
        """Stub：真实类已随 langchain-community sunset 移除。"""

    stub.ChatVertexAI = ChatVertexAI
    sys.modules[_MODULE_NAME] = stub
