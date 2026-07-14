# Lesson 07 练习

> 改 `code.py` 和 `src/kb_qa/voice.py` 里的代码，运行 `python code.py` 观察变化。本课依赖 faster-whisper（模型需联网下载）+ edge-tts（需联网）。

---

## 练习 1：换 ASR 模型大小，对比精度和速度

`voice.py` 的 `transcribe` 用的是 small 模型。换成 tiny（更快）或 medium（更准）对比：

```python
# voice.py transcribe 里
model = WhisperModel("tiny", device="cpu", compute_type="int8")   # 原来是 small
```

有模型时跑 `code.py`，看识别结果和耗时变化。

**思考**：tiny 模型识别「云启科技成立于哪一年」准确吗？耗时比 small 快多少？——**tiny 对短句够用，但对长句/专业词可能出错**。模型选型是精度-速度-内存的三角：tiny 快但糙、small 平衡、medium 准但慢。你的场景（短提问 vs 长段语音）决定选哪个。生产环境通常 small 起步，按错误率调。

---

## 练习 2：换 TTS 声音，听自然度差异

edge-tts 有多个中文声音。换成男声对比：

```python
# code.py 或 voice.py
await synthesize(answer, out_path, voice="zh-CN-YunxiNeural")   # 男声（原来 Xiaoxiao 女声）
```

跑全链路，听答案 mp3 的声音差别。

**思考**：Xiaoxiao（女声）和 Yunxi（男声）哪个更自然？——**都挺自然**（微软神经语音质量高）。声音选型更多是**产品调性**：企业知识库可能偏中性女声、C 端产品可能用活泼的声音。edge-tts 还有 Xiaoyi（温柔）、Yunjian（沉稳）等。这不是技术问题，是产品问题。

---

## 练习 3（设计实验）：量「非流式 vs 流式 TTS」的首字延迟

这是本课的**设计实验验证**题——量化流式 TTS 的产品价值。

非流式 TTS：等全部文本生成完 → 全部合成 → 播放。流式：边生成边合成边播放。设计实验量首字延迟：

```python
# code.py 加一个对比
import time

# 非流式（现状）
t0 = time.monotonic()
answer = mock_answer(question)          # 假装生成 3s
time.sleep(3)  # 模拟生成耗时
await synthesize(answer, out_path)      # TTS 2.5s
non_stream_first_byte = time.monotonic() - t0  # 5.5s 才能播放

# 流式（概念演示）
t0 = time.monotonic()
first_chunk = answer[:10]  # 假装生成完第一句
time.sleep(1)  # 首句生成 1s
await synthesize(first_chunk, chunk_path)  # 首句 TTS 0.5s
stream_first_byte = time.monotonic() - t0  # 1.5s 就能播放
print(f"非流式首字: {non_stream_first_byte:.1f}s vs 流式首字: {stream_first_byte:.1f}s")
```

**思考**：首字延迟差多少？——**约 4s**（5.5s vs 1.5s）。这就是流式 TTS 的产品价值：用户说完 1.5s 就听到第一个字（接近对话感），而非流式要 5.5s（用户以为卡住）。**首字延迟是语音交互的核心体验指标**，比总耗时更重要。把这个数字记下来——这是「为什么要流式」的量化论证。

---

## 练习 4（进阶）：接真实 kb-qa 问答（替 mock）

现在 `code.py` 的问答是 mock。接真实的 `stream_ask`：

```python
# code.py mock_answer 替换成：
async def real_answer(question: str) -> str:
    from kb_qa.service import stream_ask
    parts = []
    async for event in stream_ask(question, thread_id="voice-demo"):
        if event.get("event") == "token":
            parts.append(json.loads(event["data"])["content"])
    return "".join(parts)
```

需要：ZHIPUAI_API_KEY + 预先 ingest 文档。

**思考**：接真实问答后，延迟拆解表里「生成」那栏从 0 变成多少？——**1-3s**（glm-4 流式）。这时候延迟瓶颈的分布就真实了：ASR ~2s + 生成 ~2s + TTS ~2.5s。**真实的语音问答首字延迟约 4-5s（非流式）**，这对企业内部工具可接受，对 C 端实时对话不够（要流式压到 2s 内）。你的产品形态决定延迟预算。

---

## ✅ 完成本课后，你应该能回答

1. 语音问答的管线是什么？中间的 RAG 主链路改了吗？（没改，语音是入口）
2. ASR/TTS 的选型？为什么用 faster-whisper + edge-tts？（免费、pip 友好、中文可用）
3. 延迟拆解：ASR/检索/生成/TTS 各占多少？瓶颈在哪？
4. 为什么 TTS 要流式才有产品感？（首字延迟，非流式用户等太久）
5. faster-whisper 的模型大小（tiny/small/medium）怎么选？（精度-速度-内存三角）
6. enable_voice 默认为什么关？（不影响现有服务，按需开启）
7. （落地）kb-qa 的 `/api/ask_voice` 端点怎么工作？enable_voice=off 时返回什么？
