# -*- coding: utf-8 -*-
"""
长期记忆模块
--------------
借鉴 ai-friend 的记忆系统思路，做精简落地：
从对话中抽取「值得记住的事实」，存到本地 JSON，
每轮按相关性检索注入，避免把所有历史都塞进上下文。

- 存储：本地 JSON 文件（标准库，零额外依赖）
- 检索：字符 bigram 重叠相似度（轻量，无需分词 / 向量库）
- 抽取：复用现有大模型接口（可开关）
"""
import json
import os
import time


class MemoryStore:
    """长期记忆存储（JSON 文件，内存缓存 + 落盘）。"""

    def __init__(self, path: str, max_items: int = 200):
        self.path = path
        self.max_items = max_items
        # 记忆条目：[{"content": str, "importance": float, "ts": float}]
        self.items = []
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.items = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.items = []

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.items, f, ensure_ascii=False, indent=2)

    def add_fact(self, content: str, importance: float = 0.5):
        """新增一条记忆（内容去重，超上限时按重要性裁剪）。"""
        content = (content or "").strip()
        if not content:
            return
        if any(item["content"] == content for item in self.items):
            return
        self.items.append({
            "content": content,
            "importance": max(0.0, min(1.0, float(importance))),
            "ts": time.time(),
        })
        if len(self.items) > self.max_items:
            # 优先保留重要性高、时间新的条目
            self.items.sort(key=lambda x: x["importance"], reverse=True)
            self.items = self.items[: self.max_items]
        self.save()

    def retrieve(self, query: str, top_k: int = 3) -> list:
        """返回与 query 最相关的记忆内容列表。"""
        if not query or not self.items:
            return []
        scored = [(self._similarity(query, it["content"]), it) for it in self.items]
        scored.sort(key=lambda x: (x[0], x[1]["importance"]), reverse=True)
        return [it["content"] for s, it in scored[:top_k] if s > 0.05]

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        """字符 bigram 重叠相似度（0~1），轻量检索。"""

        def bigrams(s):
            s = s.replace(" ", "")
            return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}

        ga, gb = bigrams(a), bigrams(b)
        if not ga or not gb:
            return 0.0
        return len(ga & gb) / max(len(ga), len(gb))


# 抽取事实用的提示词（{text} 为待替换的对话内容）
EXTRACT_PROMPT = """你是记忆整理助手。请从下面这段对话中抽取值得长期记住的、关于用户的事实或偏好（例如名字、喜好、身份、重要事件、情绪状态等）。

要求：
1. 只输出 JSON 数组，不要任何解释；
2. 数组元素格式：{"content": "事实内容", "importance": 0.0 到 1.0 之间的小数}；
3. 没有值得记住的内容就输出 []。

对话内容：
{text}"""


def extract_facts(client, user_text: str, assistant_text: str) -> list:
    """用大模型从一轮对话中抽取事实。

    参数:
        client: LLMClient 实例
        user_text: 用户本轮输入
        assistant_text: 奶龙本轮回复

    返回:
        list: [{"content": str, "importance": float}]；失败时返回空列表（不抛异常）
    """
    text = f"用户：{user_text}\n奶龙：{assistant_text}"
    prompt = EXTRACT_PROMPT.replace("{text}", text)
    try:
        raw = client.chat([{"role": "user", "content": prompt}]).strip()
        # 去掉可能的 markdown 代码块包裹
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        start, end = raw.find("["), raw.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        data = json.loads(raw[start:end + 1])
        if not isinstance(data, list):
            return []
        result = []
        for item in data:
            if isinstance(item, dict) and item.get("content"):
                result.append({
                    "content": str(item["content"]).strip(),
                    "importance": float(item.get("importance", 0.5)),
                })
        return result
    except Exception:
        # 抽取失败不影响主流程
        return []
