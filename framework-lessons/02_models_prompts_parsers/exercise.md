# Lesson 02 练习 — 三件套：Models + Prompts + Parsers

> 动手做才能真懂。重点在第 3、4 题（结构化输出，面试常考）。

---

## 练习 1：对比 from_messages 和手写 messages（10 分钟）

打开 `rag-lessons/05_prompt/code.py`，看 `section_citation` 里手写的 prompt。

把它改写成 `ChatPromptTemplate.from_messages([...])` 的形式（system + human 双角色），在本课 `code.py` 的基础上写一小段测试代码跑通。

**思考**：
- 手写版和框架版，哪个改"system 指令"更方便？
- 如果你要在 system 里加一句"回答用 markdown"，两种写法分别怎么改？

---

## 练习 2：理解 `.partial()`（5 分钟）

`code.py` 实验②里用了 `.partial(format_instructions=...)`。回答：

1. 为什么不直接把 `format_instructions` 放进 `.invoke({...})` 的字典里？
2. 什么场景下 `.partial()` 比运行时传参更合适？（提示：想想"哪些变量是固定的、哪些是每次请求才有的"）

---

## 练习 3：扩展 EmployeeCard（核心练习，15 分钟）

给 `EmployeeCard` 加两个字段：
- `department: str`（部门）
- `is_manager: bool`（是否管理者）

然后分别用**两种方式**让 GLM 提取：

输入文本：`"王五是研发部技术总监，管理 10 人团队，工作 8 年，擅长架构设计"`

预期输出类似：
```
EmployeeCard(name='王五', years=8, department='研发部', is_manager=True, skills=['架构设计'])
```

要求：
1. 用 `PydanticOutputParser` 方式实现一遍
2. 用 `with_structured_output` 方式实现一遍
3. 对比两种方式的代码量

**观察**：`bool` 字段模型能正确推断吗？如果文本里没明说"是管理者"，模型会怎么处理？

---

## 练习 4：两种结构化输出的边界测试（关键认知，10 分钟）

故意给一段**信息不完整**的文本：
`"赵六是个员工"`（没说工龄、没说技能）

分别用两种方式提取，观察：
1. `PydanticOutputParser` 会怎样？（可能报错，因为 years 是必填 int）
2. `with_structured_output` 会怎样？

然后**修复**：把 `years` 和 `skills` 改成**可选字段**（`Optional[int] = None`、`Optional[list[str]] = None`），重跑。

> 这是面试高频考点：**结构化输出如何处理信息缺失**。Pydantic 的 `Optional` + `default` 是标准解法。

提示：
```python
from typing import Optional
class EmployeeCard(BaseModel):
    name: str
    years: Optional[int] = None
    skills: Optional[list[str]] = None
```

---

## 练习 5：换模型验证"可替换性"（可选，需有其他 API Key）

如果你有 OpenAI 或其他模型的 Key，把 `create_llm()` 里的 `ChatZhipuAI` 换成对应的 ChatModel（如 `ChatOpenAI`），**其余代码一行不改**，验证三件套的链是否能照跑。

> 没有 Key 也没关系，理解这个概念即可：这就是 `BaseChatModel` 统一接口的价值。

---

## 思考题（不写代码）

1. **`with_structured_output` 和 `PydanticOutputParser`，什么时候选哪个？** 想一个必须用后者的场景。

2. **`with_structured_output` 背后用的是 Function Calling。** 回顾 Agent L02，模型返回的 `tool_call.function.arguments` 是什么类型？框架要把它变成 Pydantic 对象，中间做了什么？

3. **为什么 LangChain 要把 Prompt 也设计成 Runnable（能 `.invoke()`）？** 如果 Prompt 只是普通字符串，LCEL 的 `|` 管道还能成立吗？

---

## 完成标志

- [ ] 能说清三件套分别解决什么痛点
- [ ] 跑通 `from_messages` 双角色模板
- [ ] 用两种方式实现结构化输出，理解它们原理不同
- [ ] 会处理结构化输出的"字段缺失"问题（练习 4）
- [ ] 能口述 `with_structured_output` 背后的 Function Calling 流程

下一课 [L03](../03_documents_splitter_vectorstore/) 进入数据层：Loaders + Splitters + VectorStores。
