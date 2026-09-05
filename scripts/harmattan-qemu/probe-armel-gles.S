/* ARMEL Linux, no libc. Nokia's gateway pushes two words before STR.
 * Set both core-register and VFP arguments so one probe can test both ABIs.
 */
.syntax unified
.arm
.global _start
.type _start,%function
_start:
    bl guest_main
    mov r7, #1
    svc #0

.global n00_call
.type n00_call,%function
n00_call:
    mov r3, #0
.global n00_float_call
.type n00_float_call,%function
n00_float_call:
    push {r4-r8,lr}
    mov r8, r3
    add r4, r0, r1, lsl #2
    mov r5, r2
    add r6, r5, #16
    ldmia r6, {r0-r3}
    push {r0-r3}
    vldmia r5, {s0-s3}
    ldmia r5, {r0-r3}
    /* Deliberately poison the unused floating argument channel. */
    cmp r8, #1
    bne 2f
    mov r6, #0
    vmov s0, r6
    vmov s1, r6
    vmov s2, r6
    vmov s3, r6
2:  cmp r8, #2
    moveq r0, #0
    moveq r1, #0
    moveq r2, #0
    moveq r3, #0
    push {r4-r5}
    str r4, [r4]
1:  ldr r5, [r4]
    cmp r5, #0
    bne 1b
    pop {r4-r5}
    add sp, sp, #16
    pop {r4-r8,pc}

.global linux_call
.type linux_call,%function
linux_call:
    push {r4-r7,lr}
    ldr r4, [sp, #20]
    ldr r5, [sp, #24]
    ldr r6, [sp, #28]
    mov r7, r0
    mov r0, r1
    mov r1, r2
    mov r2, r3
    mov r3, r4
    mov r4, r5
    mov r5, r6
    svc #0
    pop {r4-r7,pc}
.section .note.GNU-stack,"",%progbits
