#include <string.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "app_wifi.h"

static const char *TAG = "app_wifi";

#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1
#define WIFI_SCAN_TIMEOUT_MS 10000   /* 搜索 WiFi 超时：10 秒，找不到就停止连接 */
#define MAX_RETRY          5

static EventGroupHandle_t s_wifi_events;
static int s_retry = 0;

/* 扫描完成后检查目标 SSID 是否可见：可见才发起连接，找不到则停止连接 */
static void handle_scan_done(void)
{
    uint16_t ap_num = 0;
    esp_err_t ret = esp_wifi_scan_get_ap_num(&ap_num);
    if (ret != ESP_OK || ap_num == 0) {
        ESP_LOGW(TAG, "scan done, no AP found");
        xEventGroupSetBits(s_wifi_events, WIFI_FAIL_BIT);
        return;
    }

    wifi_ap_record_t *records = malloc(ap_num * sizeof(wifi_ap_record_t));
    if (records == NULL) {
        ESP_LOGE(TAG, "no mem for scan records");
        xEventGroupSetBits(s_wifi_events, WIFI_FAIL_BIT);
        return;
    }
    ret = esp_wifi_scan_get_ap_records(&ap_num, records);
    if (ret != ESP_OK) {
        free(records);
        xEventGroupSetBits(s_wifi_events, WIFI_FAIL_BIT);
        return;
    }

    bool found = false;
    for (int i = 0; i < ap_num; i++) {
        ESP_LOGI(TAG, "AP[%d] '%s' rssi=%d", i, records[i].ssid, records[i].rssi);
        if (strcmp((const char *)records[i].ssid, CONFIG_WIFI_SSID) == 0) {
            found = true;
            break;
        }
    }
    free(records);

    if (found) {
        ESP_LOGI(TAG, "target AP '%s' found, start connecting", CONFIG_WIFI_SSID);
        esp_wifi_connect();
    } else {
        ESP_LOGW(TAG, "target AP '%s' not found, stop connecting", CONFIG_WIFI_SSID);
        xEventGroupSetBits(s_wifi_events, WIFI_FAIL_BIT);
    }
}

static void wifi_event_handler(void *arg, esp_event_base_t base,
                               int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        /* 先扫描目标 AP，找到才连接；10 秒内搜不到就停止连接 */
        wifi_scan_config_t scan_cfg = {
            .ssid = NULL,
            .bssid = NULL,
            .channel = 0,
            .show_hidden = true,
        };
        esp_err_t ret = esp_wifi_scan_start(&scan_cfg, false);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "scan start failed: %s", esp_err_to_name(ret));
            xEventGroupSetBits(s_wifi_events, WIFI_FAIL_BIT);
        }
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_SCAN_DONE) {
        handle_scan_done();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Disconnect, reason: %d", ((wifi_event_sta_disconnected_t *)data)->reason);
        if (s_retry < MAX_RETRY) {
            esp_wifi_connect();
            s_retry++;
            ESP_LOGW(TAG, "retry connect (%d/%d)", s_retry, MAX_RETRY);
        } else {
            xEventGroupSetBits(s_wifi_events, WIFI_FAIL_BIT);
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *evt = (ip_event_got_ip_t *)data;
        s_retry = 0;
        ESP_LOGI(TAG, "got ip: " IPSTR, IP2STR(&evt->ip_info.ip));
        xEventGroupSetBits(s_wifi_events, WIFI_CONNECTED_BIT);
    }
}

esp_err_t app_wifi_start(void)
{
    s_wifi_events = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    esp_event_handler_instance_t instance_any_id;
    esp_event_handler_instance_t instance_got_ip;
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, &instance_any_id));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, &instance_got_ip));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = CONFIG_WIFI_SSID,
            .password = CONFIG_WIFI_PASSWORD,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    EventBits_t bits = xEventGroupWaitBits(
        s_wifi_events, WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
        pdFALSE, pdFALSE, pdMS_TO_TICKS(WIFI_SCAN_TIMEOUT_MS));

    if (bits & WIFI_CONNECTED_BIT) {
        ESP_LOGI(TAG, "connected to AP");
        return ESP_OK;
    }
    ESP_LOGE(TAG, "failed to connect within %d ms", WIFI_SCAN_TIMEOUT_MS);
    return ESP_FAIL;
}

bool app_wifi_connected(void)
{
    if (s_wifi_events == NULL) {
        return false;
    }
    return (xEventGroupGetBits(s_wifi_events) & WIFI_CONNECTED_BIT) != 0;
}
