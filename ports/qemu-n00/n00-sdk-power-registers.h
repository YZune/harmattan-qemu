/*
 * Nokia OMAP3 development board
 *
 * Copyright (C) 2009-2010 Nokia Corporation
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License as
 * published by the Free Software Foundation; either version 2 or
 * (at your option) version 3 of the License.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along
 * with this program; if not, see <http://www.gnu.org/licenses/>.
 */

/* Original SDK register behavior, from Nokia revision
 * 32530f6ab08f80a53bf56843ab793eefde75a67f, hw/n00.c and hw/nseries.c.
 * The latter is Copyright (C) 2007 Nokia Corporation, written by
 * Andrzej Zaborowski <andrew@openedhand.com>, under the same GPL-2.0-or-3.0.
 * Fixed virtual-device defaults are NOT physical host battery measurements.
 */
#ifndef N00_SDK_POWER_REGISTERS_H
#define N00_SDK_POWER_REGISTERS_H
#include <stdint.h>

typedef struct BQ2415XState_s {
    int firstbyte;
    uint8_t reg;

    uint8_t id;
    uint8_t st_ctrl;
    uint8_t ctrl;
    uint8_t bat_v;
    uint8_t tcc;
} BQ2415XState;

static void bq2415x_reset(BQ2415XState *s)
{

    s->firstbyte = 0;
    s->reg = 0;

    s->st_ctrl = 0x50 | 0x80; // 40
    s->ctrl = 0x30;
    s->bat_v = 0x0a;
    s->tcc = 0xa1; // 89
}


static int bq2415x_rx(BQ2415XState *s)
{
    int value = -1;
    switch (s->reg) {
        case 0x00:
            value = s->st_ctrl;
            break;
        case 0x01:
            value = s->ctrl;
            break;
        case 0x02:
            value = s->bat_v;
            break;
        case 0x03:
        case 0x3b:
            value = s->id;
            break;
        case 0x04:
            value = s->tcc;
            break;
        default:
            value = 0;
            break;
    }
    s->reg++;
    return value;
}

static int bq2415x_tx(BQ2415XState *s, uint8_t data)
{
    if (s->firstbyte) {
        s->reg = data;
        s->firstbyte = 0;
    } else {
        switch (s->reg) {
            case 0x00:
                s->st_ctrl = (s->st_ctrl & 0x3f) | (data & 0x40) | 0x80;
                break;
            case 0x01:
                s->ctrl = data;
                break;
            case 0x02:
                s->bat_v = data;
                break;
            case 0x04:
                s->tcc = data | 0x80;
                break;
            default:
                break;
        }
        s->reg++;
    }
    return 1;
}


typedef struct BQ27521State_s {
    uint8_t firstbyte;
    uint8_t reg;

    uint16_t ctrl;
    uint16_t c1, c2;
    uint16_t st;
    uint16_t cl, ch;
    uint16_t cur;
} BQ27521State;

#define BQ27521_READ(r, v) \
    case r: value = s->v & 0xff; break; \
    case r + 1: value = s->v >> 8; break
#define BQ27521_WRITE_LSB(v) s->v = (s->v & 0xff00) | data
#define BQ27521_WRITE_MSB(v) s->v = (s->v & 0xff) | (((uint16_t)data) << 8)
#define BQ27521_WRITE(r, v) \
    case r: BQ27521_WRITE_LSB(v); break; \
    case r + 1: BQ27521_WRITE_MSB(v); break

static void bq27521_reset(BQ27521State *s)
{
    s->firstbyte = 0;
    s->ctrl = 0x0005;
    s->c1 = 0x37ff;
    s->c2 = 0x00c0;
    s->st = 0x0040;
    s->cl = s->ch = 0;
    s->cur = 0x0200; /* 512mA */
}


static int bq27521_rx(BQ27521State *s)
{
    int value = -1;
    switch (s->reg) {
    BQ27521_READ(0x02, ctrl);
    BQ27521_READ(0x04, c1);
    BQ27521_READ(0x06, c2);
    BQ27521_READ(0x08, st);
    BQ27521_READ(0x0e, cur);
    BQ27521_READ(0x10, cur);
    case 0x12 ... 0x15:
        value = 0;
        break;
    BQ27521_READ(0x26, cl);
    BQ27521_READ(0x28, ch);
    case 0x32:
    case 0x33:
    case 0x34:
        value = 0;
        break;
    case 0x35:
        value = 0x21;
        break;
    default:
        return -1;
    }
    s->reg++;
    return value;
}

static int bq27521_tx(BQ27521State *s, uint8_t data)
{
    if (s->firstbyte) {
        s->reg = data;
        s->firstbyte = 0;
    } else {
        switch (s->reg) {
        case 0x02:
            if (data & 0x80) {
                bq27521_reset(s);
            }
            if (data & 0x40) {
                s->st &= ~(1 << 6);
            }
            data &= 0x3f;
            BQ27521_WRITE_LSB(ctrl);
            break;
        case 0x03:
            BQ27521_WRITE_MSB(ctrl);
            break;
        BQ27521_WRITE(0x04, c1);
        BQ27521_WRITE(0x06, c2);
        BQ27521_WRITE(0x26, cl);
        BQ27521_WRITE(0x28, ch);
        default:
            return -1;
        }
        s->reg++;
    }
    return 1;
}


/* Original N00 TWL5031 GP ADC callback and result byte packing. */
static int n00_sdk_adc_read(unsigned address)
{
    unsigned channel = (address - 0x37) >> 1;
    uint16_t value;
    switch (channel) {
    case 0: case 4: case 12: value = 0x2b9; break;
    case 1: value = 0x1ed; break;
    default: return -1;
    }
    return (address & 1) ? (value & 3) << 6 : (value >> 2) & 0xff;
}
#endif
