#pragma once
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 初始化 LCD + LVGL（参考 xiaozhi-esp32 的 Display 抽象：状态栏 + 滚动对话区）。
 * 必须在任何 app_display_* 调用前执行一次。
 */
esp_err_t app_display_init(void);

/**
 * 更新顶部状态栏文字（如 "待机" / "听你说话..." / "思考中..." / "播放中..."）。
 */
void app_display_set_status(const char *status);

/**
 * 向屏幕对话区追加一条消息，格式为 "who: text"，并自动滚动到底部。
 * 例如 app_display_add_message("你", "你好奶龙") 显示 "你: 你好奶龙"。
 */
void app_display_add_message(const char *who, const char *text);

#ifdef __cplusplus
}
#endif
