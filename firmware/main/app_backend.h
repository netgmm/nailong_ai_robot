#pragma once
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 把录音音频发送到后端 /voice，返回 ASR 识别文字、回复文字与 TTS 音频。
 *
 * @param audio         录音得到的 WAV 字节（含 WAV 头）
 * @param audio_len     音频字节数
 * @param asr_text_out  [out] ASR 识别出的用户原话（调用方负责 free），可能为 NULL
 * @param text_out      [out] 回复文字（调用方负责 free），可能为 NULL
 * @param audio_out     [out] TTS 音频字节（调用方负责 free），可能为 NULL
 * @param audio_len_out [out] TTS 音频字节数
 *
 * @return ESP_OK 成功；否则失败
 */
esp_err_t app_backend_send_audio(const uint8_t *audio, size_t audio_len,
                                 char **asr_text_out,
                                 char **text_out,
                                 uint8_t **audio_out, size_t *audio_len_out);

#ifdef __cplusplus
}
#endif
