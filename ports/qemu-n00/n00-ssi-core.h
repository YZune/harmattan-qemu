/*
 * N00 SSI controller, frame-buffer and basic GDD transfer model.
 * Register/driver contracts derived from Nokia's GPLv2 plat/ssi.h and
 * drivers/hsi/controllers/omap_ssi.c, kernel 2.6.32-20121301+0m8.
 * Those sources: Copyright (C) 2010 Nokia Corporation. All rights reserved.
 * SPDX-License-Identifier: GPL-2.0-only
 *
 * One port, eight channels, one pending word per direction/channel.
 * No modem, SIM, secure identity or network state is synthesized here.
 * Clock timing, multipoint arbitration and linked GDD are not implemented.
 */
#ifndef N00_SSI_CORE_H
#define N00_SSI_CORE_H
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#define N00_SSI_BASE 0x48058000u
#define N00_SSI_TX 0x2000u
#define N00_SSI_RX 0x2800u
#define N00_SSI_CHANNELS 8

typedef struct N00SSIGDD {
    uint16_t csdp, ccr, cicr, csr, count, done, link;
    uint32_t src, dst;
} N00SSIGDD;

typedef struct N00SSICore {
    uint32_t sysconfig, irq_enable[2], events, wake;
    uint32_t gdd_enable, gdd_status, gdd_gcr;
    uint32_t tx[8], rx[8], tx_full, rx_full;
    uint32_t mode[2], frame[2], channels[2], divisor, arbitration;
    uint32_t rx_error, rx_overrun, rx_break, timeout;
    N00SSIGDD dma[8];
    /* Caller supplies RAM-only little-endian accesses, rejecting all MMIO. */
    bool (*memory)(void *opaque, uint32_t address, uint32_t *word, bool write);
    void *opaque;
    bool loopback; /* Explicit test fixture, never a cellular-service peer. */
} N00SSICore;

static void n00_ssi_reset(N00SSICore *s)
{
    bool (*memory)(void *, uint32_t, uint32_t *, bool) = s->memory;
    void *opaque = s->opaque;
    bool loopback = s->loopback;
    memset(s, 0, sizeof(*s));
    s->memory = memory;
    s->opaque = opaque;
    s->loopback = loopback;
    s->frame[0] = s->frame[1] = 31;
    s->channels[0] = s->channels[1] = 4;
}

static uint32_t n00_ssi_channel_mask(uint32_t channels)
{
    return channels <= 8 ? (1u << channels) - 1 : 0;
}

static uint32_t n00_ssi_status(N00SSICore *s)
{
    uint32_t tx = s->mode[0] && s->mode[0] <= 2 ?
                  n00_ssi_channel_mask(s->channels[0]) & ~s->tx_full : 0;
    uint32_t rx = s->mode[1] && s->mode[1] <= 2 ? s->rx_full : 0;
    return tx | (rx << 8) | (s->rx_overrun << 16) |
           (s->rx_error ? 1u << 24 : 0) | (s->rx_break ? 1u << 25 : 0) | s->events;
}

static bool n00_ssi_receive(N00SSICore *s, unsigned ch, uint32_t word)
{
    if (ch >= s->channels[1] || ch >= 8 || !s->mode[1] || s->mode[1] > 2) {
        return false;
    }
    if (s->rx_full & (1u << ch)) {
        s->rx_overrun |= 1u << ch;
        return false;
    }
    s->rx[ch] = word & (UINT32_MAX >> (31 - s->frame[1]));
    s->rx_full |= 1u << ch;
    return true;
}

static void n00_ssi_dma_end(N00SSICore *s, unsigned ch, uint16_t status)
{
    N00SSIGDD *d = &s->dma[ch];
    d->ccr &= ~0x80;
    d->csr |= status;
    if (d->cicr & status) {
        s->gdd_status |= 1u << ch;
    }
}

/* Transfer only the 32-bit, one-port, unlinked format used by the original
 * driver. A disconnected TX fills its hardware buffer then stalls; RX stays
 * pending. Never acknowledge data on behalf of a nonexistent peer.
 */
static void n00_ssi_pump(N00SSICore *s)
{
    bool progress;
    do {
        progress = false;
        for (unsigned i = 0; i < 8; i++) {
            N00SSIGDD *d = &s->dma[i];
            if (!(d->ccr & 0x80)) {
                continue;
            }
            unsigned sync = d->ccr & 0x1f;
            bool rx = sync >= 0x10 && sync <= 0x17;
            unsigned ch = rx ? sync - 0x10 : sync - 1;
            unsigned src_port = (d->csdp >> 2) & 0xf;
            unsigned dst_port = (d->csdp >> 9) & 0xf;
            uint32_t peripheral = N00_SSI_BASE + (rx ? N00_SSI_RX : N00_SSI_TX) + 0x80 + 4 * ch;
            if (ch >= 8 || (d->csdp & 3) != 2 || (d->link & 0x8000) ||
                (d->cicr & 4) || s->mode[rx] > 2 || s->frame[rx] != 31 ||
                (d->ccr & 0xf000) != 0x1000 || !d->count || d->done >= d->count ||
                src_port != (rx ? 9u : 8u) || dst_port != (rx ? 8u : 9u) ||
                (rx ? d->src : d->dst) != peripheral) {
                n00_ssi_dma_end(s, i, 1); /* GDD timeout/error, never BLOCK. */
                continue;
            }
            uint32_t bit = 1u << ch;
            if (!s->mode[rx] || ch >= s->channels[rx] ||
                (rx ? !(s->rx_full & bit) : !!(s->tx_full & bit))) {
                continue;
            }
            uint32_t address = (rx ? d->dst : d->src) + 4u * d->done;
            uint32_t word = rx ? s->rx[ch] : 0;
            if (address < (rx ? d->dst : d->src) || !s->memory ||
                !s->memory(s->opaque, address, &word, rx)) {
                n00_ssi_dma_end(s, i, 1);
                continue;
            }
            if (rx) {
                s->rx_full &= ~bit;
            } else {
                s->tx[ch] = word;
                s->tx_full |= bit;
            }
            progress = true;
            if (++d->done == d->count) {
                n00_ssi_dma_end(s, i, 0x20);
            }
        }
        if (s->loopback && s->mode[0] && s->mode[0] <= 2 && s->mode[1]) {
            for (unsigned ch = 0; ch < 8; ch++) {
                uint32_t bit = 1u << ch;
                if ((s->tx_full & bit) && !(s->rx_full & bit) &&
                    n00_ssi_receive(s, ch, s->tx[ch])) {
                    s->tx_full &= ~bit;
                    progress = true;
                }
            }
        }
        /* Each pass consumes a bounded DMA element or moves a pending word.
         * No peer + no DMA progress ends the loop immediately. */
    } while (progress);
}

static bool n00_ssi_gdd_access(N00SSICore *s, uint32_t a, uint32_t *v,
                               unsigned size, bool write)
{
    unsigned ch = (a - 0x1800) / 0x40;
    unsigned reg = (a - 0x1800) % 0x40;
    if (ch >= 8) {
        return false;
    }
    N00SSIGDD *d = &s->dma[ch];
    uint16_t *half = NULL;
    switch (reg) {
    case 0: half = &d->csdp; break;
    case 2: half = &d->ccr; break;
    case 4: half = &d->cicr; break;
    case 6:
        if (size != 2) { return false; }
        if (!write) { *v = d->csr; d->csr = 0; }
        return true;
    case 8: case 12:
        if (size != 4) { return false; }
        if (write) { *(reg == 8 ? &d->src : &d->dst) = *v; }
        else { *v = reg == 8 ? d->src : d->dst; }
        return true;
    case 0x10: half = &d->count; break;
    case 0x18: case 0x1a:
        if (size != 2) { return false; }
        if (!write) {
            bool rx = (d->ccr & 0x1f) >= 0x10;
            uint32_t address = reg == 0x18 ? d->src : d->dst;
            if ((reg == 0x1a) == rx) { address += 4u * d->done; }
            *v = address & 0xffff;
        }
        return true;
    case 0x28: half = &d->link; break;
    default: return false;
    }
    if (size != 2) { return false; }
    if (write) {
        if (reg == 2 && !(*half & 0x80) && (*v & 0x80)) {
            d->done = 0;
            d->csr = 0;
        }
        *half = *v;
    } else {
        *v = *half;
    }
    return true;
}

static bool n00_ssi_access(N00SSICore *s, uint32_t a, uint32_t *v,
                           unsigned size, bool write)
{
    if (a >= 0x1800 && a < 0x1a00) {
        return n00_ssi_gdd_access(s, a, v, size, write);
    }
    if (size != 4 || (a & 3)) { return false; }
    uint32_t *reg = NULL, mask = UINT32_MAX;
    switch (a) {
    case 0: if (!write) { *v = 0x10; } return true;
    case 0x10:
        if (write && (*v & 2)) { n00_ssi_reset(s); return true; }
        reg = &s->sysconfig; mask = 0x3019; break;
    case 0x14: if (!write) { *v = 1; } return true;
    case 0x800:
        if (write) { s->gdd_status &= ~*v; } else { *v = s->gdd_status; }
        return true;
    case 0x804: reg = &s->gdd_enable; mask = 0xff; break;
    case 0x808: case 0x810:
        if (write) { s->events &= ~*v; } else { *v = n00_ssi_status(s); }
        return true;
    case 0x80c: reg = &s->irq_enable[0]; mask = 0x3ffffff; break;
    case 0x814: reg = &s->irq_enable[1]; mask = 0x3ffffff; break;
    case 0xc00: if (!write) { *v = s->wake; } return true;
    case 0xc04:
        if (write) { s->wake &= ~(*v & 0xff); } else { *v = 0; }
        return true;
    case 0xc08:
        if (write) { s->wake |= *v & 0xff; } else { *v = 0; }
        return true;
    case 0x1100: reg = &s->gdd_gcr; mask = 0xd; break;
    case 0x1200:
        if (write && (*v & 1)) {
            memset(s->dma, 0, sizeof(s->dma));
            s->gdd_status = s->gdd_enable = s->gdd_gcr = 0;
        } else if (!write) { *v = 0; }
        return true;
    default: break;
    }
    if (reg) {
        if (write) { *reg = *v & mask; } else { *v = *reg; }
        return true;
    }
    if (a < N00_SSI_TX || a >= N00_SSI_RX + 0x800) { return false; }
    bool rx = a >= N00_SSI_RX;
    uint32_t offset = a - (rx ? N00_SSI_RX : N00_SSI_TX);
    uint32_t *full = rx ? &s->rx_full : &s->tx_full;
    uint32_t *buffer = rx ? s->rx : s->tx;
    if ((offset >= 0x80 && offset < 0xa0) || (offset >= 0xc0 && offset < 0xe0)) {
        unsigned ch = (offset & 0x3f) >> 2;
        uint32_t bit = 1u << ch;
        if (write && !rx && !(*full & bit)) {
            buffer[ch] = (offset < 0xc0 ? *v : __builtin_bswap32(*v)) &
                         (UINT32_MAX >> (31 - s->frame[0]));
            *full |= bit;
        } else if (!write) {
            *v = offset < 0xc0 ? buffer[ch] : __builtin_bswap32(buffer[ch]);
            if (rx) { *full &= ~bit; }
        }
        return true;
    }
    switch (offset) {
    case 0: if (!write) { *v = 0; } return true;
    case 4: reg = &s->mode[rx]; mask = 3; break;
    case 8: reg = &s->frame[rx]; mask = 31; break;
    case 0xc:
        if (write && *v == 0) { *full = 0; }
        else if (!write) { *v = !rx && *full ? 1 : 0; }
        return true;
    case 0x10:
        if (write) { *full &= *v; } else { *v = *full; }
        return true;
    case 0x18: if (!rx) { reg = &s->divisor; mask = 127; } break;
    case 0x1c: if (rx) { reg = &s->rx_break; mask = 1; } break;
    case 0x20:
        if (rx) { if (!write) { *v = s->rx_error; } return true; }
        /* Transmit break has no receiver unless explicitly looped back. */
        if (write && *v && s->loopback) { s->rx_break = 1; }
        else if (!write) { *v = 0; }
        return true;
    case 0x24:
        if (rx) {
            if (write) { s->rx_error &= ~*v; } else { *v = 0; }
            return true;
        }
        reg = &s->channels[0]; mask = 0xf; break;
    case 0x28:
        reg = rx ? &s->channels[1] : &s->arbitration; mask = rx ? 0xf : 1; break;
    case 0x2c: if (rx) { if (!write) { *v = s->rx_overrun; } return true; } break;
    case 0x30:
        if (rx) {
            if (write) { s->rx_overrun &= ~*v; } else { *v = 0; }
            return true;
        }
        break;
    case 0x34: if (rx) { reg = &s->timeout; } break;
    default: break;
    }
    if (!reg) { return false; }
    if (write) { *reg = *v & mask; } else { *v = *reg; }
    return true;
}
#endif
