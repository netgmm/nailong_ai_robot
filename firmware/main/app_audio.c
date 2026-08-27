#include <string.h>
#include <stdlib.h>
#include <math.h>
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "bsp/esp-bsp.h"
#include "esp_codec_dev.h"
#include "app_audio.h"

static const char *TAG = "app_audio";

/* 标准 44 字节 PCM WAV 头 */
#pragma pack(push, 1)
typedef struct {
    char     riff[4];       /* "RIFF" */
    uint32_t chunk_size;    /* 36 + data_size */
    char     wave[4];       /* "WAVE" */
    char     fmt[4];        /* "fmt " */
    uint32_t fmt_size;      /* 16 */
    uint16_t audio_format;  /* 1 = PCM */
    uint16_t channels;      /* 1 */
    uint32_t sample_rate;   /* 32000 */
    uint32_t byte_rate;     /* sample_rate * channels * bits/8 */
    uint16_t block_align;   /* channels * bits/8 */
    uint16_t bits;          /* 16 */
    char     data[4];       /* "data" */
    uint32_t data_size;     /* PCM 字节数 */
} wav_header_t;
#pragma pack(pop)

/* 扬声器（ES8311）与麦克风（ES7210）codec 设备句柄 */
static esp_codec_dev_handle_t s_spk = NULL;
static esp_codec_dev_handle_t s_mic = NULL;

esp_err_t app_audio_init(void)
{
    /* I2C 总线（codec 配置用） */
    bsp_i2c_init();

    /* 初始化 I2S 外设（默认 16bit 双工） */
    esp_err_t ret = bsp_audio_init(NULL);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "bsp_audio_init failed: %s", esp_err_to_name(ret));
        return ret;
    }

    /* 扬声器与麦克风 codec 设备 */
    s_spk = bsp_audio_codec_speaker_init();
    s_mic = bsp_audio_codec_microphone_init();
    if (s_spk == NULL || s_mic == NULL) {
        ESP_LOGE(TAG, "codec init failed");
        return ESP_FAIL;
    }
    esp_codec_dev_set_out_vol(s_spk, 60);
    /* 麦克风输入增益：30dB（ES7210 默认）。之前设 70 会被钳到最大 37.5dB，太敏感、易捡底噪和回声 */
    esp_codec_dev_set_in_gain(s_mic, 30.0);

    /*
     * 关键：open 一次、之后复用，绝不反复 open/close。
     * esp_codec_dev 1.1.0 的 open 内部会先无条件 disable I2S 通道再配置，
     * 而 v5.5.5 对已 disable 的通道再 disable 会直接报错。反复 open/close
     * 会在第二轮触发 "the channel has not been enabled yet" 崩溃。
     *
     * 麦克风（ES7210 双麦克风）用 stereo（2 通道），录音时手动抽取右声道（MIC2，
     * 左声道 MIC1 实测静音）；扬声器用 stereo（2 通道）。
     */
    esp_codec_dev_sample_info_t mic_fs = {
        .sample_rate = AUDIO_SAMPLE_RATE,
        .channel = 2,
        .bits_per_sample = AUDIO_BITS,
    };
    esp_codec_dev_sample_info_t spk_fs = {
        .sample_rate = AUDIO_SAMPLE_RATE,
        .channel = 2,
        .bits_per_sample = AUDIO_BITS,
    };
    if (esp_codec_dev_open(s_mic, &mic_fs) != 0) {
        ESP_LOGE(TAG, "mic open failed");
        return ESP_FAIL;
    }
    if (esp_codec_dev_open(s_spk, &spk_fs) != 0) {
        ESP_LOGE(TAG, "spk open failed");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "audio ready (%d Hz)", (int)AUDIO_SAMPLE_RATE);
    return ESP_OK;
}

static void wav_header_fill(wav_header_t *h, uint32_t data_size)
{
    memset(h, 0, sizeof(*h));
    memcpy(h->riff, "RIFF", 4);
    memcpy(h->wave, "WAVE", 4);
    memcpy(h->fmt, "fmt ", 4);
    memcpy(h->data, "data", 4);
    h->fmt_size = 16;
    h->audio_format = 1;
    h->channels = AUDIO_CHANNELS;
    h->sample_rate = AUDIO_SAMPLE_RATE;
    h->bits = AUDIO_BITS;
    h->byte_rate = h->sample_rate * h->channels * h->bits / 8;
    h->block_align = h->channels * h->bits / 8;
    h->data_size = data_size;
    h->chunk_size = 36 + data_size;
}

/* 读一段 stereo 音频，抽取右声道（MIC2），返回原始单声道 PCM（16bit，无 WAV 头）。
 * 供连续录音使用：循环调用，把每段 PCM 追加到总缓冲。 */
static esp_err_t record_mono_chunk(uint32_t duration_ms, uint8_t **out_pcm, size_t *out_pcm_len)
{
    *out_pcm = NULL;
    *out_pcm_len = 0;
    if (s_mic == NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    size_t sample_count = (size_t)AUDIO_SAMPLE_RATE * duration_ms / 1000;
    size_t mono_bytes = sample_count * (AUDIO_BITS / 8);
    size_t stereo_bytes = sample_count * (AUDIO_BITS / 8) * 2;

    /* 读 stereo 数据（ES7210 双麦克风，2 通道交错 L R L R...） */
    uint8_t *stereo_buf = calloc(1, stereo_bytes);
    if (stereo_buf == NULL) {
        return ESP_ERR_NO_MEM;
    }
    size_t got = 0;
    while (got < stereo_bytes) {
        size_t chunk = (stereo_bytes - got) > 4096 ? 4096 : (stereo_bytes - got);
        int rc = esp_codec_dev_read(s_mic, stereo_buf + got, (int)chunk);
        if (rc != 0) {
            ESP_LOGW(TAG, "codec read: %d", rc);
            break;
        }
        got += chunk;
    }

    /* 调试：左右声道 RMS/峰值（连续录音时每块都打印，可看实时响度） */
    {
        int64_t sum_l = 0, sum_r = 0;
        int peak_l = 0, peak_r = 0;
        for (size_t i = 0; i < sample_count; i++) {
            int16_t l = (int16_t)((uint16_t)stereo_buf[i * 4] | ((uint16_t)stereo_buf[i * 4 + 1] << 8));
            int16_t r = (int16_t)((uint16_t)stereo_buf[i * 4 + 2] | ((uint16_t)stereo_buf[i * 4 + 3] << 8));
            sum_l += (int64_t)l * l;
            sum_r += (int64_t)r * r;
            int al = l < 0 ? -l : l;
            int ar = r < 0 ? -r : r;
            if (al > peak_l) peak_l = al;
            if (ar > peak_r) peak_r = ar;
        }
        int rms_l = (int)sqrt((double)sum_l / (double)sample_count);
        int rms_r = (int)sqrt((double)sum_r / (double)sample_count);
        ESP_LOGW(TAG, "[debug] 左声道 RMS=%d 峰值=%d | 右声道 RMS=%d 峰值=%d",
                 rms_l, peak_l, rms_r, peak_r);
    }

    /* 抽取右声道（MIC2）：每 4 字节（L_lo L_hi R_lo R_hi）取后 2 字节 */
    uint8_t *pcm = malloc(mono_bytes);
    if (pcm == NULL) {
        free(stereo_buf);
        return ESP_ERR_NO_MEM;
    }
    for (size_t i = 0; i < sample_count; i++) {
        pcm[i * 2]     = stereo_buf[i * 4 + 2];
        pcm[i * 2 + 1] = stereo_buf[i * 4 + 3];
    }
    free(stereo_buf);

    *out_pcm = pcm;
    *out_pcm_len = mono_bytes;
    return ESP_OK;
}

esp_err_t app_audio_read_mono(uint32_t duration_ms, uint8_t **out_buf, size_t *out_len)
{
    return record_mono_chunk(duration_ms, out_buf, out_len);
}

esp_err_t app_audio_wrap_wav(const uint8_t *pcm, size_t pcm_len, uint8_t **out_buf, size_t *out_len)
{
    *out_buf = NULL;
    *out_len = 0;
    size_t total = sizeof(wav_header_t) + pcm_len;
    uint8_t *buf = malloc(total);
    if (buf == NULL) {
        return ESP_ERR_NO_MEM;
    }
    wav_header_fill((wav_header_t *)buf, (uint32_t)pcm_len);
    if (pcm_len > 0) {
        memcpy(buf + sizeof(wav_header_t), pcm, pcm_len);
    }
    *out_buf = buf;
    *out_len = total;
    return ESP_OK;
}

esp_err_t app_audio_record(uint32_t duration_ms, uint8_t **out_buf, size_t *out_len)
{
    uint8_t *pcm = NULL;
    size_t pcm_len = 0;
    esp_err_t ret = record_mono_chunk(duration_ms, &pcm, &pcm_len);
    if (ret != ESP_OK) {
        return ret;
    }
    ret = app_audio_wrap_wav(pcm, pcm_len, out_buf, out_len);
    free(pcm);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "recorded %d samples (%d ms)", (int)(pcm_len / (AUDIO_BITS / 8)), (int)duration_ms);
    }
    return ret;
}

esp_err_t app_audio_play_wav(const uint8_t *data, size_t len)
{
    if (len < sizeof(wav_header_t)) {
        ESP_LOGE(TAG, "audio too short");
        return ESP_ERR_INVALID_ARG;
    }
    if (s_spk == NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    /*
     * GPT-SoVITS 输出 mono（16bit），但扬声器是 stereo（2 通道）。
     * 需把 mono 复制成 stereo（左右声道相同），否则 slot 宽度不匹配会导致音调变尖。
     */
    const uint8_t *mono = data + sizeof(wav_header_t);
    size_t mono_len = len - sizeof(wav_header_t);
    size_t mono_samples = mono_len / 2;   /* 每样本 2 字节 */

    /* 分块复制 mono → stereo（每块 2048 样本，避免大内存占用） */
    const size_t chunk_samples = 2048;
    uint8_t *stereo_chunk = malloc(chunk_samples * 4);
    if (stereo_chunk == NULL) {
        return ESP_ERR_NO_MEM;
    }

    size_t done = 0;
    while (done < mono_samples) {
        size_t n = mono_samples - done;
        if (n > chunk_samples) {
            n = chunk_samples;
        }
        for (size_t i = 0; i < n; i++) {
            stereo_chunk[i * 4]     = mono[(done + i) * 2];
            stereo_chunk[i * 4 + 1] = mono[(done + i) * 2 + 1];
            stereo_chunk[i * 4 + 2] = mono[(done + i) * 2];
            stereo_chunk[i * 4 + 3] = mono[(done + i) * 2 + 1];
        }
        int rc = esp_codec_dev_write(s_spk, stereo_chunk, (int)(n * 4));
        if (rc != 0) {
            ESP_LOGW(TAG, "codec write: %d", rc);
            break;
        }
        done += n;
    }
    free(stereo_chunk);

    ESP_LOGI(TAG, "played %d samples", (int)done);
    return ESP_OK;
}
