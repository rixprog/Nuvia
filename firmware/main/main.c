// Streams MPU accel/gyro over the USB serial port as CSV, one line per sample:
//   D,<millis>,<ax>,<ay>,<az>,<gx>,<gy>,<gz>,<temp_c>
// Non-data lines are IDF logs, so the host reader keys on the leading "D,".

#include <inttypes.h>
#include <stdio.h>

#include "driver/i2c_master.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mpu.h"

static const char *TAG = "main";

#define STREAM_HZ 100

void app_main(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .i2c_port = I2C_NUM_0,
        .sda_io_num = MPU_PIN_SDA,
        .scl_io_num = MPU_PIN_SCL,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));

    mpu_bus_scan(bus);

    mpu_t mpu;
    while (mpu_init(bus, &mpu) != ESP_OK) {
        ESP_LOGE(TAG, "retrying MPU init in 2s");
        vTaskDelay(pdMS_TO_TICKS(2000));
    }

    ESP_LOGI(TAG, "streaming at %d Hz", STREAM_HZ);
    puts("H,millis,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,temp_c");

    const TickType_t period = pdMS_TO_TICKS(1000 / STREAM_HZ);
    TickType_t last = xTaskGetTickCount();
    for (;;) {
        mpu_sample_t s;
        if (mpu_read(&mpu, &s) == ESP_OK) {
            printf("D,%" PRIu32 ",%.4f,%.4f,%.4f,%.2f,%.2f,%.2f,%.2f\n",
                   (uint32_t)(esp_timer_get_time() / 1000), s.ax, s.ay, s.az,
                   s.gx, s.gy, s.gz, s.temp_c);
        } else {
            ESP_LOGW(TAG, "read failed");
        }
        vTaskDelayUntil(&last, period);
    }
}
