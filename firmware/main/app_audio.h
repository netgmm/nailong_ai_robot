#pragma once
#include <stdint.h>
#include <stddef.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* 录音/播放采样率：32kHz（与 GPT-SoVITS 输出一致，共享 I2S 时钟需统一）。
 * 后端 faster-whisper 会自动重采样到 16k 识别，不受影响。 */
#define AUDIO_SAMPLE_RATE   (32000)
#define AUDIO_BITS          (16)
#define AUDIO_CHANNELS      (1)

/**
 * 初始化音频 codec（ES8311 输出 + ES7210 输入）。
 * 必须在使用录音/播放前调用。
 */
esp_err_t app_audio_init(void);

/**
 * 录制一段固定时长的语音，返回带 WAV 头的 PCM 音频（16k/16bit/mono）。
 *
 * @param duration_ms  录音时长（毫秒）
 * @param out_buf      [out] 音频字节，调用方用 free 释放
 * @param out_len      [out] 音频字节数
 */
esp_err_t app_audio_record(uint32_t duration_ms, uint8_t **out_buf, size_t *out_len);

/**
 * 读取一段单声道 PCM（16bit，右声道 MIC2，不含 WAV 头）。
 * 用于连续录音：循环调用，把每段 PCM 追加到总缓冲。
 */
esp_err_t app_audio_read_mono(uint32_t duration_ms, uint8_t **out_buf, size_t *out_len);

/**
 * 把原始单声道 PCM（16bit）包装成标准 44 字节 WAV 头 + PCM。
 *
 * @param pcm      原始 PCM 数据
 * @param pcm_len  PCM 字节数
 * @param out_buf  [out] 包装后的 WAV 字节，调用方用 free 释放
 * @param out_len  [out] WAV 字节数
 */
esp_err_t app_audio_wrap_wav(const uint8_t *pcm, size_t pcm_len, uint8_t **out_buf, size_t *out_len);

/**
 * 播放一段 WAV 音频（16k/16bit/mono）。
 * 传入的 data 必须带标准 44 字节 WAV 头。
 */
esp_err_t app_audio_play_wav(const uint8_t *data, size_t len);

#ifdef __cplusplus
}
#endif
