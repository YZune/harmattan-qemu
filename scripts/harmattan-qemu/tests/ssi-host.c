/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include "n00-ssi-core.h"

static uint32_t ram[64];
static bool memory(void *opaque, uint32_t addr, uint32_t *word, bool write)
{
    (void)opaque;
    if ((addr & 3) || addr < 0x80001000 || addr >= 0x80001100) { return false; }
    unsigned i = (addr - 0x80001000) / 4;
    if (write) { ram[i] = *word; } else { *word = ram[i]; }
    return true;
}

static void put(N00SSICore *s, uint32_t a, uint32_t v, unsigned size)
{
    assert(n00_ssi_access(s, a, &v, size, true));
    n00_ssi_pump(s);
}

static uint32_t get(N00SSICore *s, uint32_t a, unsigned size)
{
    uint32_t v = 0;
    assert(n00_ssi_access(s, a, &v, size, false));
    n00_ssi_pump(s);
    return v;
}

static void setup(N00SSICore *s, bool loopback)
{
    memset(s, 0, sizeof(*s));
    s->loopback = loopback;
    s->memory = memory;
    n00_ssi_reset(s);
    put(s, 0x2004, 2, 4);
    put(s, 0x2804, 2, 4);
}

static void dma(N00SSICore *s, unsigned ch, bool rx, uint32_t addr, unsigned count)
{
    uint32_t b = 0x1800 + ch * 0x40;
    put(s, b, rx ? 0x9026 : 0x1322, 2);
    put(s, b + 4, 0x21, 2);
    put(s, b + 8, rx ? N00_SSI_BASE + 0x2880 : addr, 4);
    put(s, b + 12, rx ? addr : N00_SSI_BASE + 0x2080, 4);
    put(s, b + 16, count, 2);
    put(s, b + 2, rx ? 0x1090 : 0x1081, 2);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    N00SSICore s;
    setup(&s, false);
    switch (atoi(argv[1])) {
    case 1:
        put(&s, 0x10, 2, 4);
        assert(get(&s, 0, 4) == 0x10 && get(&s, 0x14, 4) == 1);
        assert(!get(&s, 0x2004, 4) && !n00_ssi_status(&s));
        assert(get(&s, 0x2008, 4) == 31);
        put(&s, 0, 0xffffffff, 4);
        assert(get(&s, 0, 4) == 0x10);
        break;
    case 2:
        put(&s, 0x80c, 1, 4);
        assert(n00_ssi_status(&s) & s.irq_enable[0]);
        put(&s, 0x2080, 0xfeed1234, 4);
        assert(!(n00_ssi_status(&s) & 1));
        assert(!s.rx_full && s.tx_full == 1);
        put(&s, 0x2080, 0, 4); /* Backpressure preserves the pending frame. */
        assert(s.tx[0] == 0xfeed1234);
        put(&s, 0x808, 1, 4);
        assert(!(n00_ssi_status(&s) & 1));
        break;
    case 3:
        s.loopback = true;
        put(&s, 0x80c, 0x100, 4);
        put(&s, 0x2080, 0xaabbccdd, 4);
        assert(n00_ssi_status(&s) & s.irq_enable[0]);
        put(&s, 0x2080, 0x12345678, 4);
        assert(s.tx_full == 1); /* A full receiver stalls the second frame. */
        assert(get(&s, 0x2880, 4) == 0xaabbccdd);
        assert(get(&s, 0x2880, 4) == 0x12345678);
        assert(!s.rx_full && !s.tx_full);
        assert(!(n00_ssi_status(&s) & s.irq_enable[0]));
        break;
    case 4:
        s.loopback = true;
        for (unsigned i = 0; i < 16; i++) { ram[i] = 0x91820000u ^ (i * 0x1a23); }
        put(&s, 0x804, 3, 4);
        dma(&s, 0, true, 0x80001080, 16);
        assert(s.dma[0].ccr & 0x80); /* Empty RX cannot complete. */
        dma(&s, 1, false, 0x80001000, 16);
        assert(!memcmp(ram, ram + 32, 16 * 4));
        assert(s.gdd_status == 3);
        assert(get(&s, 0x1806, 2) == 0x20);
        assert(get(&s, 0x1806, 2) == 0);
        put(&s, 0x800, 1, 4);
        assert(s.gdd_status == 2);
        put(&s, 0x800, 2, 4);
        assert(!s.gdd_status);
        break;
    case 5:
        dma(&s, 0, false, 0xfffffffc, 2);
        assert(get(&s, 0x1806, 2) == 1 && !(s.dma[0].ccr & 0x80));
        assert(!s.tx_full && s.gdd_status == 1);
        put(&s, 0x1828, 0x8000, 2);
        dma(&s, 0, false, 0x80001000, 2);
        assert(get(&s, 0x1806, 2) == 1 && !s.tx_full);
        setup(&s, false);
        dma(&s, 0, false, 0x80001000, 16);
        assert(s.dma[0].done == 1);
        put(&s, 0x1810, 1, 2); /* Shrinking an active block cannot overrun. */
        assert(get(&s, 0x1806, 2) == 1 && s.dma[0].done == 1);
        break;
    case 6:
        dma(&s, 0, false, 0x80001000, 16);
        assert(s.dma[0].done == 1 && (s.dma[0].ccr & 0x80));
        put(&s, 0x10, 2, 4);
        assert(!s.dma[0].ccr && !s.tx_full && !s.rx_full);
        assert(!s.gdd_status && !s.irq_enable[0] && s.memory == memory);
        break;
    case 7:
        put(&s, 0xc08, 0x101, 4);
        assert(get(&s, 0xc00, 4) == 1);
        put(&s, 0xc04, 1, 4);
        assert(!get(&s, 0xc00, 4));
        assert(n00_ssi_receive(&s, 0, 11));
        assert(!n00_ssi_receive(&s, 0, 22));
        assert(get(&s, 0x282c, 4) == 1 && get(&s, 0x2880, 4) == 11);
        put(&s, 0x2830, 1, 4);
        assert(!get(&s, 0x282c, 4));
        break;
    case 8:
        for (unsigned mode = 0; mode < 5; mode++) {
            setup(&s, false);
            dma(&s, 0, true, 0x80001000, 2); /* Configure and wait for RX. */
            put(&s, 0x1802, 0, 2);
            switch (mode) {
            case 0: put(&s, 0x1804, 0x25, 2); break; /* Half interrupt. */
            case 1: put(&s, 0x2804, 3, 4); break; /* Multipoint. */
            case 2: put(&s, 0x2808, 15, 4); break; /* 16-bit frame. */
            case 3: put(&s, 0x1810, 0, 2); break; /* Empty DMA block. */
            case 4: put(&s, 0x1800, 0x9025, 2); break; /* Non-32-bit DMA. */
            }
            put(&s, 0x1802, 0x1090, 2);
            assert(get(&s, 0x1806, 2) == 1);
            assert(!(s.dma[0].ccr & 0x80) && !s.dma[0].done);
        }
        break;
    case 9:
        s.loopback = true;
        put(&s, 0x2024, 8, 4);
        put(&s, 0x2828, 8, 4);
        for (unsigned ch = 0; ch < 8; ch++) {
            put(&s, 0x2080 + 4 * ch, 0x91820000 + ch, 4);
        }
        assert(s.rx_full == 0xff && s.tx_full == 0);
        for (unsigned ch = 8; ch-- > 0;) {
            assert(get(&s, 0x2880 + 4 * ch, 4) == 0x91820000 + ch);
        }
        assert(!s.rx_full);
        break;
    default: abort();
    }
    puts("PASS");
}
