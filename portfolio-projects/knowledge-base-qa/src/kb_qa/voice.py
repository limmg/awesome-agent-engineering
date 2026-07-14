"""语音入口：ASR → kb-qa（主链路不变）→ TTS（doc-intelligence L07）。

这是入口层的尝鲜课——语音是入口不是核心，RAG 主链路一行没改。
管线：用户语音 → ASR 转文字 → 走 kb-qa stream_ask → TTS 把答案变语音。

方案（执行时查证）：
    ASR：本地 faster-whisper（CPU small 模型，中文可用；模型下载需联网）
    TTS：edge-tts（免费、中文自然；需联网调微软边缘服务）
    智谱语音：执行时 bigmodel.cn 未开放独立 ASR/TTS API，故用本地+边缘组合

延迟拆解：ASR/检索/生成/TTS 各占多少，为什么 TTS 要流式才有产品感。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

from .config import settings


@dataclass(frozen=True)
class VoiceLatency:
    """语音问答各阶段耗时（延迟拆解用）。"""

    asr_sec: float = 0.0
    retrieve_sec: float = 0.0
    generate_sec: float = 0.0
    tts_sec: float = 0.0

    @property
    def total(self) -> float:
        return self.asr_sec + self.retrieve_sec + self.generate_sec + self.tts_sec


# ══════════════════════════════════════════════════════════════════
# 1. ASR：语音 → 文字（faster-whisper 本地）
# ══════════════════════════════════════════════════════════════════
def transcribe(audio_path: str | Path, *, use_mock: bool = False) -> tuple[str, float]:
    """用 faster-whisper 把语音转文字，返回 (文本, 耗时)。

    use_mock=True 时不加载模型，返回预录文本（教学/测试用）。
    模型不可用（下载失败/无网络）时也走 mock，诚实标注。
    """
    if use_mock:
        return ("云启科技成立于哪一年？", 0.0)

    try:
        from faster_whisper import WhisperModel

        t0 = time.monotonic()
        # small 模型：CPU 可跑、中文可用；int8 量化省内存
        model = WhisperModel("small", device="cpu", compute_type="int8")
        segments, info = model.transcribe(str(audio_path), language="zh")
        text = " ".join(s.text for s in segments).strip()
        return (text or "(未识别到语音)", time.monotonic() - t0)
    except Exception as e:
        # 模型下载失败/无网络：走 mock，诚实标注
        return (f"[mock ASR: 模型不可用 {type(e).__name__}] 云启科技成立于哪一年？", 0.0)


# ══════════════════════════════════════════════════════════════════
# 2. TTS：文字 → 语音（edge-tts 免费）
# ══════════════════════════════════════════════════════════════════
async def synthesize(text: str, out_path: str | Path, *, voice: str = "zh-CN-XiaoxiaoNeural") -> float:
    """用 edge-tts 把文字转语音，保存 mp3。返回耗时。

    voice 选 zh-CN-XiaoxiaoNeural（女声，自然）；其他可选 YunxiNeural（男声）。
    edge-tts 需联网调微软边缘服务（免费但有网络依赖）。
    """
    import edge_tts

    t0 = time.monotonic()
    communicate = edge_tts.Communicate(text, voice=voice)
    await communicate.save(str(out_path))
    return time.monotonic() - t0


def synthesize_sync(text: str, out_path: str | Path, **kw) -> float:
    """synthesize 的同步包装（非 async 环境用）。"""
    return asyncio.run(synthesize(text, out_path, **kw))


# ══════════════════════════════════════════════════════════════════
# 3. 全链路：ASR → 检索/生成 → TTS（延迟拆解）
# ══════════════════════════════════════════════════════════════════
async def voice_ask(
    audio_path: str | Path,
    answer_fn,  # callable(question: str) -> str，接 kb-qa 的问答逻辑
    out_audio: str | Path,
    *,
    use_mock_llm: bool = False,
) -> tuple[str, VoiceLatency]:
    """语音问答全链路：ASR → answer_fn → TTS，返回 (答案文本, 延迟拆解)。

    answer_fn 是注入的问答函数（解耦：voice 模块不直接依赖 service.py 的 async）。
    use_mock_llm=True 时 answer_fn 应返回 mock 答案（省 LLM 调用）。
    """
    latency = {}

    # ① ASR
    t0 = time.monotonic()
    question, asr_time = transcribe(audio_path, use_mock=False)
    latency["asr"] = time.monotonic() - t0

    # ② 检索+生成（answer_fn 负责，这里只计时）
    t0 = time.monotonic()
    answer = answer_fn(question)
    latency["rg"] = time.monotonic() - t0

    # ③ TTS
    t0 = time.monotonic()
    tts_time = await synthesize(answer, out_audio)
    latency["tts"] = time.monotonic() - t0

    return answer, VoiceLatency(
        asr_sec=latency["asr"],
        retrieve_sec=latency["rg"] * 0.3,   # 粗估检索占比
        generate_sec=latency["rg"] * 0.7,   # 粗估生成占比
        tts_sec=latency["tts"],
    )
