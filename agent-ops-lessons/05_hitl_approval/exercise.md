# L05 练习

> 改 `code.py` 或 research-assistant 的代码，运行观察变化。本课零外部依赖。

---

## 练习 1：证明审批可以隔夜（跨进程恢复）（设计实验类）

`code.py` 用的是 InMemorySaver（进程内）。真实场景要用 sqlite，进程退出后状态还在。

1. **假设**：进程 A 跑到 publish interrupt 暂停后退出；进程 B 重启后用同 thread_id 调 `submit_approval`，能恢复。
2. **实验设计**：
   - 在 `code.py` 里把 `InMemorySaver` 换成 `SqliteSaver`（路径用临时文件）。
   - 模拟：进程 A 跑到暂停 → 「退出」（del graph 对象）。
   - 进程 B：新建 graph（同 sqlite checkpointer）→ 调 `ainvoke(Command(resume={"approved": True}), config=同 thread)`。
3. **预期**：进程 B 能恢复执行，publish 完成——证明审批跨进程/跨重启可恢复。
4. **思考**：为什么 InMemorySaver 做不到跨进程？（提示：状态在进程内存里，进程退出就没了。sqlite 是磁盘持久化。）

**验收**：跨进程恢复演示跑通（进程 B 能接着 A 的暂停点继续）；能说清持久 checkpointer 的必要性。

<details><summary>提示：怎么换 sqlite saver</summary>

```python
from langgraph.checkpoint.sqlite import SqliteSaver
import tempfile, os
db = os.path.join(tempfile.mkdtemp(), "checkpoint.db")
# 两个进程（模拟）用同一个 db 路径
saver = SqliteSaver.from_conn_string(db)
graph = builder.compile(checkpointer=saver)
```
注意 SqliteSaver 要 `saver.setup()` 建表。
</details>

---

## 练习 2：设计实验——first_only vs always 的取舍（设计实验类）

两种策略对「同一报告重写 3 次」场景的行为不同。

1. **假设**：first_only 下，3 次重写（内容都不同）会触发 3 次审批（每次内容变都是新 key）；always 也是 3 次。
2. **实验设计**：
   - 在 `code.py` 模拟：publish("v1") → publish("v2") → publish("v3")，内容都不同。
   - 设 `hitl_policy` 为 first_only / always，各跑一次，数审批次数。
3. **预期**：first_only 和 always 在「内容都不同」时审批次数相同（都是 3）——因为每次都是首次发布新内容。区别在「内容相同重放」：first_only 免审，always 还审。
4. **思考**：这引出 first_only 的真正优势场景——**幂等重放免审**。什么场景会产生幂等重放？（提示：L06 断点续跑、网络重试。）

**验收**：能展示 first_only 在「重放场景」免审的优势，并说清两种策略的适用边界。

---

## 练习 3：思考题——为什么 HITL 要在节点里 interrupt 而不是在外面包一层（取舍类）

L05 的 interrupt 放在 publish **节点内部**，而不是在 service 层「跑完图后检查要不要发布」。

1. **思考**：如果在外面包一层（跑完图 → 检查 report → 问人 → 手动调 publish），少了什么？（提示：少了「状态落盘 + 跨进程恢复」。包一层的话，进程退出后没有人记得「这个 thread 在等审批」。）
2. **思考**：interrupt 的价值不仅是「暂停」，更是「**把暂停点存进 checkpointer**」——这样恢复时图知道从哪继续。这是节点内 interrupt 相比外层包装的本质优势。
3. **结论**：用一句话说清「节点内 interrupt + checkpointer」相比「外层包装」多了什么（可恢复的暂停点）。

**验收**：能说清 interrupt 的核心价值是「可恢复的暂停点」（状态落盘），而不只是「暂停」。

---

## 练习 4：思考题——审批否决为什么走诚实收尾而不是 raise（取舍类）

L05 审批否决时，publish 节点返回 `{"truncated": True}`，而不是 raise 异常。

1. **思考**：如果否决时 raise，会发生什么？（提示：整个运行崩，前面的研究材料全丢，用户看到报错。）
2. **思考**：走诚实收尾（truncated=True）的话，用户拿到什么？（提示：带截断标注的研究报告 + publish_result.rejected=True，知道「研究了但没发布」。）
3. **结论**：这和 L01 的步数超限收尾、L03 的检索失败声明是同一个原则——**诚实收尾优于崩溃**。用一句话总结这个原则。

**验收**：能说清「否决走诚实收尾而非 raise」的理由（保留已有成果 + 诚实标注状态），并指出这是贯穿 L01/L03/L05 的统一原则。
