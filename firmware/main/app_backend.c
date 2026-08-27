#include <string.h>
#include <stdlib.h>
#include "esp_log.h"
#include "esp_http_client.h"
#include "cJSON.h"
#include "mbedtls/base64.h"
#include "app_backend.h"

static const char *TAG = "app_backend";

/* 计算 base64 编码后长度（含结尾 '\0'） */
static size_t b64_encode_len(size_t in_len)
{
    return ((in_len + 2) / 3) * 4 + 1;
}

/* 计算 base64 解码后最大长度 */
static size_t b64_decode_len(size_t b64_len)
{
    return (b64_len / 4) * 3 + 3;
}

/*
 * 响应累积 buffer（事件回调里动态增长）。
 * 后端返回的响应含 audio_base64（可能 1~2MB），固定 buffer 装不下，
 * 用事件回调在 HTTP_EVENT_ON_DATA 里累积，任意大小都能正确接收。
 * 单线程使用（voice_task），无需加锁。
 */
static char *g_resp_buf = NULL;
static size_t g_resp_len = 0;
static size_t g_resp_cap = 0;

static esp_err_t http_event_handler(esp_http_client_event_t *evt)
{
    switch (evt->event_id) {
    case HTTP_EVENT_ON_DATA:
        /* 动态扩容，确保能放下本次数据 + 结尾 '\0' */
        if (g_resp_len + evt->data_len + 1 > g_resp_cap) {
            size_t new_cap = g_resp_cap ? g_resp_cap * 2 : 8192;
            while (new_cap < g_resp_len + evt->data_len + 1) {
                new_cap *= 2;
            }
            char *new_buf = realloc(g_resp_buf, new_cap);
            if (new_buf == NULL) {
                ESP_LOGE(TAG, "resp realloc failed");
                return ESP_ERR_NO_MEM;
            }
            g_resp_buf = new_buf;
            g_resp_cap = new_cap;
        }
        memcpy(g_resp_buf + g_resp_len, evt->data, evt->data_len);
        g_resp_len += evt->data_len;
        g_resp_buf[g_resp_len] = '\0';
        break;
    default:
        break;
    }
    return ESP_OK;
}

/**
 * 把音频发送到后端 /voice 接口，得到 ASR 文字 + 回复文字 + TTS 音频。
 *
 * 后端约定（与 Python 后端 main.py 的 /voice 一致）：
 *   请求:  {"audio_base64": "<wav 的 base64>", "audio_format": "wav"}
 *   响应:  {"text": "<回复文字>", "audio_base64": "<wav 的 base64>",
 *           "asr_text": "...", "error": null}
 *
 * 成功返回 ESP_OK，并填充各 out 参数（需用 free 释放）。
 */
esp_err_t app_backend_send_audio(const uint8_t *audio, size_t audio_len,
                                 char **asr_text_out,
                                 char **text_out,
                                 uint8_t **audio_out, size_t *audio_len_out)
{
    esp_err_t ret = ESP_OK;
    char *asr_text = NULL;
    char *text = NULL;
    uint8_t *out_audio = NULL;
    size_t out_audio_len = 0;

    *asr_text_out = NULL;
    *text_out = NULL;
    *audio_out = NULL;
    *audio_len_out = 0;

    /* 1. 音频 → base64 */
    size_t b64_in_len = b64_encode_len(audio_len);
    char *b64_in = calloc(1, b64_in_len);
    if (b64_in == NULL) {
        return ESP_ERR_NO_MEM;
    }
    size_t olen = 0;
    int brc = mbedtls_base64_encode((unsigned char *)b64_in, b64_in_len, &olen,
                                    audio, audio_len);
    if (brc != 0) {
        ESP_LOGE(TAG, "base64 encode failed: %d", brc);
        free(b64_in);
        return ESP_FAIL;
    }

    /* 2. 构造 JSON 请求体 */
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "audio_base64", b64_in);
    cJSON_AddStringToObject(root, "audio_format", "wav");
    char *post_body = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    free(b64_in);
    if (post_body == NULL) {
        return ESP_FAIL;
    }

    /* 3. HTTP POST（事件回调累积响应） */
    char url[256];
    snprintf(url, sizeof(url), "%s/voice", CONFIG_BACKEND_BASE_URL);

    g_resp_len = 0; /* 重置累积长度 */

    esp_http_client_config_t cfg = {
        .url = url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 120000,
        .event_handler = http_event_handler,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client == NULL) {
        free(post_body);
        return ESP_FAIL;
    }
    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, post_body, strlen(post_body));

    esp_err_t err = esp_http_client_perform(client);
    int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    free(post_body);

    if (err != ESP_OK) {
        ESP_LOGE(TAG, "HTTP perform failed: %s", esp_err_to_name(err));
        return err;
    }
    if (status != 200) {
        ESP_LOGE(TAG, "HTTP status %d", status);
        return ESP_FAIL;
    }

    /* 4. 解析累积到的响应 JSON */
    if (g_resp_len == 0 || g_resp_buf == NULL) {
        ESP_LOGE(TAG, "empty response");
        return ESP_FAIL;
    }
    cJSON *jroot = cJSON_Parse(g_resp_buf);
    if (jroot == NULL) {
        ESP_LOGE(TAG, "response parse failed (len %d)", (int)g_resp_len);
        return ESP_FAIL;
    }

    cJSON *jerr = cJSON_GetObjectItem(jroot, "error");
    if (jerr && cJSON_IsString(jerr) && jerr->valuestring != NULL &&
        strlen(jerr->valuestring) > 0) {
        ESP_LOGE(TAG, "backend error: %s", jerr->valuestring);
        cJSON_Delete(jroot);
        return ESP_FAIL;
    }

    /* ASR 识别出的用户原话（屏幕显示"你：..."用） */
    cJSON *jasr = cJSON_GetObjectItem(jroot, "asr_text");
    if (jasr && cJSON_IsString(jasr) && jasr->valuestring != NULL &&
        strlen(jasr->valuestring) > 0) {
        asr_text = strdup(jasr->valuestring);
    }

    cJSON *jtext = cJSON_GetObjectItem(jroot, "text");
    if (jtext && cJSON_IsString(jtext) && jtext->valuestring != NULL) {
        text = strdup(jtext->valuestring);
    }

    cJSON *jaudio = cJSON_GetObjectItem(jroot, "audio_base64");
    if (jaudio && cJSON_IsString(jaudio) && jaudio->valuestring != NULL &&
        strlen(jaudio->valuestring) > 0) {
        /* base64 解码得到 wav 音频字节 */
        size_t b64_len = strlen(jaudio->valuestring);
        size_t dec_max = b64_decode_len(b64_len);
        out_audio = calloc(1, dec_max);
        if (out_audio == NULL) {
            cJSON_Delete(jroot);
            free(text);
            free(asr_text);
            return ESP_ERR_NO_MEM;
        }
        size_t olen2 = 0;
        int drc = mbedtls_base64_decode(out_audio, dec_max, &olen2,
                                        (const unsigned char *)jaudio->valuestring, b64_len);
        if (drc != 0) {
            ESP_LOGE(TAG, "base64 decode failed: %d", drc);
            free(out_audio);
            out_audio = NULL;
        } else {
            out_audio_len = olen2;
        }
    }
    cJSON_Delete(jroot);

    *asr_text_out = asr_text;
    *text_out = text;
    *audio_out = out_audio;
    *audio_len_out = out_audio_len;
    return ret;
}
