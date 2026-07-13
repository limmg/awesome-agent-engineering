# Lesson 09 — 落地：research-assistant 长出「手」

> 本课目标：**把 L01–L07 成果封成生产化 async `browser_tool.py` 接进 researcher。工具分层（search 快浅便宜 / browse 慢深贵）+ 路由判断 + 降级链（browse 失败回退 search）+ L07 安全规则默认开。enable_browser 默认关，全 121 测试始终绿。**

学完你能回答：**「怎么把 GUI agent 能力落地到生产系统而不破坏现有功能？」**——答案是分层（search/browse 各司其职）、降级链（browse 失败不阻塞研究）、默认关 + 单例懒加载（不破坏现有测试）、安全规则内置默认开。

---

## 0. 从课程产物到生产工具

L01–L08 在 `gui-agent-lessons/` 里手写了 BrowserSession / 观察空间 / 动作 DSL / 可靠性层 / 安全层 / mini-benchmark——它们是**教学版**（sync API、mock LLM、独立可跑）。L09 把它们**封成生产工具**接进 research-assistant：

```
教学版（gui-agent-lessons/）          生产版（research-assistant/src/）
─────────────────────              ──────────────────────────
BrowserSession (sync)       →      BrowserTool (async)        L01
page_to_obs                  →     extract_from_page          L02
动作 DSL + 循环              →     简化：直接选择器提取        L03/L04
ReliabilityLayer             →     超时兜底 + 重试预算          L06
SecurityLayer                →     allowlist + 敏感确认(默认开) L07
                            →     Evidence 证据记录            L10 预留
```

**为什么简化**：research-assistant 的 researcher 不需要完整 agent 循环（它有自己的 LangGraph 循环）。它需要的是「给一个 URL，提取结构化证据」这个**工具**——所以 L09 把 L01-L07 浓缩成一个 `BrowserTool` 类，保留核心能力（导航/提取/安全/降级），去掉教学用的循环（那是 LangGraph 的活）。

> 🎯 **核心认知**：落地不是把课程代码原样搬过去，是**抽象成生产接口**。课程教原理（手写循环），落地用框架（LangGraph 当循环）。工具只暴露「browse → evidence」这一个语义，把复杂性封装在内部。

---

## 1. 工具分层：search vs browse

research-assistant 现在有两个联网工具，分工明确：

| 工具 | 速度 | 深度 | 成本 | 用在 |
|---|---|---|---|---|
| `web_search`（ddgs） | 快 | 浅（摘要） | 低 | 打头：每个子问题都搜，拿候选链接 |
| `browse_for_evidence`（browser） | 慢 | 深（详情页/翻页/取证） | 高 | 深挖：从候选链接里挑 allowlist 内的，真开浏览器提取 |

**流程**：researcher 先 `web_search` 拿摘要 + 来源链接 → 若 `enable_browser`，从链接里挑 allowlist 内的 URL → `browse_for_evidence` 进详情页提取 → 证据附进 finding。

```
web_search("LangGraph release") 
  → 摘要 + [github.com/..., arxiv.org/..., evil.com/...]
     ↓ enable_browser?
     ↓ 过滤 allowlist（evil.com 拦掉）
browse_for_evidence([github.com/..., arxiv.org/...])
  → [Evidence(内容, URL, 访问时间), ...]
     ↓ 附进 finding
"【LangGraph】发现：v0.12.0... 来源：真实联网搜索 + 浏览器取证"
```

---

## 2. 路由判断：什么问题值得开浏览器

不是每个子问题都值得开浏览器（贵）。路由判断（简化版，L10 强化）：

| 情况 | 开 browse？ | 理由 |
|---|---|---|
| 需要**详情页结构化字段**（版本号/日期/字段） | ✅ | 摘要拿不到 |
| 需要**翻页**内容 | ✅ | 摘要只第 1 页 |
| 需要**时效证据**（访问时间戳） | ✅ | 摘要无访问时间 |
| 只需**概念解释** | ❌ | 摘要够 |
| web_search 没拿到有用链接 | ❌ | 无 URL 可 browse |

当前实现：`enable_browser=true` 时对所有子问题都 browse（简化），靠 `max_pages=2` 控成本。L10 会加智能路由（判断子问题是否值得深挖）。

---

## 3. 降级链：browse 失败不阻塞研究

**关键工程决策**：browse 是「锦上添花」不是「必需」。失败时必须降级回 search 摘要，不能让整个研究流程断。

```python
browser_evidence = ""
browser_tool = get_browser_tool()
if browser_tool is not None:
    try:
        evidences = await browser_tool.browse_for_evidence(subtopic, urls)
        browser_evidence = browser_tool.format_evidence_for_prompt(evidences)
    except Exception as e:
        log.warning(f"browser_tool 取证失败，降级到搜索摘要：{e}")
        browser_evidence = ""  # 空 = 降级，研究继续走 search 摘要
```

三层兜底：

1. **单页失败**：`extract_from_page` 异常 → 跳过该页，继续其他页。
2. **整批失败**：`browse_for_evidence` 异常 → browser_evidence 空，finding 仍含 search 摘要。
3. **工具不可用**：`enable_browser=false` 或 playwright 未装 → `get_browser_tool()` 返回 None，完全不介入。

> 🎯 **工具会失败是常态，降级链才是工程**。这和 `web_search` 的超时兜底、`kb_search` 的失败降级是同一套哲学——第五门课 ops 的「优雅降级」在 GUI 场景的延续。

---

## 4. 安全规则默认开

L07 的安全层在落地时**默认开**（不像 enable_browser 那样可关）——安全是红线不是开关：

| 安全规则 | 位置 | 默认 |
|---|---|---|
| 域名 allowlist | `check_url_allowed` | ✅ 开（DEFAULT_ALLOWED_DOMAINS） |
| 敏感动作检测 | `is_sensitive_url` | ✅ 开（命中即拦，不执行） |
| 注入标记扫描 | `scan_injection` | ✅ 开（命中即标注隔离） |

`enable_browser` 控制的是「要不要开浏览器」，不是「要不要安全」。即使开了浏览器，allowlist 仍硬拦 evil.com——这是 L07「动作层是压舱石」的落地。

---

## 5. 配置项（任务书 1.3）

新增进 `config.py` 的 `Settings`，全部默认关/安全值：

```python
enable_browser: bool = False              # 总开关，默认关
browser_max_steps: int = 12               # 步数上限（成本）
browser_page_timeout: int = 15            # 单页超时（秒）
browser_headless: bool = True             # 无头模式
browser_domain_allowlist: str = ""        # 域名白名单（空=用默认）
vision_model: str = "glm-4v-plus"         # 视觉模型（混合路线 L05）
```

`enable_browser` 默认关：不破坏现有 104 测试。开启后能拿到详情页证据，但需要 playwright + chromium 环境。

### 单例懒加载（仿 memory_store）

```python
_browser_tool = None
def get_browser_tool():
    if not settings.enable_browser:
        return None  # 完全不介入
    if _browser_tool is None:
        _browser_tool = BrowserTool()
    return _browser_tool
```

懒加载 + 单例：browser 进程只在第一次用时启动，多次调用共享。`enable_browser=false` 时连 BrowserTool 类都不构造——现有测试零影响。

---

## 6. 落地清单

### 改动文件

| 文件 | 改动 |
|---|---|
| `src/research_assistant/browser_tool.py` | **新增**：BrowserTool(async) + 安全层 + Evidence + 单例 |
| `src/research_assistant/config.py` | **新增** 6 个 browser 配置项（默认关） |
| `src/research_assistant/nodes.py` | researcher 接入：web_search 后 browse 取证 + 降级 |
| `tests/test_browser_tool.py` | **新增** 17 测试：安全层/降级/证据/单例/开关 |

### 验证

```bash
cd portfolio-projects/research-assistant

# 1. 全量测试（121 全绿，含新增 17 个 browser 测试）
.venv/Scripts/python.exe -m pytest tests/ -q
# 预期：121 passed（原 104 + browser 17）

# 2. 开 enable_browser 跑硬任务（需 playwright + 本地服务 + API key）
ENABLE_BROWSER=true .venv/Scripts/python.exe -m research_assistant.cli "对比 LangGraph release 版本号"
# 轨迹可见：researcher 日志「浏览器取证：N 页证据」，finding 含 URL+访问时间

# 3. 降级验证：关掉浏览器，确认完全回退现状
.venv/Scripts/python.exe -m pytest tests/ -q  # 仍 121 passed
```

> ⚠️ 真实跑硬任务需 `ZHIPUAI_API_KEY` + playwright + chromium。课程 code.py 用本地页 + mock 演示。

---

## 7. 课程 code.py 演示

`gui-agent-lessons/09_browser_tool/code.py` 演示落地效果：

- 起本地服务（L00 test_pages 当详情页）
- 用真实 `BrowserTool`（async）browse 本地详情页
- 对比「纯 search 摘要」vs「search + browse 证据」的 finding 差异
- 展示降级链（mock browse 失败 → 回退 search）

详见 code.py。

---

## 8. 本课在两条主线上的位置

- **评估主线**：本课是评估主线的**被评对象升级**——L08 mini-benchmark 现在可以评「带 browse 的 researcher」vs「纯 search 的 researcher」，L11 收益表会有这一列。本课的 17 个测试也是评估的一部分（安全/降级机制本身可验证）。
- **观察-行动接口主线**：本课把课程里的观察/行动能力**封装成工具接口**——researcher 不直接操作浏览器，调 `browse_for_evidence(query, urls) → [Evidence]`。接口隐藏了观察空间/动作 DSL/循环的复杂性，只暴露「取证」语义。这是从「手写机制」到「生产工具」的抽象跃迁。

---

## 🎯 面试话术

> 「我的研究助手搜索和浏览是分层的：便宜的 web_search 打头拿摘要+链接，值得深挖才开 browser 进详情页取证，带回 URL+访问时间的证据。browse 是锦上添花不是必需——失败自动降级回 search 摘要，研究流程不断。安全规则（allowlist/敏感确认/注入扫描）默认开，不随 enable_browser 开关——安全是红线。enable_browser 默认关，单例懒加载，121 个测试全绿，开启后能拿到搜索 API 拿不到的详情页字段。」
