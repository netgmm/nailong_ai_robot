# -*- coding: utf-8 -*-
"""
对话历史管理模块
------------------
维护多轮对话上下文（system 人设 + 历史消息），
支持把聊天记录留存到本地 JSONL 文件，并可重新加载续聊。
"""
import json
import os


class Conversation:
    """多轮对话上下文管理器。"""

    def __init__(self, system_prompt: str = ""):
        self.system_prompt = system_prompt
        # 历史消息列表：[{"role": "user"/"assistant", "content": str}]
        self.history = []

    def add_user(self, content: str):
        """追加一条用户消息。"""
        self.history.append({"role": "user", "content": content})

    def add_assistant(self, content: str):
        """追加一条助手消息。"""
        self.history.append({"role": "assistant", "content": content})

    def get_messages(self) -> list:
        """返回完整消息列表（含 system 人设），用于发送给大模型。"""
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self.history)
        return messages

    def set_system_prompt(self, prompt: str):
        """动态更新本轮使用的 system 人设提示词（情绪 / 记忆每轮不同）。"""
        self.system_prompt = prompt

    def clear(self):
        """清空历史（保留人设）。"""
        self.history.clear()

    def save(self, path: str):
        """把聊天记录保存为 JSONL 文件，每行一条消息。"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for msg in self.history:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    def load(self, path: str):
        """从 JSONL 文件加载历史（文件不存在则忽略）。"""
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.history.append(json.loads(line))
                except json.JSONDecodeError:
                    # 跳过损坏行，不影响整体加载
                    continue
