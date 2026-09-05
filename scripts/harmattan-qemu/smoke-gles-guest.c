/* Freestanding ARMEL wire-level test, NOT a third-party application.
 * Uses original Nokia call order and push-two-words gateway convention.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "n00_gles_wire.h"
typedef unsigned int u32;
typedef unsigned char u8;
extern long linux_call(long, long, long, long, long, long, long);
extern u32 n00_call(void *, u32, const u32 *);
extern u32 n00_float_call(void *, u32, const u32 *, u32);
enum { W = 864, H = 480, PIXELS = W * H, BYTES = PIXELS * 4 };
static u8 swap_pixels[BYTES + 32] __attribute__((aligned(4096)));
static u8 read_pixels[BYTES + 32] __attribute__((aligned(4096)));
static void *device;
static unsigned failures;

static void say(const char *text)
{
    unsigned length = 0;
    while (text[length]) {
        length++;
    }
    linux_call(4, 1, (long)text, length, 0, 0, 0);
}

static void require(int ok, const char *message)
{
    if (!ok) {
        say("\nN00_GLES_FAIL: ");
        say(message);
        say("\n");
        linux_call(1, 1, 0, 0, 0, 0, 0);
    }
}

static u32 call(void *base, u32 nr, u32 a, u32 b, u32 c, u32 d, u32 e, u32 f, u32 g)
{
    u32 args[8] = {a, b, c, d, e, f, g, 0};
    return n00_call(base, nr, args);
}

#define E(name, a, b, c, d, e)                                                         \
    call(egl, N00_egl_##name, (u32)(a), (u32)(b), (u32)(c), (u32)(d), (u32)(e), 0, 0)
#define G(name, a, b, c, d)                                                            \
    call(gl, version == 1 ? N00_es11_##name : N00_es20_##name, (u32)(a), (u32)(b),     \
         (u32)(c), (u32)(d), 0, 0, 0)
#define C(r, g, b, a) color(gl, version, abi, r, g, b, a)

static void color(void *gl, unsigned version, unsigned abi, u32 r, u32 g, u32 b, u32 a)
{
    u32 args[8] = {r, g, b, a, 0, 0, 0, 0};
    n00_float_call(gl, version == 1 ? N00_es11_glClearColor : N00_es20_glClearColor,
                   args, abi);
}

static void rgb(unsigned x, unsigned y, unsigned frame, u8 *r, u8 *g, u8 *b)
{
    /* y is OpenGL's bottom-up coordinate, not the offscreen BGRA row. */
    *r = frame ? 0 : 255;
    *g = frame ? 255 : 0;
    *b = frame ? 255 : 0;
    if (x < W / 2 && y < H / 2) {
        *r = 0;
        *g = 255;
        *b = 0;
    }
    if (x >= W / 2 && y >= H / 2) {
        *r = 0;
        *g = 0;
        *b = 255;
    }
}

static void check_pixels(unsigned frame)
{
    failures = 0;
    for (unsigned y = 0; y < H; y++) {
        for (unsigned x = 0; x < W; x++) {
            u8 r, g, b;
            rgb(x, y, frame, &r, &g, &b);
            unsigned bottom = (y * W + x) * 4;
            unsigned top = ((H - 1 - y) * W + x) * 4;
            if (read_pixels[bottom] != r || read_pixels[bottom + 1] != g ||
                read_pixels[bottom + 2] != b || swap_pixels[top] != b ||
                swap_pixels[top + 1] != g || swap_pixels[top + 2] != r) {
                failures++;
            }
        }
    }
    require(!failures, "RGBA readback / top-down BGRA swap mismatch");
    for (unsigned i = BYTES; i < BYTES + 32; i++) {
        require(swap_pixels[i] == 0xa5 && read_pixels[i] == 0x5a, "pixel buffer guard");
    }
}

static void exercise(unsigned version, unsigned abi, int use_kernel)
{
    u32 client = 0;
    long kfd = -1;
    void *egl, *gl;
    if (use_kernel) {
        /* Exercise the existing kernel module, not just /dev/mem. */
        kfd = linux_call(5, (long)"/dev/kfgles2", 2, 0, 0, 0, 0);
        require(kfd >= 0, "open original kfgles2 device");
        egl = (void *)linux_call(192, 0, 4096, 3, 1, kfd, 1);
        gl = (void *)linux_call(192, 0, 4096, 3, 1, kfd, version + 1);
        require((u32)egl < 0xfffff000u && (u32)gl < 0xfffff000u, "kfgles2 API mmap");
    } else {
        client = call(device, 0, abi, 0, 0, 0, 0, 0, 0);
        require(client > 0 && client <= N00_GLES_CLIENTS,
                "kernel init register return");
        egl = (u8 *)device + (client + 1) * N00_GLES_PAGE;
        gl = (u8 *)egl + version * N00_GLES_BLOCK;
    }
    u32 display = E(eglGetDisplay, 0, 0, 0, 0, 0);
    require((display & 0xffff0000) == 0xcafe0000, "32-bit EGL handle");
    u32 major = 0, minor = 0, config = 0, count = 0;
    require(E(eglInitialize, display, &major, &minor, 0, 0), "EGL initialize");
    require(major == 1 && minor == 4, "guest memory EGL version writeback");
    require(E(eglBindAPI, 0x30a0, 0, 0, 0, 0), "bind GLES API");
    u32 attrs[] = {0x3024, 8,      0x3023, 8,      0x3022,
                   8,      0x3020, 32,     0x3040, version == 1 ? 1 : 4,
                   0x3025, 24,     0x3026, 8,      0x3038};
    require(E(eglChooseConfig, display, attrs, &config, 1, &count) && count,
            "five-argument choose config / guest stack");
    u32 ctx_attrs[] = {0x3098, version, 0x3038};
    u32 context = E(eglCreateContext, display, config, 0, ctx_attrs, 0);
    require(context, "create context");
    u32 drawable[] = {W, H, 24, 4, (u32)swap_pixels};
    u32 surface = E(eglCreateWindowSurface, display, config, drawable, 0, 0);
    require(surface, "offscreen wire drawable");
    require(E(eglMakeCurrent, display, surface, surface, context, 0), "make current");
    G(glViewport, 0, 0, W, H);
    for (unsigned frame = 0; frame < 2; frame++) {
        for (unsigned i = 0; i < BYTES + 32; i++) {
            swap_pixels[i] = 0xa5;
            read_pixels[i] = 0x5a;
        }
        C(frame ? 0 : 0x3f800000, frame ? 0x3f800000 : 0, frame ? 0x3f800000 : 0,
          0x3f800000);
        G(glClear, 0x4000, 0, 0, 0);
        G(glEnable, 0x0c11, 0, 0, 0);
        G(glScissor, 0, 0, W / 2, H / 2);
        C(0, 0x3f800000, 0, 0x3f800000);
        G(glClear, 0x4000, 0, 0, 0);
        G(glScissor, W / 2, H / 2, W / 2, H / 2);
        C(0, 0, 0x3f800000, 0x3f800000);
        G(glClear, 0x4000, 0, 0, 0);
        G(glDisable, 0x0c11, 0, 0, 0);
        G(glFinish, 0, 0, 0, 0);
        call(gl, version == 1 ? N00_es11_glReadPixels : N00_es20_glReadPixels, 0, 0, W,
             H, 0x1908, 0x1401, (u32)read_pixels);
        require(E(eglSwapBuffers, display, surface, 0, 0, 0), "swap to guest pages");
        require(!G(glGetError, 0, 0, 0, 0), "GL error after readback and swap");
        check_pixels(frame);
    }
    long fb = linux_call(5, (long)"/dev/fb0", 1, 0, 0, 0, 0);
    require(fb >= 0, "open framebuffer");
    require(linux_call(4, fb, (long)swap_pixels, BYTES, 0, 0, 0) == BYTES,
            "present pixels");
    linux_call(6, fb, 0, 0, 0, 0, 0);
    require(E(eglMakeCurrent, display, 0, 0, 0, 0), "unbind");
    require(E(eglDestroySurface, display, surface, 0, 0, 0), "destroy surface");
    require(E(eglDestroyContext, display, context, 0, 0, 0), "destroy context");
    require(E(eglGetError, 0, 0, 0, 0, 0) == 0x3000, "EGL error at cleanup");
    if (kfd >= 0) {
        require(!linux_call(91, (long)gl, 4096, 0, 0, 0, 0), "unmap kernel GL");
        require(!linux_call(91, (long)egl, 4096, 0, 0, 0, 0),
                "unmap kernel EGL/client exit");
        linux_call(6, kfd, 0, 0, 0, 0, 0);
    } else {
        call(device, 1, client, 0, 0, 0, 0, 0, 0);
    }
    if (version == 1) {
        say("\nN00_GLES_ES1_KFGLES2_OK pixels=829440\n");
    } else if (use_kernel) {
        say("\nN00_GLES_ES2_KFGLES2_OK pixels=829440\n");
    } else {
        say("\nN00_GLES_ES2_SOFTFP_DIRECT_OK pixels=829440\n");
    }
}

#ifdef N00_GLES_NEGATIVE
static void exercise_errors(void)
{
    u32 client = call(device, 0, 1, 0, 0, 0, 0, 0, 0);
    require(client > 0 && client <= N00_GLES_CLIENTS, "negative test client");
    void *egl = (u8 *)device + (client + 1) * N00_GLES_PAGE;
    u32 display = E(eglGetDisplay, 0, 0, 0, 0, 0);
    u32 config = 0, count = 0;
    require(E(eglInitialize, display, 0, 0, 0, 0), "optional null outputs");
    require(!E(eglChooseConfig, display, 0xffffff00u, &config, 1, &count),
            "reject overflowed guest attribute pointer");
    require(E(eglGetError, 0, 0, 0, 0, 0) == 0x300c, "bad pointer EGL error");
    require(!E(eglCreateContext, display, display, 0, 0, 0),
            "reject wrong handle type");
    require(E(eglGetError, 0, 0, 0, 0, 0) == 0x300c, "bad handle EGL error");
    require(!call((u8 *)device + N00_GLES_CALL_BYTES, 0, 7, 0, 0, 0, 0, 0, 0),
            "reject call-field padding, not an alias of init");
    require(!call((u8 *)device + 63 * N00_GLES_PAGE, N00_egl_eglGetDisplay, 7, 0, 0, 0,
                  0, 0, 0),
            "reject unallocated last client page");
    call(device, 1, client, 0, 0, 0, 0, 0, 0);
    say("\nN00_GLES_NEGATIVE_OK\n");
}
#endif

int guest_main(void)
{
    long fd = linux_call(5, (long)"/dev/mem", 2, 0, 0, 0, 0);
    require(fd >= 0, "open /dev/mem");
    device = (void *)linux_call(192, 0, 0x100000, 3, 1, fd, N00_GLES_BASE / 4096);
    require((u32)device < 0xfffff000u, "map original MMIO aperture");
#ifdef N00_GLES_NEGATIVE
    exercise_errors();
#endif
    exercise(1, 2, 1);
    exercise(2, 2, 1);
    exercise(2, 1, 0);
    linux_call(91, (long)device, 0x100000, 0, 0, 0, 0);
    linux_call(6, fd, 0, 0, 0, 0, 0);
    say("\nN00_GLES_GUEST_OK\n");
    return 0;
}
