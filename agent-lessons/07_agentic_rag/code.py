"""
L07 — Agentic RAG：Agent + RAG
================================
把 RAG 包装成一个工具，让 Agent 自主决定要不要检索。
直接复用 RAG 课程的 embedding + Chroma 检索逻辑，知识闭环。

运行：python agent-lessons/07_agentic_rag/code.py
"""
from __future__ import annotations

import json
import os

import chromadb
from dotenv import load_dotenv
from zhipuai import ZhipuAI

EMBEDDING_MODEL = "embedding-3"
CHAT_MODEL = "glm-4"  # 想免费可换 "glm-4-flash"
COLLECTION_NAME = "agent07_kb"
CHROMA_PATH = "./chroma_db_agent07"
DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "sample_docs")


def create_client() -> ZhipuAI:
    load_dotenv()
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key or api_key.startswith("xxxx"):
        raise RuntimeError("请先在 .env 里配置 ZHIPUAI_API_KEY")
    return ZhipuAI(api_key=api_key)


def embed(client: ZhipuAI, texts: list[str]) -> list[list[float]]:
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]


# ════════════════════════════════════════════════════════════
# 建知识库（复用 RAG 课程的文档）
# ════════════════════════════════════════════════════════════
def build_knowledge_base(client: ZhipuAI):
    """加载 data/sample_docs 下的 md 文件，建 Chroma 向量库。

    这里简化处理：每个文件作为一整条文档存入（不切块，因为本课重点在 Agent 不在 chunking）。
    """
    docs = []
    metadatas = []
    for fname in os.listdir(DOCS_DIR):
        if not fname.endswith(".md"):
            continue
        with open(os.path.join(DOCS_DIR, fname), "r", encoding="utf-8") as f:
            # 按段落切分（简易切块）
            content = f.read()
            for chunk in content.split("\n\n"):
                chunk = chunk.strip()
                if len(chunk) > 10:  # 过滤太短的
                    docs.append(chunk)
                    metadatas.append({"source": fname})

    embeddings = embed(client, docs)
    db = chromadb.PersistentClient(path=CHROMA_PATH)
    try:
        db.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    col = db.get_or_create_collection(name=COLLECTION_NAME)
    col.add(
        documents=docs,
        embeddings=embeddings,
        metadatas=metadatas,
        ids=[f"doc_{i}" for i in range(len(docs))],
    )
    print(f"✅ 知识库已就绪：{col.count()} 个文档块")
    return col


# ════════════════════════════════════════════════════════════
# 工具 1：RAG 检索（这就是把 RAG 包装成工具！）
# ════════════════════════════════════════════════════════════
# 全局变量存 collection（教学简化，生产环境用类封装）
_KB_COLLECTION = None


def search_knowledge_base(query: str) -> str:
    """在知识库里搜索相关信息。直接复用 RAG 课程的检索逻辑。

    这就是 Agentic RAG 的核心——RAG 变成了 Agent 的一个工具。
    """
    global _KB_COLLECTION
    if _KB_COLLECTION is None:
        return "错误：知识库未初始化"

    # 这里需要 client 来做 embedding，用一个临时方案：预存
    query_emb = _QUERY_EMBEDDINGS.get(query)
    if query_emb is None:
        return "错误：无法向量化查询"
    results = _KB_COLLECTION.query(query_embeddings=[query_emb], n_results=3)
    docs = results["documents"][0]
    if not docs:
        return "没找到相关内容"
    return "\n---\n".join(docs[:3])


# 预计算查询向量用的缓存（避免工具内部依赖 client）
_QUERY_EMBEDDINGS = {}


def precompute_query_embedding(client: ZhipuAI, query: str):
    """预先把 query 向量化并存起来，供 search_knowledge_base 使用。

    这是一个教学简化：真实实现里，工具函数应该能直接拿到 client。
    生产环境通常把工具做成类，self.client 作为属性。
    """
    _QUERY_EMBEDDINGS[query] = embed(client, [query])[0]


# ════════════════════════════════════════════════════════════
# 工具 2、3：计算器、天气
# ════════════════════════════════════════════════════════════
def calculator(expression: str) -> str:
    try:
        allowed = set("0123456789+-*/.() ")
        if not all(c in allowed for c in expression):
            return "错误：表达式包含非法字符"
        return str(eval(expression))
    except Exception as e:
        return f"计算错误：{e}"


def get_weather(city: str) -> str:
    weather_map = {"北京": ("晴", 25), "上海": ("多云", 28), "广州": ("雨", 30)}
    if city not in weather_map:
        return f"没有 {city} 的数据。支持：{list(weather_map.keys())}"
    cond, t = weather_map[city]
    return f"{city}：{cond}，{t}°C"


TOOL_REGISTRY = {
    "search_knowledge_base": search_knowledge_base,
    "calculator": calculator,
    "get_weather": get_weather,
}

TOOLS_SPEC = [
    {"type": "function", "function": {
        "name": "search_knowledge_base",
        "description": "在公司知识库里搜索相关信息。当用户问公司制度、政策、流程（如年假、报销、IT制度等）时使用。如果用户问的是数学计算、天气或闲聊，不要用这个工具。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "搜索关键词或问题"},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "calculator",
        "description": "计算数学表达式。需要精确计算加减乘除时使用。",
        "parameters": {"type": "object", "properties": {
            "expression": {"type": "string", "description": "数学表达式，如 '12*34'"},
        }, "required": ["expression"]},
    }},
    {"type": "function", "function": {
        "name": "get_weather",
        "description": "查询城市天气。当用户问某城市天气/气温时使用。",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string", "description": "城市名"},
        }, "required": ["city"]},
    }},
]


def execute_function(name: str, args: dict) -> str:
    if name not in TOOL_REGISTRY:
        return f"错误：工具 '{name}' 不存在"
    try:
        return str(TOOL_REGISTRY[name](**args))
    except Exception as e:
        return f"工具失败：{e}"


# ════════════════════════════════════════════════════════════
# Agentic RAG Agent（自主决定要不要检索）
# ════════════════════════════════════════════════════════════
def run_agentic_rag(client: ZhipuAI, question: str, max_steps: int = 5) -> str | None:
    """Agentic RAG：Agent 自主决定用什么工具（包括 RAG 检索）。"""
    # 预计算可能的检索查询向量
    precompute_query_embedding(client, question)

    messages = [{"role": "user", "content": question}]
    print(f"\n🙋 用户：{question}")

    for step in range(1, max_steps + 1):
        response = client.chat.completions.create(
            model=CHAT_MODEL, messages=messages, tools=TOOLS_SPEC, tool_choice="auto"
        )
        msg = response.choices[0].message

        if msg.tool_calls:
            messages.append(msg.model_dump())
            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                # 如果 Agent 要检索，预计算它的 query 向量
                if name == "search_knowledge_base":
                    precompute_query_embedding(client, args.get("query", ""))
                result = execute_function(name, args)
                tool_label = {"search_knowledge_base": "📚 检索知识库", "calculator": "🔧 计算", "get_weather": "🌤️ 天气"}.get(name, "🔧")
                print(f"  {tool_label}：{name}({args}) → {result[:60]}")
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        else:
            print(f"  💬 回答：{msg.content[:100]}")
            return msg.content
    return None


# ════════════════════════════════════════════════════════════
# 对比用：传统 RAG（无脑检索）
# ════════════════════════════════════════════════════════════
def traditional_rag(client: ZhipuAI, question: str) -> str:
    """传统 RAG：不管什么问题，都去检索，再生成。"""
    precompute_query_embedding(client, question)
    print(f"\n🙋 用户：{question}")
    print("  📚 [传统RAG] 无脑检索知识库...")
    retrieved = search_knowledge_base(question)
    print(f"  📚 检索结果：{retrieved[:60]}...")

    prompt = f"根据以下材料回答问题，材料没有就说不知道：\n{retrieved}\n\n问题：{question}"
    resp = client.chat.completions.create(
        model=CHAT_MODEL, messages=[{"role": "user", "content": prompt}]
    )
    answer = resp.choices[0].message.content
    print(f"  💬 回答：{answer[:100]}")
    return answer


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def main():
    global _KB_COLLECTION

    print("=" * 60)
    print("L07 — Agentic RAG：Agent + RAG")
    print("=" * 60)

    client = create_client()
    _KB_COLLECTION = build_knowledge_base(client)

    # === Agentic RAG：面对不同问题自主决策 ===
    print("\n\n" + "═" * 60)
    print("实验 1：Agentic RAG（Agent 自主决定要不要检索）")
    print("═" * 60)

    questions = [
        "公司年假有几天？",          # 应该检索知识库
        "1+1 等于几？",              # 应该调计算器，不碰知识库
        "你好，请介绍一下自己。",     # 应该直接回答，不调任何工具
        "北京天气怎么样？",          # 应该调天气工具
    ]

    for q in questions:
        run_agentic_rag(client, q)

    # === 对比传统 RAG：无脑检索的尴尬 ===
    print("\n\n" + "═" * 60)
    print("实验 2：对比传统 RAG（无脑检索）")
    print("═" * 60)
    print("（同样的问题，传统 RAG 每次都去翻文档——包括不需要翻的）\n")

    traditional_rag(client, "1+1 等于几？")  # 传统 RAG 会去检索年假制度，荒谬
    traditional_rag(client, "你好，请介绍一下自己。")

    print("\n\n" + "═" * 60)
    print("对比要点：")
    print("  Agentic RAG：按需检索，不碰不需要的工具——聪明且省。")
    print("  传统 RAG：无脑检索，问'1+1'也去翻年假制度——浪费且可能干扰。")
    print("  💡 RAG 不是独立系统，而是 Agent 工具箱里的一把扳手。")
    print("=" * 60)


if __name__ == "__main__":
    main()
