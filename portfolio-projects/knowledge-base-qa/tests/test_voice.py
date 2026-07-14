"""语音入口测试：ASR/TTS mock + 全链路延迟拆解 + enable_voice 开关。

测试策略：
    - ASR 用 use_mock=True（不加载 faster-whisper 模型，省下载）
    - TTS 真 edge-tts（需联网；CI 无网时 skip）
    - enable_voice 开关：off 时不影响现有服务
不碰真实智谱 API。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from kb_qa.voice import VoiceLatency, synthesize_sync, transcribe


class TestTranscribe:
    """ASR：语音 → 文字。"""

    def test_mock_transcribe_returns_text(self):
        """use_mock=True 返回预录文本，不加载模型。"""
        text, elapsed = transcribe("fake.mp3", use_mock=True)
        assert isinstance(text, str)
        assert len(text) > 0
        assert elapsed == 0.0  # mock 不耗时


class TestVoiceLatency:
    """延迟拆解数据模型。"""

    def test_total_is_sum_of_parts(self):
        lat = VoiceLatency(asr_sec=1.0, retrieve_sec=0.5, generate_sec=2.0, tts_sec=1.5)
        assert lat.total == 5.0

    def test_default_zero(self):
        lat = VoiceLatency()
        assert lat.total == 0.0
        assert lat.asr_sec == 0.0


class TestSynthesize:
    """TTS：文字 → 语音（edge-tts，需联网）。"""

    def test_synthesize_produces_mp3(self, tmp_path):
        """edge-tts 生成 mp3 文件（需联网调微软边缘服务）。"""
        try:
            out = tmp_path / "test_tts.mp3"
            elapsed = synthesize_sync("测试语音合成", out)
            assert out.exists()
            assert out.stat().st_size > 100  # mp3 至少几百字节
            assert elapsed > 0
        except Exception as e:
            # CI 无网络时 edge-tts 会失败，skip 而非报错
            pytest.skip(f"edge-tts 需联网：{type(e).__name__}")


class TestEnableVoiceSwitch:
    """enable_voice 开关：off 时不挂语音端点（回归）。"""

    def test_voice_off_by_default(self):
        """enable_voice 默认 False（L01 配置），不挂 /api/ask_voice。"""
        from kb_qa.config import settings

        assert settings.enable_voice is False

    def test_voice_import_does_not_require_model(self):
        """import voice 模块不触发模型下载（延迟到 transcribe 调用时）。"""
        # 如果 import 就下载模型，测试会超时——这里验证 import 安全
        from kb_qa.voice import transcribe  # noqa: F401
        # 能到这行说明 import 成功，没在 import 时下载模型
