# Lesson 07 — 语音入口（尝鲜，可选能力）

> 本课目标：**跑通「语音问答」全链路（ASR → kb-qa → TTS），拆解各段延迟，理解语音是入口不是核心——RAG 主链路一行没改**。
>
> 学完你能回答面试官那句：**「做过语音入口吗？」**——跑通过全链并拆解过延迟：ASR/检索/生成/TTS 各占多少、瓶颈在哪、为什么要流式 TTS。

---

## 1. 语音问答的管线

语音入口的本质：**把文字 RAG 的两端接上语音模态**。中间的检索/生成一行不改：

```
   用户说话                    用户听答案
      │                           ▲
      ▼                           │
   ┌──────┐    ┌─────────────┐  ┌──────┐
   │ ASR  │───▶│ kb-qa 主链路 │─▶│ TTS  │
   │听→字 │    │ 检索+生成    │  │字→听 │
   └──────┘    └─────────────┘  └──────┘
    faster-       BM25+向量        edge-tts
    whisper       +glm-4           (免费)
    (本地)        (一行没改)
```

> 🎯 **核心认知**：语音是**入口层**的扩展，不是核心层的改动。ASR 把语音变文字（入口），TTS 把文字变语音（出口），中间的 kb-qa 主链路（ops 课搭好的检索+生成+防注入+缓存）完全复用。**这意味着所有文本 RAG 的能力（多模态、引用溯源、防幻觉）语音入口全继承**。

### 为什么是尝鲜课

本课**不做**这些（它们是独立的工程领域）：
- ❌ 唤醒词（"嘿，知识库"）——这是前端设备的事
- ❌ VAD（语音活动检测，判断用户说完没）——这是实时音频流的事
- ❌ 实时对话（打断、全双工）——这是通信层的事

本课**只做**：一课讲透「上传一段提问音频 → 拿到一段答案音频」的管线与延迟结构。

---

## 2. 方案对比：ASR/TTS 的选型

执行时查证 bigmodel.cn：智谱当前**未开放独立的 ASR/TTS API**（有语音相关能力但非标准 ASR/TTS 接口）。故用本地 + 边缘组合：

| 组件 | 方案 | 成本 | 离线 | 中文 |
|---|---|---|---|---|
| **ASR** | faster-whisper（small，CPU） | 免费（本地） | ✅（模型下载后） | ✅ 可用 |
| **ASR** | 智谱（如有） | 按量计费 | 🚫 | ✅ | 
| **TTS** | edge-tts（微软边缘） | **免费** | 🚫（需联网） | ✅ 自然 |
| **TTS** | 智谱（如有） | 按量计费 | 🚫 | ✅ |

> 💡 **选 faster-whisper + edge-tts 的理由**：① 免费（faster-whisper 本地、edge-tts 微软免费额度）；② pip 友好（faster-whisper 是 CTranslate2 后端，比 OpenAI whisper 轻）；③ 中文可用（small 模型中文识别率够用，edge-tts 的 XiaoxiaoNeural 女声自然）。代价是 faster-whisper 首次要下 ~500MB 模型、edge-tts 需联网。

```
ASR 模型选型（faster-whisper）：

   tiny   39MB   快但精度低（短句可用）
   small  244MB  平衡（本课用，中文够用）   ← 推荐
   medium 769MB  更准但慢（生产可升级）
   large  1.5GB  最准但 CPU 太慢（要 GPU）
```

---

## 3. 延迟拆解：瓶颈在哪

`code.py` 跑全链路，各段耗时（本机实测，mock ASR + mock 问答 + 真 TTS）：

| 阶段 | 耗时 | 占比 | 瓶颈分析 |
|---|---|---|---|
| **ASR** | ~24s（含模型加载/下载超时） | 91% | 首次加载模型慢；稳态 small 模型 ~1-2s/句 |
| 检索 | <0.5s | <2% | BM25+向量，ops 课已优化 |
| 生成 | 1-3s | 5-10% | glm-4 流式吐字（mock 近乎 0） |
| **TTS** | ~2.4s | 9% | edge-tts 联网，非流式要等全部合成 |

> 🎯 **两个关键洞察**：
> 1. **ASR 首次加载是假瓶颈**——模型加载一次常驻内存，后续每句 ~1-2s。生产环境预热模型即可。
> 2. **TTS 要流式才有产品感**——非流式 TTS 用户等全部文本生成完 + 全部音频合成完才听到声音（体感很慢）。流式 TTS（边生成边合成边播放）能把首字延迟压到 1s 内。

```
非流式 vs 流式 TTS 的体感差：

   非流式：用户说完 → [ASR 2s][检索 0.5s][生成 3s][TTS 2.5s] → 开始听
           首字延迟 = 8s 😴（用户以为卡住了）

   流式：  用户说完 → [ASR 2s][检索 0.5s] → 边生成边 TTS 边播放
           首字延迟 = 3s 🙂（边说边听，接近对话感）
```

> 💡 **本课的 TTS 是非流式**（教学简化）。生产要做流式：glm-4 的 `astream` 边吐 token、edge-tts 边合成音频片段、前端边播放。这是工程优化，不在本课范围。

---

## 4. 落地：/api/ask_voice 端点

```python
@app.post("/api/ask_voice")
async def ask_voice(file: UploadFile):
    if not settings.enable_voice:
        raise HTTPException(404, "语音入口未启用")
    
    question, _ = transcribe(audio_path)      # ① ASR
    async for event in stream_ask(question):  # ② 主链路（一行没改）
        ...                                    # 收集 token
    await synthesize(answer, out_path)         # ③ TTS
    return FileResponse(out_path, media_type="audio/mpeg")
```

> 🎯 **enable_voice 默认 False**。不开语音入口时，`/api/ask_voice` 返 404，现有服务完全不受影响。配置 `ENABLE_VOICE=true` 才挂载。

---

## 5. 本课代码会做什么

### `code.py`（真实 TTS + mock ASR/问答）
- ① 生成样例提问音频（edge-tts 合成）
- ② 全链路：ASR → 问答（mock）→ TTS，产出答案 mp3
- ③ 延迟拆解：各段耗时 + 占比 + 瓶颈分析

### 落地到 kb-qa
- 新增 `src/kb_qa/voice.py`：`transcribe`（ASR）+ `synthesize`（TTS）+ `voice_ask`（全链路）
- `api/main.py` 加 `/api/ask_voice` 端点（`enable_voice` 控制）
- `tests/test_voice.py`：6 个测试（ASR mock + TTS + 开关 + 延迟模型）

---

## 6. 跑起来

### 教学代码
```bash
cd doc-intelligence-lessons/07_voice
python code.py
```
预期：样例音频 → ASR（mock 或真）→ mock 答案 → TTS mp3 + 延迟拆解表。

> ⚠️ faster-whisper 首次要下 small 模型（~500MB，需联网）；下载失败走 mock ASR（预录文本）。

### 落地验证（kb-qa）
```bash
cd portfolio-projects/knowledge-base-qa
python -m pytest tests/test_voice.py -q                      # 6 passed
python -m pytest -q                                            # 全绿
# 验证 enable_voice=off 时端点不生效：
python -c "
from fastapi.testclient import TestClient
from api.main import app
c = TestClient(app)
r = c.post('/api/ask_voice')  # enable_voice 默认 False
print(r.status_code)  # → 404
"
```

### 验收检查
- [ ] 样例 wav 全链跑通产出 mp3
- [ ] 延迟拆解表：ASR/检索/生成/TTS 各段耗时
- [ ] `enable_voice=off` 时 `/api/ask_voice` 返 404（现有服务不受影响）
- [ ] 诚实标注：ASR mock / 真、TTS 真、问答 mock

---

## 🎯 面试话术

> 「语音入口我跑通过全链并拆解过延迟：ASR 用本地 faster-whisper（small 模型 CPU 可跑、中文够用），TTS 用 edge-tts（微软免费、Xiaoxiao 女声自然）。全链路 ASR → kb-qa 主链路 → TTS，中间检索生成一行没改——语音是入口不是核心，所有文本 RAG 的能力语音全继承。延迟瓶颈在 ASR 首次加载（预热可解）和 TTS 非流式（流式 TTS 能把首字延迟从 8s 压到 3s）。智谱当时没开放独立 ASR/TTS API，所以用本地+边缘组合。」

---

## 落地清单

| 文件 | 改动 | 如何验证 |
|---|---|---|
| `src/kb_qa/voice.py` | **新增**：`transcribe`(ASR) + `synthesize`(TTS) + `voice_ask`(全链路) + `VoiceLatency` | `python -c "from kb_qa.voice import transcribe; print(transcribe('x', use_mock=True))"` |
| `api/main.py` | 加 `/api/ask_voice` 端点（`enable_voice` 控制，默认 404） | `enable_voice=off` 时 POST 返 404 |
| `src/kb_qa/config.py` | `enable_voice` 已加（L01），默认 False | `settings.enable_voice is False` |
| `tests/test_voice.py` | **新增**：6 个测试（ASR mock + TTS + 开关 + 延迟模型） | `pytest tests/test_voice.py -q` → 6 passed |

> 📌 **两条主线位置**：本课在**成本-精度主线**上是入口层的轻量尝鲜——本地 ASR + 免费 TSS，不碰核心层的成本结构；在**溯源主线**上，语音入口复用主链路的引用溯源（ASR 出的文字带页码引用，TTS 只是读出来），不削弱可信度。

下一课 [Lesson 08 — 多模态评估：收益表](../08_evaluation/) 量化全部多模态机制的收益，出最终收益表对照 L00 基线。
