# Lesson 02 — 三件套：Models + Prompts + Output Parsers

> **本课定位**：L01 你见识了 LCEL 管道的省事。这节深入管道里**最核心的三个积木**——把"调模型、拼提示词、解析输出"这三件你反复手写过的活，标准化成可复用、可组合、可校验的对象。
>
> **映射的手写课**：
> - `rag-lessons/05_prompt`（你手写 f-string 拼 prompt + 手写 `chat()` / `chat_stream()`）
> - `agent-lessons/02_function_calling`（你手写 `TOOLS_SPEC` JSON Schema + 手解 `tool_call.function.arguments`）

---

## 一、为什么要把这三件事"对象化"？

回顾你 RAG L05 里写的代码：

```python
def build_safe_prompt(question, docs):
    context = "\n\n".join(f"【材料{i+1}】{doc}" for i, doc in enumerate(docs))
    return (
        "你是一个严谨的问答助手。请遵守以下规则：\n"
        "1. 只能根据下面提供的材料回答...\n"
        f"【材料】\n{context}\n\n"
        f"【问题】{question}"
    )   # ← 一个字符串

answer = chat(client, build_safe_prompt(question, docs))   # ← 返回一个字符串
```

这里有三个问题：
1. **Prompt 是一坨字符串**：换个用法就得重拼，没法复用、没法校验变量有没有漏填。
2. **调模型散落各处**：`chat()` 和 `chat_stream()` 是两个独立函数，逻辑重复（都是发 messages）。
3. **输出是自由文本**：模型回 `"张三，4年，会Python"`，你要自己写正则/`split` 才能提取出结构化字段。

LangChain 的三件套分别解决这三件事：

| 你的痛点 | LangChain 的解法 | 这个对象叫 |
|---------|-----------------|-----------|
| Prompt 是字符串，难复用 | 把模板变成**带占位符的对象** | `ChatPromptTemplate` |
| 调模型散落各处 | 统一成一个**标准接口对象** | `ChatModel`（如 `ChatZhipuAI`） |
| 输出是自由文本，难提取 | 把"文本→结构化对象"也变成对象 | `OutputParser` |

**最妙的是**：这三个对象都是 `Runnable`，天然能用 `|` 串成 LCEL 链（L01 已见识）。

---

## 二、积木一：Models —— "调模型"被标准化

你在前两门课里调模型的写法是：

```python
# 手写（zhipuai SDK）
response = client.chat.completions.create(model="glm-4", messages=[...])
answer = response.choices[0].message.content
```

LangChain 把它包成 `ChatZhipuAI` 对象：

```python
# 框架版
llm = ChatZhipuAI(model="glm-4", api_key=...)
answer = llm.invoke("你好")           # 直接传字符串也行
answer = llm.invoke([msg1, msg2])     # 传 messages 列表也行
```

### 为什么这是大事？—— 可替换性

`ChatZhipuAI` 和 `ChatOpenAI`、`ChatAnthropic` **实现了同一个接口**（都继承 `BaseChatModel`）。你的 LCEL 链里写的是 `prompt | llm | parser`，换模型只改 `llm =` 那一行，**链的其他部分一行不用动**。

```
prompt | ChatZhipuAI(...)  | parser   # 用智谱
prompt | ChatOpenAI(...)    | parser   # 换成 OpenAI，链不变
prompt | ChatAnthropic(...) | parser   # 换成 Claude，链不变
```

回顾你手写时：换 SDK 等于重写 `chat()` 函数（messages 结构、response 字段名全不同）。框架把这层差异抹平了。

> ⚠️ 一个细节：`ChatZhipuAI` 直接 `.invoke("字符串")` 时，框架会自动把它包成一条 `HumanMessage`。这是 LangChain 对所有 ChatModel 的统一约定，让你写 demo 时更省事。

---

## 三、积木二：Prompts —— 从手拼字符串到模板对象

### 1. `from_template` —— 单条模板（对应 RAG L05 的 f-string）

```python
# 你手写过的（RAG L05）：
prompt = f"材料：\n{context}\n\n问题：{question}"

# 框架版：
prompt = ChatPromptTemplate.from_template(
    "材料：\n{context}\n\n问题：{question}"
)
# 用的时候：
filled = prompt.invoke({"context": "...", "question": "..."})
```

**看起来差不多，但有三个实质区别**：

1. **变量校验**：`{context}` 写错了成 `{contxt}`，`.invoke()` 时立刻报错告诉你缺哪个变量。手写 f-string 是"运行时 NameError 或静默错误"。
2. **可复用**：同一个模板对象可以被多条链共享。
3. **它是 Runnable**：能接进 `|` 管道，自动接收上一步的 dict。

### 2. `from_messages` —— 多角色模板（对应手写 `messages=[{role:...},{role:...}]`）

这是更贴近真实生产的写法。回忆你 Agent 课里手写 messages：

```python
# 手写（Agent L02）：
messages = [
    {"role": "user", "content": user_question},
]
messages.append({"role": "tool", "tool_call_id": ..., "content": result})
```

框架版用 `from_messages` 显式声明每个角色：

```python
prompt = ChatPromptTemplate.from_messages([
    ("system", "你是一个严谨的问答助手。只依据材料回答，没有就说不知道。"),
    ("human", "【材料】\n{context}\n\n【问题】{question}"),
])
```

**`system` / `human` / `ai`** 这些字符串对应消息角色。框架自动把它们渲染成 `SystemMessage` / `HumanMessage` 对象，省去你手写 `{"role": ..., "content": ...}` 字典。

> 这就是你在 RAG L05 里 `messages=[{"role":"user","content":prompt}]` 的框架版——只是把"手拼字典"升级成"声明角色模板"。

### 3. `.partial()` —— 预填一部分变量

```python
prompt = ChatPromptTemplate.from_template("你好{name}，今天{day}天气如何？")
# 还没到运行时，先固定 name
prompt = prompt.partial(name="张三")
# 之后只需要给 day
prompt.invoke({"day": "周一"})
```

工程上常用：把"系统级常量"提前 `.partial()` 好，把"每次请求才有的变量"留给运行时。L05 输出解析器那节会用到。

---

## 四、积木三：Output Parsers —— 从自由文本到结构化对象

这是三件套里**含金量最高**的部分，直接对应你 Agent L02 手解 `tool_calls` 的痛点。

### 痛点回顾

你在 Agent L02 里要拿模型返回的结构化数据，得这样：

```python
# 手解（Agent L02）：
func_args = json.loads(tool_call.function.arguments)   # 手动 json.loads
# 还得处理 JSONDecodeError 兜底
```

即便不用 function calling，只要想让模型返回"员工信息卡"，你手写也得：
```python
# 假设模型回 "张三，4年，Python|RAG"
name, years, skills = answer.split("，")   # 脆弱的 split
skills = skills.split("|")                  # 又一个 split
```

一旦模型格式稍微变一下（多个空格、换个标点），你的 split 就崩。

### 解法一：`PydanticOutputParser`（提示词驱动）

思路：用 **Pydantic** 定义你要的结构，框架**自动把结构说明拼进 prompt**，让模型按 JSON 格式输出，然后**自动解析**回 Pydantic 对象。

```python
from pydantic import BaseModel, Field

# ① 用 Pydantic 定义结构（字段 + 描述）
class EmployeeCard(BaseModel):
    name: str = Field(description="员工姓名")
    years: int = Field(description="工龄年数")
    skills: list[str] = Field(description="技能列表")

# ② 建解析器
parser = PydanticOutputParser(pydantic_object=EmployeeCard)

# ③ 把"格式说明"自动塞进 prompt（这是魔法所在）
prompt = ChatPromptTemplate.from_template(
    "从下面文本提取员工信息。\n{info}\n\n{format_instructions}"
).partial(format_instructions=parser.get_format_instructions())
#                   ↑ 这一行会生成一段类似
# "请输出 JSON，格式如下：{\"name\": str, \"years\": int, ...}" 的指令

# ④ 串成链
chain = prompt | llm | parser
result = chain.invoke({"info": "张三工作4年，会Python和RAG"})
# result 是 EmployeeCard 对象，不是字符串！
result.name    # "张三"
result.years   # 4
result.skills  # ["Python", "RAG"]
```

**对比你手写**：不再需要 `split`、不再需要手拼 JSON Schema、解析失败时框架会报清晰的校验错误。

### 解法二：`with_structured_output()`（Function Calling 驱动）⭐

这是**更现代、更可靠**的方式，也是本课的"重头戏"——它直接用上了你 Agent L02 学过的 **Function Calling**，但把"手写 TOOLS_SPEC + 手解 tool_calls"全自动化了。

```python
# Agent L02 你手写过的（约 60 行）：
#   1. 手写 TOOLS_SPEC 的 JSON Schema
#   2. tools=TOOLS_SPEC 传给 API
#   3. json.loads(tool_call.function.arguments) 手解参数

# 框架版（1 行）：
structured_llm = llm.with_structured_output(EmployeeCard)
result = structured_llm.invoke("李四工作6年，会Java和Go")
# result 直接是 EmployeeCard 对象
```

**它在背后做了什么**：
1. 从 Pydantic 模型**自动生成** JSON Schema（省掉你 Agent L02 手写 TOOLS_SPEC）
2. 把 schema 作为 tool 传给模型（用 Function Calling 协议）
3. 模型返回 `tool_call`，框架**自动解析** arguments 成 Pydantic 对象（省掉你手 `json.loads`）

> 这正是「框架把你 Agent L02 的 60 行收成 1 行」的最好例子。但你必须懂 Agent L02 的原理，才知道这 1 行背后发生了什么、出错时怎么排查——这就是本课程"手写→框架"对比的价值。

### 两种解法怎么选？

| | `PydanticOutputParser` | `with_structured_output` |
|---|---|---|
| 原理 | 在 prompt 里要求输出 JSON 文本 | 用 Function Calling 协议 |
| 可靠性 | 依赖模型守规矩（偶尔会出错） | 协议级保证，更可靠 |
| 依赖 | 任何模型都行 | 模型需支持 function calling（GLM 支持 ✅）|
| 推荐 | 模型不支持 FC 时的退路 | **首选** |

> 我们已实测：智谱 GLM 的 `with_structured_output` 工作正常（code.py 会演示）。

---

## 五、三件套合体：一条结构化输出链

把三件套用 `|` 串起来，就是一条"输入文本 → 结构化对象"的完整链：

```python
chain = prompt | llm | parser      # PydanticOutputParser 方案
# 或
chain = prompt | llm.with_structured_output(EmployeeCard)   # FC 方案
```

这就是 L01 学的 LCEL 管道，只是现在每一节你都知道"里面装的是什么对象"了。

---

## 六、本课代码

`code.py` 三个实验，每个都做「手写 vs 框架」对比：

1. **Models + Prompts**：用 `from_messages` 重写 RAG L05 的防幻觉 prompt（system + human 双角色）
2. **PydanticOutputParser**：把"提取员工信息"结构化（对比手写 split）
3. **with_structured_output**：用 Function Calling 一行搞定结构化（对比 Agent L02 的 60 行）

---

## 七、小结 & 下节预告

✅ 现在你应该明白：
- Models / Prompts / Parsers 三个对象分别解决什么痛点
- `from_messages` 怎么把手拼 messages 升级成角色模板
- 两种结构化输出方案的区别（prompt 驱动 vs Function Calling 驱动）
- `with_structured_output` 如何把 Agent L02 的 60 行收成 1 行

🔜 **L03** 进入数据层：Loaders + Splitters + VectorStores——把 RAG 的"文档进库"环节工程化，对应你 RAG L03（向量库）和 L04（切块）。其中 `RecursiveCharacterTextSplitter` 你其实已经在 RAG L04 用过了！
