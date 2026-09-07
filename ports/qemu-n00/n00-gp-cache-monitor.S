/* SPDX-License-Identifier: GPL-2.0-only OR GPL-3.0-only
 * Restricted OMAP3 GP ROM service for QEMU TCG; not an HS/BB5 monitor.
 * Linked at zero, where the Cortex-A8 reset MVBAR points.
 * API 1 = L2 invalidate (U-Boot arch/arm/include/asm/arch-omap3/omap.h).
 * QEMU models coherent guest memory, without a data-cache array. Barriers
 * suffice for this operation; no authentication or storage API is provided.
 */
.syntax unified
.arch armv7-a
.arch_extension sec
.arm
.section .text
.global _start
_start:
    b rejected
    b rejected
    b smc_entry
    b rejected
    b rejected
    b rejected
    b rejected
    b rejected
smc_entry:
    /* SP_mon is private scratch: no caller memory or stack is required. */
    mov sp, r0
    mrs r0, spsr
    and r0, r0, #0x3f
    cmp r0, #0x13              /* ARM SVC only, never Thumb/Monitor. */
    bne rejected
    mrs r0, spsr
    tst r0, #0x200             /* Little endian caller only. */
    bne rejected
    cmp r12, #1
    bne rejected
    ldr r0, [lr, #-4]
    bic r0, r0, #0xf0000000    /* Accept executed conditional SMC #0. */
    eor r0, r0, #0x01600000
    eors r0, r0, #0x70
    bne rejected
    dsb sy
    isb sy
    mov r0, sp
    movs pc, lr                /* Restore SPSR, caller mode and flags. */
    .org 0x80
rejected:
    b rejected                /* Unsupported calls never return success. */
