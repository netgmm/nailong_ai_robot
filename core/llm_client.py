# -*- coding: utf-8 -*-
"""
大模型客户端模块
------------------
封装 OpenAI 兼容接口（/chat/completions），统一异常处理。
切换不同厂商 API 只需修改 config.yaml 中的 base_url 与 model，无需改动本文件。
"""
import requests


class LLMError(Exception):
    """大模型调用过程中的可预期错误（网络 / 接口 / 密钥等），已转为友好提示。"""
    pass


class LLMClient:
    """OpenAI 兼容接口客户端。"""

    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float = 0.8, max_tokens: int = 512,
                 timeout: int = 30):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def chat(self, messages: list) -> str:
        """发送多轮对话消息，返回助手回复文本。

        参数:
            messages: 消息列表，元素格式 {"role": "system"/"user"/"assistant", "content": str}

        返回:
            str: 模型回复内容

        抛出:
            LLMError: 网络 / 接口 / 密钥等错误（已转成友好提示）
        """
        # 未填写密钥时提前拦截，给出明确指引
        if not self.api_key or self.api_key.startswith("sk-在此"):
            raise LLMError("尚未填写有效的 API 密钥，请编辑 config.yaml 中的 api_key。")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }

        # 网络层异常统一捕获，避免程序直接崩溃
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        except requests.exceptions.Timeout:
            raise LLMError("请求超时啦，奶龙有点卡住~ 请检查网络或稍后重试。")
        except requests.exceptions.ConnectionError:
            raise LLMError("网络连接失败，奶龙连不上服务器了~ 请检查网络设置。")
        except requests.exceptions.RequestException as e:
            raise LLMError(f"网络请求出错：{e}")

        # 非 200 状态码，按常见情况给出针对性提示
        if resp.status_code != 200:
            detail = resp.text[:300]
            if resp.status_code == 401:
                raise LLMError("API 密钥无效或无权限（401），请检查 config.yaml 中的 api_key。")
            if resp.status_code == 429:
                raise LLMError("请求过于频繁或额度不足（429），请稍后重试或检查账户额度。")
            raise LLMError(f"接口返回错误（HTTP {resp.status_code}）：{detail}")

        # 解析返回内容
        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError) as e:
            raise LLMError(f"接口返回格式异常，无法解析回复：{e}")

        return content.strip()
