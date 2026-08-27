# -*- coding: utf-8 -*-
"""
TTS（文字转语音）接口 —— 已接入本地 GPT-SoVITS
------------------------------------------------
通过 GPT-SoVITS 自带的 api.py 暴露的 /tts 接口，
把文字合成为奶龙音色的 WAV 音频，并本地播放。
"""
import os

import requests


def synthesize_speech(text: str, output_path: str = None,
                      api_url: str = "", ref_audio_path: str = "",
                      prompt_text: str = "", prompt_language: str = "zh",
                      text_language: str = "zh", timeout: int = 60,
                      **kwargs) -> bytes:
    """调用 GPT-SoVITS 合成语音，返回 WAV 音频字节。

    参数:
        text: 待合成的文本。
        output_path: 音频保存路径；为 None 时仅返回音频字节。
        api_url: GPT-SoVITS /tts 接口地址。
        ref_audio_path: 参考音频路径（引导音色）。
        prompt_text: 参考音频逐字对应的文本。
        prompt_language / text_language: 参考 / 目标语言。
        timeout: 合成超时（秒）。

    返回:
        bytes: WAV 音频字节。
    """
    if not api_url:
        raise RuntimeError("未配置 GPT-SoVITS 的 api_url，请检查 config.yaml 的 tts 段。")

    params = {
        "text": text,
        "text_lang": text_language,
        "ref_audio_path": ref_audio_path,
        "prompt_text": prompt_text,
        "prompt_lang": prompt_language,
    }
    resp = requests.get(api_url, params=params, timeout=timeout)
    resp.raise_for_status()
    audio = resp.content

    if output_path:
        with open(output_path, "wb") as f:
            f.write(audio)
    return audio


def play_audio(audio_bytes: bytes, method: str = "winsound"):
    """播放音频字节。

    method:
        "winsound"  —— Windows 原生，零依赖（默认）
        "playsound" —— 跨平台，需 pip install playsound
    """
    # 用固定路径覆盖写入，避免临时文件堆积
    tmp_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data", "tts_output.wav"
    )
    tmp_path = os.path.abspath(tmp_path)
    os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
    with open(tmp_path, "wb") as f:
        f.write(audio_bytes)

    if method == "winsound":
        import winsound
        winsound.PlaySound(tmp_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
    else:
        from playsound import playsound
        playsound(tmp_path)
