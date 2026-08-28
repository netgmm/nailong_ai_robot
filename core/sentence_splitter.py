# -*- coding: utf-8 -*-
"""
流式分句器
------------
把大模型逐 token 吐出的文本切成完整句子，
供语音流水线「切一句、合成一句、播一句」使用，不等整段回复生成完毕。
"""
import re

# 断句标点（中文句号 / 叹号 / 问号 / 省略号 / 分号 + 换行）
_SENT_END = re.compile(r"[。！？…；\n]")

# 无标点时强制切分的最大长度（字），避免一句过长导致 TTS 迟迟不出声
DEFAULT_MAX_LEN = 30


class SentenceSplitter:
    """流式分句器：增量输入 token，输出完整句子。"""

    def __init__(self, max_len: int = DEFAULT_MAX_LEN):
        self.max_len = max_len
        self._buf = ""

    def push(self, text: str) -> list:
        """输入新文本，返回本轮切出的完整句子列表（不含未完成部分）。

        行为：遇到断句标点立即切句；无标点但缓冲超长时硬切，
        避免 LLM 一口气输出长句导致首句出声延迟。
        """
        self._buf += (text or "")
        sentences = []
        while True:
            m = _SENT_END.search(self._buf)
            if m:
                idx = m.end()
                sentences.append(self._buf[:idx].strip())
                self._buf = self._buf[idx:]
            elif len(self._buf) >= self.max_len:
                sentences.append(self._buf[: self.max_len].strip())
                self._buf = self._buf[self.max_len:]
            else:
                break
        return [s for s in sentences if s]

    def flush(self) -> list:
        """流式结束：把剩余缓冲作为最后一句输出（若不为空）。"""
        out = []
        if self._buf.strip():
            out.append(self._buf.strip())
        self._buf = ""
        return out
