/*
 * QEMU 9.1 adapter for Nokia's original N00 SDK power devices.
 * Register implementation and inherited notices: n00-sdk-power-registers.h.
 * SPDX-License-Identifier: GPL-2.0-or-3.0
 */
#include "qemu/osdep.h"
#include "hw/i2c/i2c.h"
#include "hw/qdev-properties.h"
#include "hw/hw.h"
#include "qapi/error.h"
#include "qemu/module.h"
#include "qemu/error-report.h"
#include "n00-sdk-power-registers.h"

void n00_sdk_power_init(I2CBus *bus);
bool n00_sdk_power_enabled(void);
int n00_sdk_power_adc(unsigned address);

typedef struct N00Charger {
    I2CSlave parent_obj;
    BQ2415XState regs;
} N00Charger;

typedef struct N00Gauge {
    I2CSlave parent_obj;
    BQ27521State regs;
} N00Gauge;

static void charger_reset(DeviceState *dev)
{
    bq2415x_reset(&((N00Charger *)dev)->regs);
}

static void gauge_reset(DeviceState *dev)
{
    bq27521_reset(&((N00Gauge *)dev)->regs);
}

static int charger_event(I2CSlave *dev, enum i2c_event event)
{
    if (event == I2C_START_SEND) {
        ((N00Charger *)dev)->regs.firstbyte = 1;
    }
    return 0;
}

static int gauge_event(I2CSlave *dev, enum i2c_event event)
{
    if (event == I2C_START_SEND) {
        ((N00Gauge *)dev)->regs.firstbyte = 1;
    }
    return 0;
}

static uint8_t charger_recv(I2CSlave *dev)
{
    return bq2415x_rx(&((N00Charger *)dev)->regs);
}

static uint8_t gauge_recv(I2CSlave *dev)
{
    int value = bq27521_rx(&((N00Gauge *)dev)->regs);
    if (value < 0) {
        hw_error("N00 SDK BQ27521: unsupported register read");
    }
    return value;
}

static int charger_send(I2CSlave *dev, uint8_t value)
{
    bq2415x_tx(&((N00Charger *)dev)->regs, value);
    /* Modern I2CSlave send returns 0 for ACK, unlike the old Nokia callback. */
    return 0;
}

static int gauge_send(I2CSlave *dev, uint8_t value)
{
    if (bq27521_tx(&((N00Gauge *)dev)->regs, value) < 0) {
        hw_error("N00 SDK BQ27521: unsupported register write");
    }
    return 0;
}

static Property charger_properties[] = {
    DEFINE_PROP_UINT8("chip-id", N00Charger, regs.id, 0x49),
    DEFINE_PROP_END_OF_LIST(),
};

static void charger_class_init(ObjectClass *klass, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    I2CSlaveClass *ic = I2C_SLAVE_CLASS(klass);
    dc->reset = charger_reset;
    dc->user_creatable = false;
    device_class_set_props(dc, charger_properties);
    ic->event = charger_event;
    ic->recv = charger_recv;
    ic->send = charger_send;
}

static void gauge_class_init(ObjectClass *klass, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    I2CSlaveClass *ic = I2C_SLAVE_CLASS(klass);
    dc->reset = gauge_reset;
    dc->user_creatable = false;
    ic->event = gauge_event;
    ic->recv = gauge_recv;
    ic->send = gauge_send;
}

static const TypeInfo power_types[] = {
    { .name = "n00-sdk-bq2415x", .parent = TYPE_I2C_SLAVE,
      .instance_size = sizeof(N00Charger), .class_init = charger_class_init },
    { .name = "n00-sdk-bq27521", .parent = TYPE_I2C_SLAVE,
      .instance_size = sizeof(N00Gauge), .class_init = gauge_class_init },
};
DEFINE_TYPES(power_types)

void n00_sdk_power_init(I2CBus *bus)
{
    static const uint8_t addresses[] = { 0x6b, 0x6a };
    static const uint8_t ids[] = { 0x51, 0x41 };
    for (unsigned i = 0; i < G_N_ELEMENTS(addresses); i++) {
        I2CSlave *dev = i2c_slave_new("n00-sdk-bq2415x", addresses[i]);
        qdev_prop_set_uint8(DEVICE(dev), "chip-id", ids[i]);
        i2c_slave_realize_and_unref(dev, bus, &error_fatal);
    }
    i2c_slave_create_simple(bus, "n00-sdk-bq27521", 0x55);
}

/* Explicit experiment until original BME and the full service graph pass. */
bool n00_sdk_power_enabled(void)
{
    const char *mode = getenv("HARMATTAN_N00_SDK_POWER");
    if (mode && strcmp(mode, "off") && strcmp(mode, "on")) {
        error_report("HARMATTAN_N00_SDK_POWER must be off or on");
        exit(1);
    }
    return mode && !strcmp(mode, "on");
}

int n00_sdk_power_adc(unsigned address)
{
    return n00_sdk_adc_read(address);
}
