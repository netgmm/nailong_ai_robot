# -*- coding: utf-8 -*-
"""
配置加载模块
--------------
负责读取 config.yaml，提供统一的配置访问入口，并做基本校验。
所有需要频繁修改的项（接口地址、密钥、模型名、人设提示词）都集中在 config.yaml。
"""
import os

import yaml

# 默认配置文件路径：项目根目录下的 config.yaml
DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config.yaml",
)


class ConfigError(Exception):
    """配置相关异常（文件缺失 / 语法错误等）。"""
    pass


def load_config(config_path: str = None) -> dict:
    """加载并返回配置字典。

    参数:
        config_path: 配置文件路径，缺省使用项目根目录下的 config.yaml

    返回:
        dict: 配置字典

    抛出:
        ConfigError: 文件不存在或 YAML 语法错误
    """
    path = config_path or DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        raise ConfigError(
            f"找不到配置文件：{path}\n请先创建 config.yaml 并填写 API 密钥。"
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"配置文件解析失败（请检查 YAML 语法）：{e}")

    if not config:
        raise ConfigError("配置文件内容为空。")

    return config


def get_llm_config(config: dict) -> dict:
    """从配置字典中提取大模型相关参数，缺失项使用默认值。"""
    llm = config.get("llm", {}) or {}
    # API 密钥优先读环境变量 DEEPSEEK_API_KEY，读不到再回退 config.yaml（便于不把密钥写进仓库）
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        api_key = (llm.get("api_key") or "").strip()
    return {
        "base_url": (llm.get("base_url") or "").strip(),
        "api_key": api_key,
        "model": (llm.get("model") or "gpt-4o-mini").strip(),
        "temperature": float(llm.get("temperature", 0.8)),
        "max_tokens": int(llm.get("max_tokens", 512)),
        "timeout": int(llm.get("timeout", 30)),
    }


def get_system_prompt(config: dict) -> str:
    """从配置字典中提取人设提示词（未配置时返回空字符串）。"""
    prompt = (config.get("personality", {}) or {}).get("system_prompt", "")
    return (prompt or "").strip()


def get_memory_config(config: dict) -> dict:
    """提取长期记忆相关配置。"""
    mem = config.get("memory", {}) or {}
    default_path = os.path.join(os.path.dirname(DEFAULT_CONFIG_PATH), "data", "memory.json")
    return {
        "enabled": bool(mem.get("enabled", True)),
        "path": (mem.get("path") or "").strip() or default_path,
        "top_k": int(mem.get("top_k", 3)),
        "max_items": int(mem.get("max_items", 200)),
    }


def get_emotion_config(config: dict) -> dict:
    """提取动态情绪相关配置。"""
    emo = config.get("emotion", {}) or {}
    return {
        "enabled": bool(emo.get("enabled", True)),
        "baseline": float(emo.get("baseline", 0.2)),
        "decay": float(emo.get("decay", 0.3)),
    }


def get_tts_config(config: dict) -> dict:
    """提取语音输出（GPT-SoVITS）相关配置。"""
    tts = config.get("tts", {}) or {}
    return {
        "enabled": bool(tts.get("enabled", False)),
        "api_url": (tts.get("api_url") or "").strip(),
        "ref_audio_path": (tts.get("ref_audio_path") or "").strip(),
        "prompt_text": (tts.get("prompt_text") or "").strip(),
        "prompt_language": (tts.get("prompt_language") or "zh").strip(),
        "text_language": (tts.get("text_language") or "zh").strip(),
        "timeout": int(tts.get("timeout", 60)),
    }


def get_asr_config(config: dict) -> dict:
    """提取语音输入（faster-whisper）相关配置。"""
    asr = config.get("asr", {}) or {}
    return {
        "enabled": bool(asr.get("enabled", True)),
        "model_size": (asr.get("model_size") or "base").strip(),
        "device": (asr.get("device") or "cpu").strip(),
        "compute_type": (asr.get("compute_type") or "int8").strip(),
        "language": (asr.get("language") or "zh").strip(),
    }
