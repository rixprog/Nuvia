#include "mpu.h"

#include <string.h>

#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "mpu";

#define REG_SMPLRT_DIV   0x19
#define REG_CONFIG       0x1A
#define REG_GYRO_CONFIG  0x1B
#define REG_ACCEL_CONFIG 0x1C
#define REG_ACCEL_XOUT_H 0x3B
#define REG_PWR_MGMT_1   0x6B
#define REG_WHO_AM_I     0x75

#define I2C_TIMEOUT_MS 100

static esp_err_t reg_write(mpu_t *mpu, uint8_t reg, uint8_t val)
{
    uint8_t buf[2] = {reg, val};
    return i2c_master_transmit(mpu->dev, buf, sizeof(buf), I2C_TIMEOUT_MS);
}

static esp_err_t reg_read(mpu_t *mpu, uint8_t reg, uint8_t *dst, size_t len)
{
    return i2c_master_transmit_receive(mpu->dev, &reg, 1, dst, len, I2C_TIMEOUT_MS);
}

// WHO_AM_I values across the MPU/ICM family. The register layout used below is
// shared by all of them, so an unknown id is still worth streaming.
static const char *chip_name(uint8_t who)
{
    switch (who) {
    case 0x68: return "MPU-6050/6000";
    case 0x69: return "MPU-6050 (AD0 high)";
    case 0x70: return "MPU-6500";
    case 0x71: return "MPU-9250";
    case 0x73: return "MPU-9255";
    case 0x74: return "MPU-9515";
    case 0x75: return "MPU-6515";
    case 0x76: return "MPU-6880";
    case 0x98: return "ICM-20602";
    case 0xAC: return "ICM-20608";
    default:   return "unknown MPU-compatible";
    }
}

void mpu_bus_scan(i2c_master_bus_handle_t bus)
{
    ESP_LOGI(TAG, "scanning I2C bus (SDA=%d SCL=%d)...", MPU_PIN_SDA, MPU_PIN_SCL);
    int found = 0;
    for (uint8_t addr = 0x08; addr < 0x78; addr++) {
        if (i2c_master_probe(bus, addr, 50) == ESP_OK) {
            ESP_LOGI(TAG, "  device at 0x%02X", addr);
            found++;
        }
    }
    if (found == 0) {
        ESP_LOGW(TAG, "  nothing responded - check 3V3, GND, SDA/SCL and pull-ups");
    }
}

esp_err_t mpu_init(i2c_master_bus_handle_t bus, mpu_t *out)
{
    memset(out, 0, sizeof(*out));

    const uint8_t candidates[] = {0x68, 0x69};
    for (size_t i = 0; i < sizeof(candidates); i++) {
        if (i2c_master_probe(bus, candidates[i], 100) != ESP_OK) {
            continue;
        }
        i2c_device_config_t cfg = {
            .dev_addr_length = I2C_ADDR_BIT_LEN_7,
            .device_address = candidates[i],
            .scl_speed_hz = MPU_I2C_HZ,
        };
        ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(bus, &cfg, &out->dev), TAG,
                            "add device 0x%02X", candidates[i]);
        out->addr = candidates[i];
        break;
    }
    if (out->addr == 0) {
        ESP_LOGE(TAG, "no MPU found at 0x68 or 0x69");
        return ESP_ERR_NOT_FOUND;
    }

    ESP_RETURN_ON_ERROR(reg_read(out, REG_WHO_AM_I, &out->who_am_i, 1), TAG, "WHO_AM_I");
    out->name = chip_name(out->who_am_i);
    ESP_LOGI(TAG, "found %s at 0x%02X (WHO_AM_I=0x%02X)", out->name, out->addr, out->who_am_i);

    // Wake from sleep and run off the gyro X PLL, which is more stable than the
    // internal oscillator.
    ESP_RETURN_ON_ERROR(reg_write(out, REG_PWR_MGMT_1, 0x80), TAG, "reset");  // device reset
    vTaskDelay(pdMS_TO_TICKS(100));
    ESP_RETURN_ON_ERROR(reg_write(out, REG_PWR_MGMT_1, 0x01), TAG, "wake");
    vTaskDelay(pdMS_TO_TICKS(10));

    ESP_RETURN_ON_ERROR(reg_write(out, REG_CONFIG, 0x03), TAG, "dlpf");        // DLPF 44Hz, 1kHz base
    ESP_RETURN_ON_ERROR(reg_write(out, REG_SMPLRT_DIV, 0x04), TAG, "rate");    // 1000/(1+4) = 200 Hz
    ESP_RETURN_ON_ERROR(reg_write(out, REG_GYRO_CONFIG, 0x08), TAG, "gyro");   // +-500 dps
    ESP_RETURN_ON_ERROR(reg_write(out, REG_ACCEL_CONFIG, 0x08), TAG, "accel"); // +-4 g

    out->accel_lsb_per_g = 8192.0f;
    out->gyro_lsb_per_dps = 65.5f;
    return ESP_OK;
}

esp_err_t mpu_read(mpu_t *mpu, mpu_sample_t *out)
{
    uint8_t raw[14];
    ESP_RETURN_ON_ERROR(reg_read(mpu, REG_ACCEL_XOUT_H, raw, sizeof(raw)), TAG, "burst read");

    int16_t v[7];
    for (int i = 0; i < 7; i++) {
        v[i] = (int16_t)((raw[i * 2] << 8) | raw[i * 2 + 1]);
    }

    out->ax = v[0] / mpu->accel_lsb_per_g;
    out->ay = v[1] / mpu->accel_lsb_per_g;
    out->az = v[2] / mpu->accel_lsb_per_g;
    out->temp_c = v[3] / 340.0f + 36.53f;
    out->gx = v[4] / mpu->gyro_lsb_per_dps;
    out->gy = v[5] / mpu->gyro_lsb_per_dps;
    out->gz = v[6] / mpu->gyro_lsb_per_dps;
    return ESP_OK;
}
