#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include "n00-sdk-power-registers.h"

static void charger_select(BQ2415XState *s, uint8_t reg)
{
    s->firstbyte = 1;
    assert(bq2415x_tx(s, reg) == 1);
}

static void gauge_select(BQ27521State *s, uint8_t reg)
{
    s->firstbyte = 1;
    assert(bq27521_tx(s, reg) == 1);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    BQ2415XState charger = { .id = 0x51 };
    BQ27521State gauge = { 0 };
    bq2415x_reset(&charger);
    bq27521_reset(&gauge);
    switch (atoi(argv[1])) {
    case 1: /* Both N00 charger variants; IDs survive reset and writes. */
        for (unsigned id = 0x41; id <= 0x51; id += 0x10) {
            charger.id = id;
            charger_select(&charger, 3);
            bq2415x_tx(&charger, 0);
            charger_select(&charger, 3);
            assert(bq2415x_rx(&charger) == (int)id);
            charger_select(&charger, 0x3b);
            assert(bq2415x_rx(&charger) == (int)id);
            bq2415x_reset(&charger);
            assert(charger.id == id);
        }
        break;
    case 2: /* Guest cannot overwrite charger status bits via status/control. */
        for (unsigned v = 0; v <= 255; v++) {
            charger_select(&charger, 0);
            bq2415x_tx(&charger, v);
            charger_select(&charger, 0);
            assert(bq2415x_rx(&charger) == (int)(0x90 | (v & 0x40)));
            charger_select(&charger, 4);
            bq2415x_tx(&charger, v);
            charger_select(&charger, 4);
            assert(bq2415x_rx(&charger) == (int)(v | 0x80));
        }
        break;
    case 3: /* Repeated-start/auto-increment, little endian gauge state. */
        gauge_select(&gauge, 0x26);
        bq27521_tx(&gauge, 0x34);
        bq27521_tx(&gauge, 0x12);
        bq27521_tx(&gauge, 0xcd);
        bq27521_tx(&gauge, 0xab);
        gauge_select(&gauge, 0x26);
        assert(bq27521_rx(&gauge) == 0x34);
        assert(bq27521_rx(&gauge) == 0x12);
        assert(bq27521_rx(&gauge) == 0xcd);
        assert(bq27521_rx(&gauge) == 0xab);
        gauge_select(&gauge, 0x0e);
        assert(bq27521_rx(&gauge) == 0);
        assert(bq27521_rx(&gauge) == 2);
        break;
    case 4: /* Original status clear and software reset commands. */
        assert(gauge.st == 0x40);
        gauge_select(&gauge, 2);
        bq27521_tx(&gauge, 0x40);
        assert(gauge.st == 0);
        gauge_select(&gauge, 2);
        bq27521_tx(&gauge, 0x80);
        assert(gauge.st == 0x40 && gauge.cl == 0 && gauge.ch == 0);
        assert(gauge.c1 == 0x37ff && gauge.c2 == 0xc0);
        break;
    case 5: /* Unknown gauge accesses remain failures, not fabricated data. */
        gauge_select(&gauge, 0xff);
        assert(bq27521_rx(&gauge) < 0);
        gauge_select(&gauge, 0x30);
        assert(bq27521_tx(&gauge, 42) < 0);
        /* The original charger's unknown register behavior is zero/ignore. */
        charger_select(&charger, 0xff);
        assert(bq2415x_rx(&charger) == 0);
        break;
    case 6: /* N00 ten-bit MADC values must retain their low two bits. */
        for (unsigned ch = 0; ch < 16; ch++) {
            unsigned addr = 0x37 + ch * 2;
            int lo = n00_sdk_adc_read(addr), hi = n00_sdk_adc_read(addr + 1);
            if (ch == 0 || ch == 4 || ch == 12) {
                assert((hi << 2 | lo >> 6) == 0x2b9);
            } else if (ch == 1) {
                assert((hi << 2 | lo >> 6) == 0x1ed);
            } else {
                assert(lo == -1 && hi == -1);
            }
        }
        break;
    default: return 2;
    }
    puts("PASS");
    return 0;
}
