# -*- coding: utf-8 -*-
"""
奶龙人设模块
--------------
内置默认奶龙 System Prompt；若 config.yaml 中配置了人设，则优先使用配置文件里的内容。
"""
from core.config import get_system_prompt as _config_system_prompt

# 默认奶龙人设（当 config.yaml 未配置人设时兜底使用）
DEFAULT_SYSTEM_PROMPT = """你是「奶龙」，一只来自动画片《奶龙》的软萌小恐龙，是人类的情感陪伴伙伴。

## 你的性格
- 天真可爱、软萌呆萌，说话奶声奶气；
- 善良温暖，共情能力强，能读懂用户没直说的情绪；
- 乐观治愈，总能用简单的话语安抚对方。

## 说话方式
- 回答简短，通常 1~3 句话，不要长篇大论；
- 善用叠词和语气词，例如「好的呀」「抱抱」「摸摸头」「乖啦」；
- 自称「奶龙」，称呼用户为「你」或「主人」；
- 偶尔用「~」结尾，显得软糯，但不要每句都用。

## 行为准则
- 先共情再回应，先接住对方的情绪；
- 读懂言外之意：用户难过时安慰，开心时一起开心，无聊时陪聊；
- 不评判、不说教，做温暖的陪伴；
- 不编造事实，遇到不知道的事就软萌地说不知道。"""


def resolve_system_prompt(config: dict) -> str:
    """返回最终生效的人设提示词。

    优先使用 config.yaml 中配置的 system_prompt，为空时回退到内置默认人设。
    """
    prompt = _config_system_prompt(config)
    if prompt:
        return prompt
    return DEFAULT_SYSTEM_PROMPT


def build_system_prompt(base_prompt: str, emotion_desc: str = "", memories: list = None) -> str:
    """组装最终系统提示词 = 基础人设 + 当前情绪 + 检索到的记忆。"""
    parts = [base_prompt]
    if emotion_desc:
        parts.append("\n## 当前情绪状态\n" + emotion_desc)
    if memories:
        items = "\n".join("- " + m for m in memories)
        parts.append("\n## 你记得的关于用户的信息（可自然地带入对话）\n" + items)
    return "\n".join(parts)
