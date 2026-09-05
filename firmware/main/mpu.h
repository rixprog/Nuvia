#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "driver/i2c_master.h"
#include "esp_err.h"

// Wiring (ESP32 DevKit defaults). MPU VCC -> 3V3, GND -> GND,
// SDA -> GPIO21, SCL -> GPIO22, AD0 -> GND (address 0x68).
#define MPU_PIN_SDA 21
#define MPU_PIN_SCL 22
#define MPU_I2C_HZ 400000

typedef struct {
    i2c_master_dev_handle_t dev;
    uint8_t addr;
    uint8_t who_am_i;
    const char *name;
    float accel_lsb_per_g;
    float gyro_lsb_per_dps;
} mpu_t;

typedef struct {
    float ax, ay, az;  // g
    float gx, gy, gz;  // deg/s
    float temp_c;
} mpu_sample_t;

// Prints every responding address on the bus.
void mpu_bus_scan(i2c_master_bus_handle_t bus);

// Finds an MPU at 0x68 or 0x69, identifies it and configures it for streaming.
esp_err_t mpu_init(i2c_master_bus_handle_t bus, mpu_t *out);

esp_err_t mpu_read(mpu_t *mpu, mpu_sample_t *out);
