#pragma once
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 启动 WiFi Station 并连接路由器（阻塞直到连上或失败）。
 * SSID/密码通过 menuconfig 配置，见 Kconfig.projbuild。
 */
esp_err_t app_wifi_start(void);

/**
 * 返回当前是否已连上 WiFi。
 */
bool app_wifi_connected(void);

#ifdef __cplusplus
}
#endif
