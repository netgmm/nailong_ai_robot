# -*- coding: utf-8 -*-
"""
情绪状态模块
--------------
借鉴 ai-friend 的情绪系统思路，做精简落地：
维护一个动态情绪状态（效价 valence + 连续负面计数「破防」），
每轮根据用户输入的情感倾向更新（带向基线的衰减），
并把当前情绪翻译成自然语言，动态注入人设提示词，影响回复语气。

为保持轻量、零额外依赖，本模块用内置情感词表做规则判断，
不额外调用大模型（如需更精准，可自行替换为 LLM 情感分析）。
"""

# 正向情感词
POSITIVE_WORDS = {
    "开心", "高兴", "喜欢", "爱你", "爱死", "太好了", "好棒", "棒", "赞",
    "可爱", "哈哈", "嘿嘿", "嘻嘻", "谢谢", "想你", "亲亲", "抱抱",
    "真棒", "厉害", "辛苦啦", "好耶", "耶", "棒棒", "暖", "治愈",
    "太棒", "绝了", "好喜欢", "爱了", "棒极了",
}

# 负向情感词
NEGATIVE_WORDS = {
    "难过", "伤心", "哭", "委屈", "生气", "烦", "讨厌", "累", "压力",
    "焦虑", "崩溃", "失望", "孤单", "寂寞", "害怕", "担心", "痛苦",
    "不开心", "难受", "气死", "烦死", "想哭", "沮丧", "低落", "抑郁",
    "烦躁", "不要", "哼", "呜呜", "555", "好烦", "好累",
}

# 强调副词（加强情感强度）
INTENSIFIERS = {"太", "好", "超级", "特别", "非常", "真的", "超", "死", "极了"}


class EmotionalState:
    """奶龙的动态情绪状态（精简版）。"""

    def __init__(self, baseline: float = 0.2, decay: float = 0.3):
        self.baseline = baseline          # 情绪基线（奶龙偏乐观，略为正）
        self.decay = decay                # 每轮向基线回归的比例
        self.valence = baseline           # 效价：-1（难过）~ +1（开心）
        self.consecutive_negative = 0     # 连续负面交互计数（驱动破防）

    def update(self, user_text: str):
        """根据用户输入更新情绪状态。"""
        sentiment = self._sentiment(user_text)  # -1 ~ +1

        # 向基线衰减 + 本轮情感影响
        self.valence = self._clamp(
            self.valence + (self.baseline - self.valence) * self.decay + sentiment * 0.4
        )

        # 连续负面计数（借鉴 ai-friend 破防机制）
        if sentiment < -0.3:
            self.consecutive_negative += 1
        elif sentiment > 0.3:
            self.consecutive_negative = max(0, self.consecutive_negative - 1)

    def describe(self) -> str:
        """返回当前情绪的自然语言描述，用于注入人设提示词。"""
        # 破防优先
        if self.consecutive_negative >= 5:
            return "奶龙连续被怼了好几次，委屈得要哭了，说话带哭腔、软软地撒娇。"
        v = self.valence
        if v >= 0.6:
            return "奶龙现在特别开心，活力满满，语气雀跃。"
        if v >= 0.2:
            return "奶龙心情不错，软萌轻快。"
        if v > -0.2:
            return "奶龙心情平静，温柔安稳。"
        if v > -0.6:
            return "奶龙有点低落，需要被安慰，语气软软的。"
        return "奶龙很难过、委屈，声音闷闷的，想被抱抱。"

    def _sentiment(self, text: str) -> float:
        """规则法：统计正负情感词，返回 -1~1 的倾向值。"""
        pos = sum(1 for w in POSITIVE_WORDS if w in text)
        neg = sum(1 for w in NEGATIVE_WORDS if w in text)
        if pos == 0 and neg == 0:
            return 0.0
        boost = 1.0 + (0.3 if any(w in text for w in INTENSIFIERS) else 0.0)
        raw = (pos - neg) / float(pos + neg)
        return self._clamp(raw * boost)

    @staticmethod
    def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, x))
