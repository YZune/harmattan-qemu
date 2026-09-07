/* N00 SSI QEMU adapter. SPDX-License-Identifier: GPL-2.0-only */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qemu/error-report.h"
#include "qemu/log.h"
#include "hw/sysbus.h"
#include "hw/irq.h"
#include "hw/qdev-properties.h"
#include "exec/address-spaces.h"
#include "qemu/module.h"
#include "n00-ssi-core.h"

void n00_ssi_init(DeviceState *intc);

typedef struct N00SSI {
    SysBusDevice parent_obj;
    MemoryRegion mmio;
    qemu_irq irq[3];
    N00SSICore core;
} N00SSI;

static bool ssi_memory(void *opaque, uint32_t address, uint32_t *word, bool write)
{
    uint8_t bytes[4];
    if ((address & 3) || address < 0x80000000u || address > 0x9ffffffcu) {
        return false;
    }
    /* Guest-programmable windows can overlap SDRAM. Validate the current
     * mapping too, so an in-range address can never recurse into MMIO. */
    MemoryRegionSection section = memory_region_find(get_system_memory(), address, 4);
    bool ram = section.mr && memory_region_is_ram(section.mr) &&
               !memory_region_is_rom(section.mr) &&
               int128_ge(section.size, int128_make64(4));
    if (section.mr) { memory_region_unref(section.mr); }
    if (!ram) { return false; }
    if (write) {
        stl_le_p(bytes, *word);
        return address_space_write(&address_space_memory, address,
                                   MEMTXATTRS_UNSPECIFIED, bytes, 4) == MEMTX_OK;
    }
    if (address_space_read(&address_space_memory, address,
                           MEMTXATTRS_UNSPECIFIED, bytes, 4) != MEMTX_OK) {
        return false;
    }
    *word = ldl_le_p(bytes);
    return true;
}

static void ssi_update(N00SSI *s)
{
    n00_ssi_pump(&s->core);
    uint32_t status = n00_ssi_status(&s->core);
    qemu_set_irq(s->irq[0], !!(status & s->core.irq_enable[0]));
    qemu_set_irq(s->irq[1], !!(status & s->core.irq_enable[1]));
    qemu_set_irq(s->irq[2], !!(s->core.gdd_status & s->core.gdd_enable));
}

static uint64_t ssi_read(void *opaque, hwaddr address, unsigned size)
{
    N00SSI *s = opaque;
    uint32_t value = 0;
    if (!n00_ssi_access(&s->core, address, &value, size, false)) {
        qemu_log_mask(LOG_UNIMP, "N00 SSI: unsupported read 0x%" HWADDR_PRIx "/%u\n", address, size);
    }
    ssi_update(s);
    return value;
}

static void ssi_write(void *opaque, hwaddr address, uint64_t value, unsigned size)
{
    N00SSI *s = opaque;
    uint32_t word = value;
    if (!n00_ssi_access(&s->core, address, &word, size, true)) {
        qemu_log_mask(LOG_UNIMP, "N00 SSI: unsupported write 0x%" HWADDR_PRIx "/%u\n", address, size);
    }
    ssi_update(s);
}

static const MemoryRegionOps ssi_ops = {
    .read = ssi_read, .write = ssi_write, .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 2, .max_access_size = 4 },
    .impl = { .min_access_size = 2, .max_access_size = 4 },
};

static void ssi_reset(DeviceState *dev)
{
    N00SSI *s = (N00SSI *)dev;
    n00_ssi_reset(&s->core);
    ssi_update(s);
}

static void ssi_instance_init(Object *obj)
{
    N00SSI *s = (N00SSI *)obj;
    s->core.memory = ssi_memory;
    memory_region_init_io(&s->mmio, obj, &ssi_ops, s, "n00-ssi", 0x3c00);
    sysbus_init_mmio(SYS_BUS_DEVICE(obj), &s->mmio);
    for (unsigned i = 0; i < 3; i++) {
        sysbus_init_irq(SYS_BUS_DEVICE(obj), &s->irq[i]);
    }
}

static Property ssi_properties[] = {
    DEFINE_PROP_BOOL("loopback", N00SSI, core.loopback, false),
    DEFINE_PROP_END_OF_LIST(),
};

static void ssi_class_init(ObjectClass *klass, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    dc->reset = ssi_reset;
    dc->user_creatable = false;
    device_class_set_props(dc, ssi_properties);
}

static const TypeInfo ssi_info = {
    .name = "n00-ssi", .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(N00SSI), .instance_init = ssi_instance_init,
    .class_init = ssi_class_init,
};

static void ssi_register_types(void) { type_register_static(&ssi_info); }
type_init(ssi_register_types)

void n00_ssi_init(DeviceState *intc)
{
    const char *mode = getenv("HARMATTAN_N00_SSI");
    if (mode && strcmp(mode, "off") && strcmp(mode, "on")) {
        error_report("HARMATTAN_N00_SSI must be off or on");
        exit(1);
    }
    if (!mode || !strcmp(mode, "off")) { return; }
    DeviceState *dev = qdev_new("n00-ssi");
    SysBusDevice *bus = SYS_BUS_DEVICE(dev);
    sysbus_realize_and_unref(bus, &error_fatal);
    sysbus_mmio_map(bus, 0, N00_SSI_BASE);
    static const unsigned irqs[] = { 67, 68, 71 };
    for (unsigned i = 0; i < 3; i++) {
        sysbus_connect_irq(bus, i, qdev_get_gpio_in(intc, irqs[i]));
    }
}
