#pragma once
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 启动 WiFi Station 并自动连接路由器（阻塞直到连上或失败）。
 * 流程：先主动扫描周边 WiFi（最多 10 秒），扫描结果里找不到
 * 目标 SSID 就停止连接并返回失败；找到后才发起连接。
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
