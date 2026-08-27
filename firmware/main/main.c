#include <string.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_err.h"
#include "nvs_flash.h"
#include "bsp/esp-bsp.h"
#include "iot_button.h"
#include "app_wifi.h"
#include "app_audio.h"
#include "app_backend.h"
#include "app_display.h"

static const char *TAG = "main";

/* 连续录音参数 */
#define RECORD_CHUNK_MS  500     /* 每块录音时长（毫秒），越小停止响应越快 */
#define RECORD_MAX_MS    30000   /* 最大录音时长，防止忘记按结束 */

/* 按键触发录音：配置键（GPIO0/boot 键）按一下开始录，再按一下结束。 */
static bool s_recording = false;

static void record_btn_click(void *btn_handle, void *usr_data)
{
    s_recording = !s_recording;   /* 切换录音状态 */
}

static void voice_task(void *arg)
{
    while (1) {
        /* 等待单击开始录音 */
        if (!s_recording) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }

        if (!app_wifi_connected()) {
            ESP_LOGW(TAG, "wifi not connected, skip");
            app_display_set_status("网络未连接");
            s_recording = false;   /* 没网就复位，避免卡在录音态 */
            vTaskDelay(pdMS_TO_TICKS(200));
            continue;
        }

        ESP_LOGI(TAG, "start recording...");
        app_display_set_status("听你说话...（再按一次结束）");

        /* 1. 连续录音：直到再次单击（s_recording 变 false）或达到最大时长 */
        uint8_t *pcm = NULL;
        size_t pcm_len = 0;
        uint32_t recorded_ms = 0;
        while (s_recording && recorded_ms < RECORD_MAX_MS) {
            uint8_t *chunk = NULL;
            size_t chunk_len = 0;
            if (app_audio_read_mono(RECORD_CHUNK_MS, &chunk, &chunk_len) != ESP_OK || chunk == NULL) {
                break;
            }
            uint8_t *np = realloc(pcm, pcm_len + chunk_len);
            if (np == NULL) {
                free(chunk);
                free(pcm);
                pcm = NULL;
                pcm_len = 0;
                break;
            }
            pcm = np;
            memcpy(pcm + pcm_len, chunk, chunk_len);
            pcm_len += chunk_len;
            free(chunk);
            recorded_ms += RECORD_CHUNK_MS;
        }
        ESP_LOGI(TAG, "stop recording, pcm %d bytes (%d ms)", (int)pcm_len, (int)recorded_ms);

        /* 组装成 WAV 再发送 */
        if (pcm == NULL || pcm_len == 0) {
            ESP_LOGE(TAG, "record failed");
            app_display_set_status("录音失败");
            vTaskDelay(pdMS_TO_TICKS(300));
            continue;
        }
        uint8_t *audio = NULL;
        size_t audio_len = 0;
        esp_err_t ret = app_audio_wrap_wav(pcm, pcm_len, &audio, &audio_len);
        free(pcm);
        if (ret != ESP_OK || audio == NULL) {
            ESP_LOGE(TAG, "wrap wav failed");
            app_display_set_status("录音失败");
            vTaskDelay(pdMS_TO_TICKS(300));
            continue;
        }

        /* 2. 发送到后端 /voice */
        char *asr_text = NULL;
        char *reply_text = NULL;
        uint8_t *reply_audio = NULL;
        size_t reply_audio_len = 0;
        app_display_set_status("思考中...");
        ret = app_backend_send_audio(audio, audio_len,
                                     &asr_text, &reply_text, &reply_audio, &reply_audio_len);
        free(audio);

        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "backend failed");
            app_display_set_status("连接失败");
            if (reply_text) {
                free(reply_text);
            }
            vTaskDelay(pdMS_TO_TICKS(300));
            continue;
        }

        /* 屏幕显示双方对话：先"你"的原话，再奶龙的回复 */
        if (asr_text && asr_text[0]) {
            app_display_add_message("你", asr_text);
            free(asr_text);
        }
        if (reply_text) {
            ESP_LOGI(TAG, "reply: %s", reply_text);
            app_display_add_message("奶龙", reply_text);
            free(reply_text);
        }

        /* 3. 播放返回的 TTS 音频 */
        if (reply_audio && reply_audio_len > 0) {
            app_display_set_status("播放中...");
            app_audio_play_wav(reply_audio, reply_audio_len);
            free(reply_audio);
        }
        app_display_set_status("待机");
    }
}

void app_main(void)
{
    /* NVS */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    /* 音频 codec 初始化 */
    ESP_ERROR_CHECK(app_audio_init());

    /* 屏幕（LCD + LVGL）初始化：状态栏 + 对话区 */
    ESP_ERROR_CHECK(app_display_init());

    /* 按键：配置键（GPIO0/boot 键）按一下开始录、再按一下结束。
     * 静音键（GPIO1/BSP_BUTTON_MUTE）按下会点亮静音灯、硬件层面把麦克风静音，
     * 所以不能拿它当录音键，否则录到的全是静音。 */
    button_handle_t btns[BSP_BUTTON_NUM];
    int btn_cnt = 0;
    ret = bsp_iot_button_create(btns, &btn_cnt, BSP_BUTTON_NUM);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "button init failed: %s", esp_err_to_name(ret));
    } else {
        iot_button_register_cb(btns[BSP_BUTTON_CONFIG], BUTTON_SINGLE_CLICK, record_btn_click, NULL);
    }

    /* WiFi 连接（阻塞，最多 20s） */
    ret = app_wifi_start();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "wifi connect failed, will retry on demand");
    } else {
        ESP_LOGI(TAG, "backend: %s", CONFIG_BACKEND_BASE_URL);
    }

    xTaskCreate(voice_task, "voice_task", 16384, NULL, 5, NULL);
}
