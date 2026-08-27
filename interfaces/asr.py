# -*- coding: utf-8 -*-
"""
ASR（语音转文字）接口 —— 已接入本地 faster-whisper
------------------------------------------------
使用 faster-whisper 在本地把音频识别为中文文字，
无需联网、零 API 费用。首次使用会自动下载对应尺寸的模型。

模型尺寸与速度/精度权衡（越小越快、越不准）：
  tiny / base / small / medium / large-v3
中文推荐 base 或 small。
"""
import os
import tempfile
import threading

# 国内访问 HuggingFace 超时时，自动切换到镜像站下载模型
if "HF_ENDPOINT" not in os.environ:
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
# 镜像站对 Xet 存储重建支持不佳，禁用 Xet 走传统下载
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# 全局单例：避免每次识别都重新加载模型（加载很慢）
_model = None
_model_config = None
_lock = threading.Lock()


def _get_model(model_size: str, device: str, compute_type: str):
    """懒加载 faster-whisper 模型（线程安全，只加载一次）。"""
    global _model, _model_config
    key = (model_size, device, compute_type)
    with _lock:
        if _model is None or _model_config != key:
            from faster_whisper import WhisperModel
            _model = WhisperModel(model_size, device=device, compute_type=compute_type)
            _model_config = key
        return _model


def warmup(model_size: str, device: str, compute_type: str):
    """预热：提前加载 faster-whisper 模型，避免首次识别时卡顿。

    在后端启动时调用，把耗时的模型加载提前完成，这样第一次语音请求
    就不会因加载模型而超时。
    """
    _get_model(model_size, device, compute_type)


def recognize_speech(audio_file_path: str = None,
                     model_size: str = "base", device: str = "cpu",
                     compute_type: str = "int8", language: str = "zh",
                     **kwargs) -> str:
    """将音频文件识别为文字。

    参数:
        audio_file_path: 音频文件路径（wav/mp3 等常见格式均可）。
        model_size: faster-whisper 模型尺寸（tiny/base/small/medium/large-v3）。
        device: cpu 或 cuda。
        compute_type: cpu 上建议 int8；cuda 上可用 float16。
        language: 识别语言，zh 表示中文（可设为 None 自动检测）。
        **kwargs: 预留扩展参数。

    返回:
        str: 识别出的文本（去掉首尾空白）。
    """
    if not audio_file_path:
        raise ValueError("缺少音频文件路径：请传入 audio_file_path。")

    model = _get_model(model_size, device, compute_type)
    segments, _info = model.transcribe(audio_file_path, language=language)
    # 拼接所有片段文本
    text = "".join(seg.text for seg in segments).strip()
    return text


def recognize_bytes(audio_data: bytes, suffix: str = ".wav", **kwargs) -> str:
    """将音频字节（如板子上传的 WAV）识别为文字。

    参数:
        audio_data: 音频二进制内容。
        suffix: 临时文件后缀，需与音频实际格式一致。
        **kwargs: 透传给 recognize_speech（model_size/device/language 等）。
    """
    if not audio_data:
        raise ValueError("音频数据为空。")

    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(audio_data)
        return recognize_speech(tmp_path, **kwargs)
    finally:
        # 清理临时文件
        try:
            os.remove(tmp_path)
        except OSError:
            pass
