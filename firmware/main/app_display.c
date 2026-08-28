#include <string.h>
#include <stdio.h>
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "bsp/esp-bsp.h"
#include "lvgl.h"
#include "app_display.h"

static const char *TAG = "app_display";

/* 对话区文本缓存上限（超出后丢弃最早的半段，保留最近内容） */
#define CHAT_MAX  2048

static lv_obj_t *s_status_label = NULL;
static lv_obj_t *s_chat_area = NULL;
static lv_obj_t *s_chat_label = NULL;
static char s_chat[CHAT_MAX] = "";

/* 中文字体：GB2312 全量（7446 字，含汉字/中文标点/假名等），
 * 由 Windows 黑体 simhei.ttf 用 lv_font_conv 生成（见 fonts/ 目录生成脚本），
 * 覆盖日常对话文本，避免 LVGL 内置 1338 字 CJK 字体大量缺字显示方框。 */
LV_FONT_DECLARE(lv_font_simhei_16);

esp_err_t app_display_init(void)
{
    /* 初始化 LCD 并启动 LVGL（esp-box bsp） */
    lv_disp_t *disp = bsp_display_start();
    if (disp == NULL) {
        ESP_LOGE(TAG, "bsp_display_start failed");
        return ESP_FAIL;
    }
    bsp_display_backlight_on();

    lv_obj_t *scr = lv_scr_act();
    lv_obj_set_style_bg_color(scr, lv_color_hex(0x1A1A2E), 0);

    /* 顶部状态栏 */
    s_status_label = lv_label_create(scr);
    lv_label_set_text(s_status_label, "待机");
    lv_obj_set_style_text_color(s_status_label, lv_color_hex(0x8FE3CF), 0);
    lv_obj_set_style_text_font(s_status_label, &lv_font_simhei_16, 0);
    lv_obj_align(s_status_label, LV_ALIGN_TOP_LEFT, 8, 4);

    /* 对话滚动区域（320x240 屏幕，留出顶部状态栏） */
    s_chat_area = lv_obj_create(scr);
    lv_obj_set_size(s_chat_area, 304, 200);
    lv_obj_align(s_chat_area, LV_ALIGN_TOP_LEFT, 8, 28);
    lv_obj_set_style_bg_color(s_chat_area, lv_color_hex(0x16213E), 0);
    lv_obj_set_style_border_width(s_chat_area, 0, 0);
    lv_obj_set_style_pad_all(s_chat_area, 8, 0);
    lv_obj_set_scroll_dir(s_chat_area, LV_DIR_VER);
    lv_obj_set_scrollbar_mode(s_chat_area, LV_SCROLLBAR_MODE_OFF);

    s_chat_label = lv_label_create(s_chat_area);
    lv_label_set_long_mode(s_chat_label, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(s_chat_label, 288);
    lv_obj_set_style_text_color(s_chat_label, lv_color_hex(0xEEEEEE), 0);
    lv_obj_set_style_text_font(s_chat_label, &lv_font_simhei_16, 0);
    lv_label_set_text(s_chat_label, "");

    ESP_LOGI(TAG, "display ready");
    return ESP_OK;
}

void app_display_set_status(const char *status)
{
    if (s_status_label == NULL || status == NULL) {
        return;
    }
    if (!bsp_display_lock(0)) {
        return;
    }
    lv_label_set_text(s_status_label, status);
    bsp_display_unlock();
}

void app_display_add_message(const char *who, const char *text)
{
    if (s_chat_label == NULL || s_chat_area == NULL || who == NULL || text == NULL) {
        return;
    }

    /* 新消息拼成 "who: text\n" */
    char line[320];
    int n = snprintf(line, sizeof(line), "%s: %s", who, text);
    if (n <= 0) {
        return;
    }

    if (!bsp_display_lock(0)) {
        return;
    }

    size_t used = strlen(s_chat);
    size_t need = (size_t)n + 1;
    if (used + need >= CHAT_MAX) {
        /* 缓存满了：丢弃最早的一半，避免截断当前消息 */
        size_t keep_from = used / 2;
        while (keep_from > 0 && s_chat[keep_from] != '\n') {
            keep_from--;
        }
        memmove(s_chat, s_chat + keep_from, used - keep_from + 1);
        used = strlen(s_chat);
    }

    if (used > 0 && s_chat[used - 1] != '\n') {
        s_chat[used++] = '\n';
        s_chat[used] = '\0';
    }
    memcpy(s_chat + used, line, (size_t)n);
    s_chat[used + (size_t)n] = '\0';

    lv_label_set_text(s_chat_label, s_chat);
    /* 滚动到底部，显示最新消息 */
    lv_obj_scroll_to_y(s_chat_area, LV_COORD_MAX, LV_ANIM_OFF);

    bsp_display_unlock();
}
