/* ARM Linux dynamic executable entry: delegate runtime startup to guest glibc.
 * No Harmattan CRT or SDK is required. All function arguments are integer/pointer.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
.syntax unified
.arm
.global _start
.type _start,%function
_start:
    mov fp, #0
    mov lr, #0
    mov r4, r0
    ldr r1, [sp], #4
    mov r2, sp
    push {r2}
    push {r4}
    mov r3, #0
    push {r3}
    ldr r0, =main
    bl __libc_start_main
    b .
.section .note.GNU-stack,"",%progbits
