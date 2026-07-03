"""
Lesson 02 — 三件套：Models + Prompts + Output Parsers
=====================================================
本课用 LangChain 三件套重写你手写过的「调模型、拼 prompt、解析输出」。

三个实验：
  ① Models + Prompts：from_messages 重写 RAG L05 的防幻觉 prompt（system+human 双角色）
  ② PydanticOutputParser：把"提取员工信息"结构化（对比手写 split）
  ③ with_structured_output：用 Function Calling 一行搞定（对比 Agent L02 的 60 行）

运行：python framework-lessons/02_models_prompts_parsers/code.py
"""
# 消除 langchain-community 的 sunset 警告（L01 README 已讲过背景）
import warnings
warnings.filterwarnings("ignore", message=".*langchain-community.*is being sunset.*")

import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# === LangChain 三件套导入 ===
from langchain_community.chat_models import ChatZhipuAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser, PydanticOutputParser

CHAT_MODEL = "glm-4"          # 想免费可换 "glm-4-flash"

# 演示用的"知识片段"（模拟检索结果，本课重点不在检索，先写死）
SAMPLE_DOCS = [
    "年假：入职满 1 年有 5 天带薪年假，满 3 年有 10 天，满 5 年有 15 天。",
    "每周可远程办公最多 2 个工作日，需直属上级批准。试用期员工不适用远程办公。",
]


# ════════════════════════════════════════════════════════════
# 准备模型
# ════════════════════════════════════════════════════════════
def create_llm():
    """创建 ChatModel —— 对应手写版的 ZhipuAI() 客户端。

    对照 Agent/RAG 课的手写：
        client = ZhipuAI(api_key=...)         # 手写
        resp = client.chat.completions.create(model=..., messages=...)
        text = resp.choices[0].message.content
    框架版：
        llm = ChatZhipuAI(model=..., api_key=...)   # 一次创建
        text = llm.invoke(...)                       # 标准接口，可换模型
    """
    load_dotenv()
    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key or api_key.startswith("xxxx"):
        raise RuntimeError("请先在 .env 里配置 ZHIPUAI_API_KEY")
    return ChatZhipuAI(model=CHAT_MODEL, api_key=api_key)


# ════════════════════════════════════════════════════════════
# 实验①：Models + Prompts —— from_messages 重写防幻觉 prompt
# ════════════════════════════════════════════════════════════
def experiment_1_prompt_template(llm):
    """对比 RAG L05 的手写 f-string 拼接 vs ChatPromptTemplate.from_messages。

    RAG L05 手写：
        prompt = ("你是严谨问答助手...\n" "1. 只能依据材料...\n" f"【材料】\n{context}...")
        resp = client.chat.completions.create(messages=[{"role":"user","content":prompt}])

    框架版：用 from_messages 显式声明 system/human 双角色。
    """
    print("\n" + "═" * 64)
    print("实验①：Models + Prompts —— from_messages 双角色模板")
    print("═" * 64)

    # 用 from_messages 声明角色（对应手写 messages=[{role:system},{role:user}]）
    # 系统消息放"规则"（不变的约束），人类消息放"每次不同的内容"
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是一个严谨的问答助手。只依据材料回答，材料没有就说不知道，不要编造。"),
        ("human", "【材料】\n{context}\n\n【问题】{question}"),
    ])

    # 串成链：prompt | llm | StrOutputParser（提取纯文本）
    chain = prompt | llm | StrOutputParser()

    # 实验 a：问题在材料范围内（应该能答）
    print("\n[1a] 问题在范围内：我工作 4 年，能休几天年假？")
    answer = chain.invoke({
        "context": "\n".join(SAMPLE_DOCS),
        "question": "我工作 4 年，能休几天年假？",
    })
    print(f"🤖 {answer[:120]}")

    # 实验 b：问题超出范围（应该回答"不知道"——防幻觉约束的威力）
    print("\n[1b] 问题超出范围：公司 wifi 密码是多少？（防幻觉约束测试）")
    answer = chain.invoke({
        "context": "\n".join(SAMPLE_DOCS),
        "question": "公司 wifi 密码是多少？",
    })
    print(f"🤖 {answer[:120]}")
    print("\n👉 对比 RAG L05：你手写 f-string + messages dict，这里 from_messages 自动处理角色。")
    print("   防幻觉的'原理'没变（仍是 system 里的约束指令），框架只是让模板可复用、可校验。")


# ════════════════════════════════════════════════════════════
# 实验②：PydanticOutputParser —— 提示词驱动的结构化输出
# ════════════════════════════════════════════════════════════
# ① 用 Pydantic 定义你要的结构（这就是"合同"）
class EmployeeCard(BaseModel):
    """员工信息卡 —— 演示结构化输出的目标结构。"""
    name: str = Field(description="员工姓名")
    years: int = Field(description="工龄（年）")
    skills: list[str] = Field(description="技能列表")


def experiment_2_pydantic_parser(llm):
    """用 PydanticOutputParser 把自由文本解析成结构化对象。

    痛点：手写时模型回 "张三，4年，Python|RAG"，你得 split 再 split，格式一变就崩。
    解法：Pydantic 定义结构 → 框架自动把格式说明塞进 prompt → 自动解析成对象。
    """
    print("\n" + "═" * 64)
    print("实验②：PydanticOutputParser —— 提示词驱动结构化输出")
    print("═" * 64)

    # ② 建解析器，绑定到 EmployeeCard
    parser = PydanticOutputParser(pydantic_object=EmployeeCard)

    # ③ 把"格式说明"自动塞进 prompt
    #    parser.get_format_instructions() 会生成类似：
    #    "The output should be formatted as a JSON instance..."
    #    （这段指令告诉模型按什么 JSON schema 输出）
    prompt = ChatPromptTemplate.from_template(
        "从下面文本中提取员工信息，严格按格式输出。\n\n"
        "文本：{info}\n\n"
        "{format_instructions}"
    ).partial(format_instructions=parser.get_format_instructions())

    # ④ 串成链：prompt | llm | parser
    chain = prompt | llm | parser

    info = "张三在 ACME 公司工作 4 年，擅长 Python 和 RAG 系统。"
    print(f"\n输入文本：{info}")

    result = chain.invoke({"info": info})

    # ⑤ result 不是字符串，是 EmployeeCard 对象！
    print(f"\n✅ 解析结果（类型={type(result).__name__}）：")
    print(f"   name   = {result.name!r}")
    print(f"   years  = {result.years}")
    print(f"   skills = {result.skills}")
    print("\n👉 对比手写：你不用 split、不用 json.loads、不用处理格式漂移。")
    print("   Pydantic 字段类型自动校验（years 自动转 int）。")


# ════════════════════════════════════════════════════════════
# 实验③：with_structured_output —— Function Calling 驱动（重头戏）
# ════════════════════════════════════════════════════════════
def experiment_3_structured_output(llm):
    """用 with_structured_output 一行搞定结构化输出。

    这是 Agent L02 的"框架版"：
        Agent L02 手写（约 60 行）：
          1. 手写 TOOLS_SPEC 的 JSON Schema
          2. tools=TOOLS_SPEC 传给 API
          3. json.loads(tool_call.function.arguments) 手解
        框架版（1 行）：
          structured_llm = llm.with_structured_output(EmployeeCard)
    """
    print("\n" + "═" * 64)
    print("实验③：with_structured_output —— Function Calling 一行搞定")
    print("═" * 64)

    # ⭐ 核心一行：把 Pydantic 模型传进去，得到一个"会返回结构化对象"的模型
    #   背后：框架从 Pydantic 自动生成 JSON Schema → 作为 tool 给模型 →
    #         模型用 Function Calling 返回 → 框架自动解析成 EmployeeCard
    structured_llm = llm.with_structured_output(EmployeeCard)

    # 直接 invoke，连 prompt 都不用写 format_instructions
    info = "李四工作 6 年，擅长 Java 和 Go 语言。"
    print(f"\n输入文本：{info}")
    result = structured_llm.invoke(f"从下面文本提取员工信息：{info}")

    print(f"\n✅ 解析结果（类型={type(result).__name__}）：")
    print(f"   name   = {result.name!r}")
    print(f"   years  = {result.years}")
    print(f"   skills = {result.skills}")

    print("\n👉 对比 Agent L02 的 60 行（手写 TOOLS_SPEC + 手解 tool_calls）：")
    print("   这里 1 行 with_structured_output 就完成了同样的事。")
    print("   但你必须懂 Agent L02 的原理，才知道这 1 行背后：")
    print("     - schema 是怎么从 Pydantic 生成的")
    print("     - 模型走的是 Function Calling 协议")
    print("     - 出错时（模型没按要求返回）该去哪排查")


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def main():
    print("=" * 64)
    print("Lesson 02 — 三件套：Models + Prompts + Output Parsers")
    print("=" * 64)
    print("本课把「调模型、拼 prompt、解析输出」三件手写过的活标准化。")
    print("映射：rag-lessons/05_prompt + agent-lessons/02_function_calling")

    llm = create_llm()

    experiment_1_prompt_template(llm)      # Models + Prompts
    experiment_2_pydantic_parser(llm)      # PydanticOutputParser
    experiment_3_structured_output(llm)    # with_structured_output

    print("\n" + "=" * 64)
    print("✅ 三件套小结：")
    print("   - ChatModel：标准化调模型，可换厂商（ChatZhipuAI ↔ ChatOpenAI）")
    print("   - ChatPromptTemplate：从手拼字符串 → 可校验、可复用的角色模板")
    print("   - OutputParser / with_structured_output：从手解文本 → 结构化对象")
    print("   三者都是 Runnable，用 | 串成 LCEL 链")
    print("=" * 64)


if __name__ == "__main__":
    main()
