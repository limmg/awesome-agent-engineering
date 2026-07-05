# Lesson 07 — 框架级 Agent：Tools + prebuilt Agents

> **本课定位**：把 Agent 的两大痛点——「工具定义」和「Agent 组装」——完全框架化。你 Agent L02 手写了 35 行 `TOOLS_SPEC` JSON Schema、L04 研究了工具描述好坏的影响、L06 手画了 StateGraph 图。本课用 `@tool` 装饰器 + `create_agent` 把这些全部收成几行。
>
> **映射的手写课**：
> - `agent-lessons/02_function_calling`（手写 `TOOLS_SPEC` + `TOOL_REGISTRY` + `execute_function`）
> - `agent-lessons/04_tool_design`（好/差 description 对比、工具选择难题）
> - `agent-lessons/03_react_loop`（L06 已用 StateGraph 重写过，本课用预置版再简化）

---

## 一、痛点回顾：你手写工具时最烦的是什么？

打开 `agent-lessons/04_tool_design/code.py`，看你写的 `TOOLS_SPEC_GOOD`：

```python
{"type": "function", "function": {
    "name": "get_weather",
    "description": "查询指定城市的实时天气。当用户问'XX天气'时使用。不支持查询非城市。",
    "parameters": {"type": "object", "properties": {
        "city": {"type": "string", "description": "城市名，如'北京'"},
        "unit": {"type": "string", "enum": ["摄氏度", "华氏度"], "description": "温度单位"},
    }, "required": ["city"]},
}}
# ... 6 个工具，每个都这样手写，约 50 行
```

**最大的痛点**：你要维护**三份重复的东西**：
1. `get_weather()` —— Python 函数实现
2. `TOOLS_SPEC` 里手写的 JSON Schema（name/description/parameters/required）
3. `TOOL_REGISTRY` 里的 `"get_weather": get_weather` 映射

函数改名了？得改 spec。参数变了？得改 spec。忘了改？运行时才发现。**这三者本质上是同一个东西的三个副本**。

还有 L04 你亲手验证过的：description 写得模糊，模型就会选错工具。所以 description 要写好——但手写 JSON Schema 里写中文 description 又繁琐又容易写错格式。

**`@tool` 装饰器就是为了消灭这个重复。**

---

## 二、`@tool` 装饰器：从函数自动生成 schema

### 手写 vs 框架

```python
# Agent L02/L04 手写（函数 + JSON Schema，两份）：
def get_weather(city: str, unit: str = "摄氏度") -> str:
    ...
TOOLS_SPEC = [{"type":"function","function":{
    "name":"get_weather",
    "description":"查询城市天气...",
    "parameters":{"type":"object","properties":{
        "city":{"type":"string","description":"城市名"},
        "unit":{"type":"string","enum":["摄氏度","华氏度"]}
    },"required":["city"]}
}}]

# 框架版（@tool，一份搞定）：
from langchain_core.tools import tool

@tool
def get_weather(city: str, unit: str = "摄氏度") -> str:
    """查询指定城市的天气。当用户问'XX天气'时使用。

    Args:
        city: 城市名，如北京、上海
        unit: 温度单位，摄氏度或华氏度
    """
    return f"{city}：晴，25度"
```

**`@tool` 做了什么**：它读取函数的**类型注解**（`city: str`、`unit: str = "摄氏度"`）和 **docstring**，**自动生成**等价于你手写的那份 JSON Schema。

### 自动生成的 schema 长什么样？

运行本课 code.py 实验①会打印出来，类似：
```json
{
  "description": "查询指定城市的天气。当用户问'XX天气'时使用...",
  "properties": {
    "city": {"type": "string"},         ← 从 city: str 推断
    "unit": {"default": "摄氏度", "type": "string"}  ← 从默认值推断可选
  },
  "required": ["city"]                   ← 没默认值的自动进 required
}
```

### `@tool` 读取的三个信息源

| 信息 | 来自哪里 | 对应手写 spec 的什么 |
|------|---------|---------------------|
| 函数名 | `def get_weather` | `"name": "get_weather"` |
| 描述 | docstring 第一段 | `"description": "..."` |
| 参数名+类型 | 类型注解 `city: str` | `properties` 里的字段 |
| 是否必填 | 有没有默认值 | `required` 列表 |
| 参数描述 | docstring 的 `Args:` 段 | 各字段的 `description` |

**你只写一份代码（函数本身），schema 自动派生**——改名、改参数、改描述，全在一处改。这就是"消灭三份副本"。

### docstring 是灵魂（呼应 Agent L04）

你在 L04 验证过：description 是工具选择的灵魂。`@tool` 把 description 放在 docstring 里——这更符合 Python 习惯（IDE 会显示 docstring），也更容易写好。

> **L04 的教训仍然适用**：docstring 写模糊，模型一样会选错。`@tool` 只是换了写 description 的位置（从 JSON 移到 docstring），没有降低"写好描述"的重要性。框架不改变原理。

---

## 三、三种定义工具的方式

除了 `@tool` 装饰器，还有两种方式，了解即可：

| 方式 | 写法 | 适用 |
|------|------|------|
| `@tool` 装饰器（推荐）| 装饰一个普通函数 | **绝大多数场景** ✅ |
| `StructuredTool.from_function` | 显式构造，可覆盖 schema | 需要微调自动生成的 schema 时 |
| `StructuredTool` + Pydantic | 用 Pydantic 模型定义参数 | 参数复杂、需严格校验时 |

本课重点用 `@tool`（最常用）。后两种在需要时查文档即可。

### `@tool` 的高级用法（了解）

```python
# 可以覆盖自动生成的名字和返回值解析
@tool("查天气", return_direct=True)
def get_weather(...): ...

# 可以指定更复杂的参数 schema
from pydantic import BaseModel, Field
class WeatherInput(BaseModel):
    city: str = Field(description="城市名")
    unit: str = Field(default="摄氏度")

@tool(args_schema=WeatherInput)
def get_weather(city: str, unit: str = "摄氏度"): ...
```

这些在毕业项目（L09）用到时再细讲。

---

## 四、`create_agent`：一行创建 Agent

这是本课的"重头戏"。L06 你手写了整张 StateGraph（agent 节点 + tools 节点 + 条件边 + 回路）。`create_agent` 把这张图**预置成一个函数**：

```python
# L06 手写（约 15 行构建图）：
builder = StateGraph(MessagesState)
builder.add_node("agent", call_model)
builder.add_node("tools", ToolNode(tools))
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)
builder.add_edge("tools", "agent")
graph = builder.compile()

# 框架版（1 行）：
from langchain.agents import create_agent
agent = create_agent(llm, tools)
```

**`create_agent` 内部做的就是 L06 你手写的那张图**——它就是那张图的"快捷方式"。你已经在 L06 理解了每个节点和边的含义，现在用预置版只是省掉样板代码。

### ⚠️ 一个迁移背景：`create_react_agent` → `create_agent`

你在网上搜到的老教程几乎都用 `from langgraph.prebuilt import create_react_agent`。但在 **LangGraph 1.0+**，这个函数被**迁移**了：

| | 旧（LangGraph 0.x）| 新（LangGraph 1.x，推荐）|
|---|---|---|
| 导入 | `from langgraph.prebuilt import create_react_agent` | `from langchain.agents import create_agent` |
| 名字 | `create_react_agent` | `create_agent` |
| prompt 参数 | `prompt=...` | `system_prompt=...` |
| 状态 | 已弃用（V2.0 移除，会报 DeprecationWarning）| 当前推荐 |

这是 LangChain 1.x 大重构的一部分：把 Agent 相关功能统一收进 `langchain.agents`。**功能完全一样**，只是换了个家。本课代码用新路径，但你遇到老教程时要知道它们是同一个东西。

> 这又是一个"框架在不断迁移"的活例子（和 L01 讲的 `langchain-community` sunset 同理）。

### 带 system prompt（对应 Agent L04 的"好指令"）

```python
agent = create_agent(
    llm,
    tools,
    system_prompt="你是一个严谨的助手。优先使用工具获取信息，不要编造。",  # system 消息
)
```

`system_prompt` 参数注入系统消息——这就是你 Agent L04 强调的"用 system prompt 约束 Agent 行为"的框架版。

### 何时用预置 / 何时手写图？

| 场景 | 选择 | 理由 |
|------|------|------|
| 标准 ReAct（调工具→回答）| `create_agent` | 够用，省代码 |
| 需要自定义节点（如加"自我反思""审查"步骤）| 手写 StateGraph | 预置版改不了流程 |
| 需要并行/子图（L09 毕业项目）| 手写 StateGraph | 复杂图结构 |

> **关键认知**：`create_agent` 不是魔法，它就是 L06 那张图的封装。你在 L06 懂了图的原理，才知道预置版"背后是什么""什么时候不够用要手写"。这就是先学原理再学框架的价值。

---

## 五、一个真实细节：LLM 用工具时会犯错

本课 code.py 会演示一个真实现象：让 GLM 算 `2的10次方`，模型可能传 `2^10` 给 calculator——但在 Python 里 `^` 是**异或**不是乘方，结果会是 8 而非 1024。

这**不是框架的 bug**，是 LLM 对工具参数理解的局限。解决方式：
- 在工具 docstring 里写清楚支持的语法（如"用 `**` 表示乘方"）
- 或加一个专门的 `power` 工具

> 这个细节很有教学价值：**框架帮你把工具接上了，但工具能不能被正确使用，仍取决于 description 的质量**——又回到 Agent L04 的核心教训。

---

## 六、手写 vs 框架：终极对比

把 Agent L02 + L04 + L06 的手写工作量和框架版并排：

| 环节 | 手写（Agent L02+L04）| 框架版（本课）|
|------|---------------------|--------------|
| 工具定义 | 函数 + TOOLS_SPEC + TOOL_REGISTRY（三份）| `@tool`（一份）|
| 工具执行 | `execute_function` 调度器 | ToolNode 自动 |
| Agent 组装 | L06 的 StateGraph（15行）| `create_agent`（1行）|
| 循环/分支 | for + if | 图内部自动 |
| **总代码量** | ~150 行 | ~20 行 |

**但原理你全懂了**：schema 怎么来的（L04）、工具怎么调度（L02）、图怎么运转（L06）。框架只是把这些原理封装得更省事。

---

## 七、本课代码

`code.py` 三个实验：

1. **`@tool` 自动生成 schema**：打印生成的 JSON，对比 Agent L04 手写的 TOOLS_SPEC
2. **`create_agent` 一行建 Agent**：对比 L06 手写的整张图
3. **真实细节**：LLM 用 `2^10` 算错的现象，体会"description 仍是灵魂"

---

## 八、小结 & 下节预告

✅ 现在你应该明白：
- `@tool` 从函数的类型注解 + docstring 自动生成 schema（消灭三份副本）
- `create_react_agent` 是 L06 那张图的预置封装（一行建 Agent）
- description 仍是灵魂（框架换了位置，没降低重要性）
- 何时用预置 / 何时手写图

🔜 **L08** 进入 LangGraph 的杀手锏：状态持久化（Checkpointer）+ 人机协作（Human-in-the-loop）。这是手写循环几乎做不到、而图天然擅长的事——对应你 Agent L05 的记忆主题，但强大得多。
