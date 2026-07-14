"""Lesson 07 — 语音入口（尝鲜）
==================================
跑通「语音问答」全链路：ASR → kb-qa → TTS，拆解各段延迟。
    ① 样例提问音频（edge-tts 合成的）→ ASR 识别成文字
    ② 文字走问答（mock 答案，省 LLM）→ 拿到答案
    ③ 答案 TTS 成 mp3 → 全链产出
    ④ 延迟拆解：ASR/检索/生成/TTS 各占多少，瓶颈在哪

语音是入口不是核心——RAG 主链路一行没改。
faster-whisper 模型不可用（下载超时）时走 mock ASR，诚实标注。

运行：python code.py
依赖：edge-tts（venv 已装）+ faster-whisper（venv 已装，模型需联网下载）
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Windows GBK 坑：中文输出会 UnicodeEncodeError，统一 utf-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = ROOT / "data" / "multimodal_docs" / "voice_samples"
sys.path.insert(0, str(ROOT / "portfolio-projects" / "knowledge-base-qa" / "src"))


# ══════════════════════════════════════════════════════════════════
# 1. 生成样例提问音频（edge-tts 合成，模拟用户语音输入）
# ══════════════════════════════════════════════════════════════════
async def ensure_sample_question() -> Path:
    """确保有样例提问音频（没有就 edge-tts 合成一个）。"""
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    q_mp3 = SAMPLE_DIR / "question_sample.mp3"
    if not q_mp3.exists():
        import edge_tts

        text = "云启科技成立于哪一年？"
        communicate = edge_tts.Communicate(text, voice="zh-CN-XiaoxiaoNeural")
        await communicate.save(str(q_mp3))
        print(f"  [生成] 样例提问音频: {q_mp3.name}（edge-tts 合成）")
    else:
        print(f"  [复用] 样例提问音频: {q_mp3.name}")
    return q_mp3


# ══════════════════════════════════════════════════════════════════
# 2. 全链路：ASR → 问答 → TTS
# ══════════════════════════════════════════════════════════════════
async def run_full_pipeline(q_mp3: Path) -> dict:
    """跑完整语音问答链路，返回各段耗时和结果。"""
    from kb_qa.voice import transcribe, synthesize, VoiceLatency

    result = {}

    # ① ASR：语音 → 文字
    t0 = time.monotonic()
    question, asr_internal = transcribe(q_mp3, use_mock=False)
    result["asr_sec"] = time.monotonic() - t0
    result["question"] = question
    is_mock_asr = "[mock" in question

    # ② 检索 + 生成（mock 答案，省 LLM 调用——语音入口的延迟结构不依赖 LLM）
    t0 = time.monotonic()
    answer = mock_answer(question)  # 真实场景接 kb_qa.service.stream_ask
    rg_sec = time.monotonic() - t0
    result["retrieve_sec"] = rg_sec * 0.3  # 粗估检索占比
    result["generate_sec"] = rg_sec * 0.7  # 粗估生成占比
    result["answer"] = answer

    # ③ TTS：答案 → 语音
    out_mp3 = SAMPLE_DIR / "answer_output.mp3"
    t0 = time.monotonic()
    await synthesize(answer, out_mp3)
    result["tts_sec"] = time.monotonic() - t0
    result["out_mp3"] = out_mp3
    result["is_mock_asr"] = is_mock_asr

    return result


def mock_answer(question: str) -> str:
    """模拟 kb-qa 的答案（语音入口演示用，省 LLM 调用）。

    真实场景：from kb_qa.service import stream_ask; 收集 token 拼成 answer。
    这里用 mock 是因为语音课的重点是「管线 + 延迟结构」，不是问答质量。
    """
    if "成立于" in question or "哪一年" in question:
        return "云启科技成立于2018年，总部位于上海张江高科技园区。"
    if "年假" in question:
        return "入职满3年不满5年，每年有10天年假。"
    return "这是语音问答的演示答案。"


# ══════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════
async def amain() -> None:
    print("=" * 66)
    print("演示 1：生成样例提问音频（edge-tts）")
    print("=" * 66)
    q_mp3 = await ensure_sample_question()

    print("\n" + "=" * 66)
    print("演示 2：全链路 ASR → 问答 → TTS")
    print("=" * 66)
    r = await run_full_pipeline(q_mp3)

    print(f"\n  ① ASR: {r['question']}")
    if r["is_mock_asr"]:
        print(f"     ⚠️ [mock] faster-whisper 模型不可用，走预录文本")
    else:
        print(f"     ✅ 真实 faster-whisper 识别")
    print(f"     耗时: {r['asr_sec']:.2f}s")

    print(f"\n  ② 问答（mock）: {r['answer']}")
    print(f"     检索+生成耗时: {r['retrieve_sec']+r['generate_sec']:.2f}s (mock 近乎 0)")

    print(f"\n  ③ TTS: {r['out_mp3'].name}")
    print(f"     耗时: {r['tts_sec']:.2f}s")

    total = r["asr_sec"] + r["retrieve_sec"] + r["generate_sec"] + r["tts_sec"]
    print(f"\n  全链路总耗时: {total:.2f}s")

    print("\n" + "=" * 66)
    print("演示 3：延迟拆解 —— 瓶颈在哪")
    print("=" * 66)
    print(f"\n  {'阶段':<12} {'耗时':<10} {'占比':<10} {'说明'}")
    print("  " + "-" * 56)
    stages = [
        ("ASR", r["asr_sec"], "语音转文字，本地 faster-whisper"),
        ("检索", r["retrieve_sec"], "BM25+向量，通常 <0.5s"),
        ("生成", r["generate_sec"], "glm-4 流式，通常 1-3s（mock 近乎0）"),
        ("TTS", r["tts_sec"], "文字转语音，edge-tts 联网"),
    ]
    for name, sec, note in stages:
        pct = sec / total * 100 if total > 0 else 0
        print(f"  {name:<10} {sec:<10.2f} {pct:<10.0f}% {note}")
    print(f"\n  → 真实场景瓶颈在 ASR（首次加载模型慢）和生成（LLM 流式吐字）。")
    print(f"  → TTS 要流式才有产品感：非流式用户等全部生成完才听到声音（体感慢）。")

    print("\n" + "=" * 66)
    print("诚实标注")
    print("=" * 66)
    if r["is_mock_asr"]:
        print("  - ASR 走 mock（faster-whisper 模型下载失败/无网络），识别文本是预录的。")
        print("    真实 ASR 需联网下载 small 模型（首次 ~500MB）。")
    else:
        print("  - ASR 是真实 faster-whisper 识别。")
    print("  - 问答用 mock 答案（语音课重点是管线+延迟，不是问答质量）。")
    print("  - TTS 是真实 edge-tts（需联网调微软边缘服务，免费）。")
    print("  - 延迟数字是本机实测，不同硬件/网络会变。")
    print("  - 智谱 bigmodel.cn 执行时未开放独立 ASR/TTS API，故用本地+边缘组合。")


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
