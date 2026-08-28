# -*- coding: utf-8 -*-
"""
奶龙情感陪伴AI —— FastAPI 后端服务
====================================
把对话核心封装成 HTTP 服务，供 ESP32-S3-Box-3 等终端调用。

接口：
  POST /chat   输入文字，返回奶龙回复文字 + TTS 音频（base64 编码）
  POST /voice  输入音频（base64），先 ASR 转文字再对话，返回文字 + 音频
  GET  /health 健康检查

运行方式：
  python main.py            # 默认 0.0.0.0:8000
  uvicorn main:app --host 0.0.0.0 --port 8000
"""
import asyncio
import base64
import json
import sys
import threading

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from core.config import (
    ConfigError,
    get_asr_config,
    get_emotion_config,
    get_llm_config,
    get_memory_config,
    get_tts_config,
    load_config,
)
from core.conversation import Conversation
from core.emotion import EmotionalState
from core.llm_client import LLMClient, LLMError
from core.memory import MemoryStore, extract_facts
from core.personality import build_system_prompt, resolve_system_prompt
from core.sentence_splitter import SentenceSplitter
from interfaces.asr import recognize_bytes, warmup
from interfaces.tts import synthesize_speech

app = FastAPI(title="奶龙情感陪伴AI", version="1.0.0")


# ---------- 全局状态（单用户陪伴机器人，常驻内存） ----------
_client = None
_conv = None
_memory_store = None
_emotional_state = None
_base_prompt = ""
_mem_cfg = {}
_emo_cfg = {}
_tts_cfg = {}
_asr_cfg = {}
_lock = threading.Lock()


def _init():
    """加载配置并初始化各模块（启动时执行一次）。"""
    global _client, _conv, _memory_store, _emotional_state
    global _base_prompt, _mem_cfg, _emo_cfg, _tts_cfg, _asr_cfg

    config = load_config()
    _client = LLMClient(**get_llm_config(config))
    _base_prompt = resolve_system_prompt(config)
    _mem_cfg = get_memory_config(config)
    _emo_cfg = get_emotion_config(config)
    _tts_cfg = get_tts_config(config)
    _asr_cfg = get_asr_config(config)

    _conv = Conversation(system_prompt=_base_prompt)
    _memory_store = MemoryStore(_mem_cfg["path"], _mem_cfg["max_items"]) if _mem_cfg["enabled"] else None
    _emotional_state = EmotionalState(_emo_cfg["baseline"], _emo_cfg["decay"]) if _emo_cfg["enabled"] else None

    # 预热 ASR 模型：提前加载 faster-whisper，避免首次语音请求因加载模型而超时
    if _asr_cfg["enabled"]:
        try:
            warmup(_asr_cfg["model_size"], _asr_cfg["device"], _asr_cfg["compute_type"])
            print("[预热] ASR 模型已加载完成")
        except Exception as e:
            print(f"[预热] ASR 模型加载失败（首次请求时会重试）：{e}")


# 启动即初始化；配置错误则友好退出
try:
    _init()
except ConfigError as e:
    print(f"[配置错误] {e}")
    sys.exit(1)


# ---------- 数据模型 ----------
class ChatRequest(BaseModel):
    text: str


class VoiceRequest(BaseModel):
    audio_base64: str
    # 可选：音频格式后缀（.wav / .mp3 等），需与 audio_base64 解码后的实际格式一致
    audio_format: str = "wav"


class ChatResponse(BaseModel):
    text: str = ""            # 奶龙回复文字
    audio_base64: str | None = None   # 回复的 TTS 音频（base64）
    asr_text: str | None = None       # 语音接口返回：识别出的用户文字
    error: str | None = None


# ---------- 内部工具 ----------
def _run_chat(user_input: str) -> str:
    """执行一轮对话，返回奶龙回复文字。调用方需已持有 _lock。"""
    _conv.add_user(user_input)

    # 动态情绪：先根据本轮输入更新，再生成描述
    emotion_desc = ""
    if _emotional_state:
        _emotional_state.update(user_input)
        emotion_desc = _emotional_state.describe()

    # 长期记忆：检索与当前输入最相关的记忆
    memories = _memory_store.retrieve(user_input, _mem_cfg["top_k"]) if _memory_store else []

    # 动态组装 system 提示词（人设 + 情绪 + 记忆）
    _conv.set_system_prompt(build_system_prompt(_base_prompt, emotion_desc, memories))

    # 调用大模型，捕获可预期错误
    try:
        reply = _client.chat(_conv.get_messages())
    except LLMError as e:
        # 回滚刚加入的用户消息，避免污染上下文
        if _conv.history and _conv.history[-1]["role"] == "user":
            _conv.history.pop()
        raise

    _conv.add_assistant(reply)

    # 抽取本轮事实，写入长期记忆（失败静默）
    if _memory_store:
        for fact in extract_facts(_client, user_input, reply):
            _memory_store.add_fact(fact["content"], fact["importance"])

    return reply


def _run_chat_stream(user_input: str):
    """流式执行一轮对话：逐 token 产出回复文本增量。

    与 _run_chat 的【核心业务逻辑完全一致】（记忆检索 / 情绪更新 / 人设组装 /
    失败回滚 / 事实抽取写入），只是 LLM 调用改为 stream=True 逐 token 产出。
    调用方需已持有 _lock。

    产出:
        str: 回复文本增量（每个 token 一段）
    """
    _conv.add_user(user_input)

    # 动态情绪：先根据本轮输入更新，再生成描述
    emotion_desc = ""
    if _emotional_state:
        _emotional_state.update(user_input)
        emotion_desc = _emotional_state.describe()

    # 长期记忆：检索与当前输入最相关的记忆
    memories = _memory_store.retrieve(user_input, _mem_cfg["top_k"]) if _memory_store else []

    # 动态组装 system 提示词（人设 + 情绪 + 记忆）
    _conv.set_system_prompt(build_system_prompt(_base_prompt, emotion_desc, memories))

    # 流式调用大模型，捕获可预期错误
    try:
        reply_parts = []
        for token in _client.chat_stream(_conv.get_messages()):
            reply_parts.append(token)
            yield token
    except LLMError as e:
        # 回滚刚加入的用户消息，避免污染上下文
        if _conv.history and _conv.history[-1]["role"] == "user":
            _conv.history.pop()
        raise

    reply = "".join(reply_parts)
    _conv.add_assistant(reply)

    # 抽取本轮事实，写入长期记忆（失败静默）
    if _memory_store:
        for fact in extract_facts(_client, user_input, reply):
            _memory_store.add_fact(fact["content"], fact["importance"])


def _synthesize_audio(reply: str) -> bytes | None:
    """把回复文字合成为 TTS 音频，返回 WAV 字节；失败或未启用返回 None。"""
    if not _tts_cfg["enabled"]:
        return None
    try:
        return synthesize_speech(
            reply,
            api_url=_tts_cfg["api_url"],
            ref_audio_path=_tts_cfg["ref_audio_path"],
            prompt_text=_tts_cfg["prompt_text"],
            prompt_language=_tts_cfg["prompt_language"],
            text_language=_tts_cfg["text_language"],
            timeout=_tts_cfg["timeout"],
        )
    except Exception:
        return None


def _synthesize(reply: str) -> str | None:
    """把回复文字合成为 TTS 音频，返回 base64；失败或未启用返回 None。"""
    audio = _synthesize_audio(reply)
    return base64.b64encode(audio).decode("ascii") if audio else None


# ---------- 接口 ----------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    user_input = (req.text or "").strip()
    if not user_input:
        return ChatResponse(text="", error="text 不能为空")

    with _lock:
        try:
            reply = _run_chat(user_input)
        except LLMError as e:
            return ChatResponse(text="", error=str(e))

    return ChatResponse(text=reply, audio_base64=_synthesize(reply))


def _debug_save_voice(audio_data: bytes):
    """调试辅助：保存后端收到的音频并打印响度(RMS/峰值)，用于排查「识别为空」。

    判别标准：
      - RMS 接近 0（如 < 100）：麦克风录到的是静音/坏通道，问题在录音端；
      - RMS 有明显数值（几百~上万）：音频有内容，问题在 ASR/格式。
    """
    import os
    import wave
    import array
    try:
        os.makedirs("data", exist_ok=True)
        path = os.path.join("data", "debug_voice.wav")
        with open(path, "wb") as f:
            f.write(audio_data)
        with wave.open(path, "rb") as w:
            n = w.getnframes()
            ch = w.getnchannels()
            sw = w.getsampwidth()
            raw = w.readframes(n)
        rms = 0
        peak = 0
        if sw == 2 and n > 0:
            samples = array.array("h", raw)
            rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
            peak = max((abs(s) for s in samples), default=0)
        print(f"[调试] 音频已存 data/debug_voice.wav | 帧数={n} 声道={ch} 位宽={sw} | RMS={rms:.1f} 峰值={peak}")
    except Exception as e:
        print(f"[调试] 保存/分析音频失败: {e}")


@app.post("/voice", response_model=ChatResponse)
def voice(req: VoiceRequest):
    # 1. 解码音频字节
    try:
        audio_data = base64.b64decode(req.audio_base64)
    except Exception:
        return ChatResponse(text="", error="audio_base64 解码失败")

    if not audio_data:
        return ChatResponse(text="", error="音频数据为空")

    _debug_save_voice(audio_data)

    # 2. ASR 转文字（本地 faster-whisper，首次会加载模型，较慢）
    if not _asr_cfg["enabled"]:
        return ChatResponse(text="", error="语音输入未启用，请在 config.yaml 开启 asr.enabled")

    suffix = "." + (req.audio_format or "wav").lstrip(".")
    try:
        user_input = recognize_bytes(
            audio_data,
            suffix=suffix,
            model_size=_asr_cfg["model_size"],
            device=_asr_cfg["device"],
            compute_type=_asr_cfg["compute_type"],
            language=_asr_cfg["language"],
        ).strip()
    except Exception as e:
        return ChatResponse(text="", error=f"语音识别失败：{e}")

    if not user_input:
        return ChatResponse(text="", error="未识别到有效语音内容", asr_text="")

    # 3. 走正常对话流程
    with _lock:
        try:
            reply = _run_chat(user_input)
        except LLMError as e:
            return ChatResponse(asr_text=user_input, text="", error=str(e))

    return ChatResponse(text=reply, audio_base64=_synthesize(reply), asr_text=user_input)


# ---------- WebSocket 流式端点（降低语音对话延迟） ----------

async def _handle_voice_round(ws: WebSocket, audio_data: bytes):
    """处理一轮语音：ASR → 流式对话 → 分句 TTS → 逐句二进制下发。"""
    # 1. ASR 转文字（CPU 密集，丢线程池）
    def _recognize():
        return recognize_bytes(
            audio_data,
            suffix=".wav",
            model_size=_asr_cfg["model_size"],
            device=_asr_cfg["device"],
            compute_type=_asr_cfg["compute_type"],
            language=_asr_cfg["language"],
        ).strip()

    try:
        user_input = await asyncio.to_thread(_recognize)
    except Exception as e:
        await ws.send_text(json.dumps({"type": "error", "message": f"语音识别失败：{e}"}))
        return

    if not user_input:
        await ws.send_text(json.dumps({"type": "error", "message": "未识别到有效语音内容"}))
        return
    await ws.send_text(json.dumps({"type": "asr", "text": user_input}))

    # 2. 流式对话 + 分句 + 逐句合成
    out_q = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _producer():
        """线程内：LLM 逐 token 产出 → 分句器切句 → 塞入 asyncio 队列。"""
        splitter = SentenceSplitter()

        def emit(item):
            loop.call_soon_threadsafe(out_q.put_nowait, item)

        try:
            with _lock:
                for token in _run_chat_stream(user_input):
                    for sent in splitter.push(token):
                        emit(("sentence", sent))
                for sent in splitter.flush():
                    emit(("sentence", sent))
        except LLMError as e:
            emit(("error", str(e)))
        finally:
            emit(("done", None))

    producer_task = asyncio.create_task(asyncio.to_thread(_producer))

    # 3. 消费：每句合成 TTS 立即二进制下发（合成与 LLM 生成并行）
    while True:
        kind, payload = await out_q.get()
        if kind == "done":
            break
        if kind == "error":
            await ws.send_text(json.dumps({"type": "error", "message": payload}))
            break
        # kind == "sentence"
        sentence = payload
        if len(sentence) < 2:
            continue  # 过短句子不合成，避免 GPT-SoVITS 异常
        await ws.send_text(json.dumps({"type": "sentence", "text": sentence}))
        audio = await asyncio.to_thread(_synthesize_audio, sentence)
        if audio:
            await ws.send_bytes(audio)

    await producer_task
    await ws.send_text(json.dumps({"type": "end"}))


@app.websocket("/ws/voice")
async def ws_voice(ws: WebSocket):
    """语音流式端点。

    客户端协议（文本帧 / 二进制帧混用）：
      - 文本帧 {"type":"start"}           开始新一段录音缓冲
      - 二进制帧                          音频分片（WAV 格式，累积到缓冲）
      - 文本帧 {"type":"end"}             该段说完，触发识别与流式回复

    服务端下发：
      - 文本帧 {"type":"asr","text":...}            识别出的用户文字
      - 文本帧 {"type":"sentence","text":...}        切出的一句话
      - 二进制帧                                    该句的 TTS WAV 音频
      - 文本帧 {"type":"error","message":...}        出错
      - 文本帧 {"type":"end"}                        本轮结束
    """
    await ws.accept()
    audio_buf = bytearray()
    try:
        while True:
            message = await ws.receive()
            mtype = message.get("type", "")
            if mtype == "websocket.disconnect":
                break
            if mtype == "websocket.receive":
                if message.get("bytes") is not None:
                    audio_buf.extend(message["bytes"])
                elif message.get("text") is not None:
                    try:
                        data = json.loads(message["text"])
                    except json.JSONDecodeError:
                        continue
                    cmd = data.get("type")
                    if cmd == "start":
                        audio_buf.clear()
                    elif cmd == "end":
                        if audio_buf:
                            await _handle_voice_round(ws, bytes(audio_buf))
                        audio_buf.clear()
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await ws.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
