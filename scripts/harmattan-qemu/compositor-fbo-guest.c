/* SPDX-License-Identifier: GPL-2.0-or-later
 * Opt-in process-local correction for PR1.3 libmcompositor.so.1.1.3 only.
 * SHA256 e9fcdb50530076abce62aaae65f5116a71badc283c89111a0d5e38f13b4a8c1b
 * MCompositeWindowGroup::init() loads GL_RENDERBUFFER at +0x64 before
 * calling glBindFramebuffer at +0x70, returning to +0x74. The generated
 * object is the framebuffer stored at private+8. Later calls use correct
 * targets. Preserve the original binary and every other GL call/error.
 * Build and guest startup verify the full library hash; this guard verifies
 * the loaded function and callsite before permitting the one correction.
 */
extern void *dlsym(void *, const char *);
extern int write(int, const void *, unsigned);
extern void _exit(int) __attribute__((noreturn));
void glBindFramebuffer(unsigned target, unsigned framebuffer);
typedef void (*BindFramebuffer)(unsigned, unsigned);
typedef __UINTPTR_TYPE__ Address;

static BindFramebuffer original_bind;
static const unsigned char *group_init;
static int corrected;

static void fail(void)
{
    static const char message[] = "N00_COMPOSITOR_FBO_TARGET_ERROR unsupported ABI\n";
    write(2, message, sizeof(message) - 1);
    _exit(123);
}

static void initialize(void)
{
    static const unsigned char entry[] = {0xf0, 0x49, 0x2d, 0xe9, 0x02, 0x8b, 0x2d, 0xed};
    static const unsigned char site[] = {
        0x41, 0x0d, 0x08, 0xe3, /* movw r0, #0x8d41 */
        0x08, 0x10, 0x95, 0xe5, /* ldr r1, [r5, #8] */
        0x34, 0x70, 0x4b, 0xe2, /* sub r7, r11, #52 */
        0x04, 0xf0, 0xff, 0xeb  /* bl glBindFramebuffer@PLT */
    };
    original_bind = (BindFramebuffer)dlsym((void *)-1, "glBindFramebuffer");
    group_init = dlsym((void *)-1, "_ZN21MCompositeWindowGroup4initEv");
    if (!original_bind || original_bind == glBindFramebuffer ||
        !group_init || ((Address)group_init & 3)) fail();
    for (unsigned i = 0; i < sizeof(entry); i++) {
        if (group_init[i] != entry[i]) fail();
    }
    for (unsigned i = 0; i < sizeof(site); i++) {
        if (group_init[0x64 + i] != site[i]) fail();
    }
    static const char message[] = "N00_COMPOSITOR_FBO_TARGET_GUARD_READY\n";
    write(1, message, sizeof(message) - 1);
}

static void bind_from(unsigned target, unsigned framebuffer, const void *caller)
{
    if (!original_bind) initialize();
    if (target == 0x8d41 && caller == group_init + 0x74) {
        target = 0x8d40;
        if (!corrected) {
            static const char message[] = "N00_COMPOSITOR_FBO_TARGET_FIXED site=init+0x74\n";
            write(1, message, sizeof(message) - 1);
            corrected = 1;
        }
    }
    original_bind(target, framebuffer);
}

void glBindFramebuffer(unsigned target, unsigned framebuffer)
{
    bind_from(target, framebuffer, __builtin_return_address(0));
}
