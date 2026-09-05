/* Preserve the original eight-word ABI probe and add a twelve-word gateway.
 * TexImage2D/TexSubImage2D need nine words, including five on the stack.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "probe-armel-gles.S"
.text
.global n00_render_call
.type n00_render_call,%function
n00_render_call:
    push {r4-r10,lr}
    add r9, r0, r1, lsl #2
    mov r8, r2
    add r10, r2, #16
    ldmia r10, {r0-r7}
    push {r0-r7}
    ldmia r8, {r0-r3}
    push {r8-r9}
    str r9, [r9]
1:  ldr r8, [r9]
    cmp r8, #0
    bne 1b
    pop {r8-r9}
    add sp, sp, #32
    pop {r4-r10,pc}
.section .note.GNU-stack,"",%progbits
