/* Freestanding ARMEL GLES2 textured-render test, not an application/Qt test.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "n00_gles_wire.h"
typedef unsigned int u32;
typedef unsigned char u8;
typedef unsigned short u16;
extern long linux_call(long, long, long, long, long, long, long);
extern u32 n00_render_call(void *, u32, const u32 *);
enum { W = 864, H = 480, BYTES = W * H * 4 };
static u8 swapped[BYTES + 32] __attribute__((aligned(4096)));
static u8 readback[BYTES + 32] __attribute__((aligned(4096)));
static void *egl, *gl;
/* Clang lowers large aggregate initializers to memcpy even with -fno-builtin. */
void *memcpy(void *destination, const void *source, unsigned length)
{
    volatile u8 *out = destination;
    const volatile u8 *in = source;
    for (unsigned i = 0; i < length; i++) {
        out[i] = in[i];
    }
    return destination;
}
#define CALL(base, nr, ...) n00_render_call(base, nr, (const u32[12]){__VA_ARGS__})
#define E(name, ...) CALL(egl, N00_egl_##name, __VA_ARGS__)
#define G(name, ...) CALL(gl, N00_es20_##name, __VA_ARGS__)
#define P(value) ((u32)(value))

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
static u32 shader(u32 type, const char **strings, const int *lengths, unsigned count)
{
    u32 object = G(glCreateShader, type);
    require(object, "create shader result register");
    G(glShaderSource, object, count, P(strings), P(lengths));
    G(glCompileShader, object);
    int status = -1;
    G(glGetShaderiv, object, 0x8b81, P(&status));
    if (!status) {
        char log[1024];
        G(glGetShaderInfoLog, object, sizeof(log), 0, P(log));
        say(log);
    }
    require(status == 1, "compile actual guest shader");
    return object;
}
static void expected(unsigned frame, unsigned x, unsigned y, u8 *r, u8 *g, u8 *b)
{
    unsigned cell = frame < 2 ? (x >= W / 2) : (x < W / 3 ? 0 : x < 2 * W / 3 ? 1 : 2);
    if (frame < 2) {
        *r = cell == 0 ? (y < H / 2 ? 255 : 0) : (y < H / 2 ? 0 : 255);
        *g = cell == 1 ? 255 : 0;
        *b = y >= H / 2 || (frame == 1 && cell == 0) ? 255 : 0;
    } else {
        static const u8 colors[6][3] = {{255, 0, 0}, {0, 255, 0},   {255, 255, 0},
                                        {0, 0, 255}, {0, 255, 255}, {255, 255, 255}};
        unsigned index = cell + (y >= H / 2 ? 3 : 0);
        *r = colors[index][0];
        *g = frame == 3 ? 0 : colors[index][1];
        *b = colors[index][2];
    }
}
static void check_frame(unsigned frame, u32 display, u32 surface)
{
    for (unsigned i = 0; i < BYTES + 32; i++) {
        swapped[i] = 0xa5;
        readback[i] = 0x5a;
    }
    G(glFinish, 0);
    G(glReadPixels, 0, 0, W, H, 0x1908, 0x1401, P(readback));
    require(E(eglSwapBuffers, display, surface), "swap textured frame to guest pages");
    require(!G(glGetError, 0), "GL error after textured draw/readback/swap");
    for (unsigned y = 0; y < H; y++) {
        for (unsigned x = 0; x < W; x++) {
            u8 r, g, b;
            expected(frame, x, y, &r, &g, &b);
            unsigned bottom = (y * W + x) * 4, top = ((H - 1 - y) * W + x) * 4;
            require(readback[bottom] == r && readback[bottom + 1] == g &&
                        readback[bottom + 2] == b && swapped[top] == b &&
                        swapped[top + 1] == g && swapped[top + 2] == r,
                    "textured RGBA/BGRA pixel mismatch");
        }
    }
    for (unsigned i = BYTES; i < BYTES + 32; i++) {
        require(swapped[i] == 0xa5 && readback[i] == 0x5a, "render buffer guard");
    }
}
static void vertex_pointers(u32 position, u32 uv)
{
    G(glVertexAttribPointer, 0, 2, 0x1406, 0, 16, position);
    G(glVertexAttribPointer, 1, 2, 0x1406, 0, 16, uv);
}
#ifdef N00_RENDER_NEGATIVE
static void reject_bad_inputs(u32 vertex_shader)
{
    G(glVertexAttribPointer, 16, 2, 0x1406, 0, 16, 0);
    require(G(glGetError, 0) == 0x501, "reject out-of-range attribute");
    G(glBufferSubData, 0x8892, 79, 2, P("xx"));
    require(G(glGetError, 0) == 0x501, "reject buffer update beyond allocation");
    G(glDrawElements, 4, 6, 0x1403, 14);
    require(G(glGetError, 0) == 0x502, "reject EBO overread");
    vertex_pointers(0xfffffff0u, 24);
    G(glDrawElements, 4, 6, 0x1403, 4);
    require(G(glGetError, 0) == 0x502, "reject VBO offset overflow");
    vertex_pointers(16, 24);
    G(glTexImage2D, 0x0de1, 0, 0x1908, 4097, 2, 0, 0x1908, 0x1401, 0);
    require(G(glGetError, 0) == 0x501, "reject oversized texture");
    G(glPixelStorei, 0x0cf5, 3);
    require(G(glGetError, 0) == 0x501, "reject invalid row alignment");
    u32 bad = 0xdead0000;
    int length = 32;
    G(glShaderSource, vertex_shader, 1, P(&bad), P(&length));
    require(G(glGetError, 0) == 0x502, "reject unmapped shader source");
    say("\nN00_GLES_RENDER_NEGATIVE_OK rejections=7\n");
}
#endif
int guest_main(void)
{
    long fd = linux_call(5, (long)"/dev/kfgles2", 2, 0, 0, 0, 0);
    require(fd >= 0, "open original kfgles2 module");
    egl = (void *)linux_call(192, 0, 4096, 3, 1, fd, 1);
    gl = (void *)linux_call(192, 0, 4096, 3, 1, fd, 3);
    require(P(egl) < 0xfffff000u && P(gl) < 0xfffff000u,
            "map original EGL/ES2 transport");
    u32 display = E(eglGetDisplay, 0), config = 0, count = 0;
    require(E(eglInitialize, display, 0, 0), "initialize EGL");
    require(E(eglBindAPI, 0x30a0), "bind GLES API");
    u32 attrs[] = {0x3024, 8, 0x3023, 8,  0x3022, 8, 0x3020, 32,
                   0x3040, 4, 0x3025, 24, 0x3026, 8, 0x3038};
    require(E(eglChooseConfig, display, P(attrs), P(&config), 1, P(&count)) && count,
            "choose render config");
    u32 ctx_attrs[] = {0x3098, 2, 0x3038};
    u32 context = E(eglCreateContext, display, config, 0, P(ctx_attrs));
    u32 drawable[] = {W, H, 24, 4, P(swapped)};
    u32 surface = E(eglCreateWindowSurface, display, config, P(drawable), 0);
    require(context && surface && E(eglMakeCurrent, display, surface, surface, context),
            "make render context current");
    G(glViewport, 0, 0, W, H);
    const char vertex_a[] = "attribute vec2 pos; attribute vec2 uv; varying vec2 tc;";
    const char vertex_b[] =
        "uniform mat4 matrix; void main(){tc=uv;gl_Position=matrix*vec4(pos,0.0,1.0);}";
    const char *vertex_sources[] = {vertex_a, vertex_b};
    int lengths[] = {sizeof(vertex_a) - 1, sizeof(vertex_b) - 1};
    u32 vs = shader(0x8b31, vertex_sources, lengths, 2);
    const char *fragment_source =
        "precision mediump float; varying vec2 tc; uniform sampler2D tex; uniform vec4 "
        "tint; void main(){gl_FragColor=texture2D(tex,tc)*tint;}";
    u32 fs = shader(0x8b30, &fragment_source, 0, 1);
    u32 bad = G(glCreateShader, 0x8b30);
    const char *bad_source = "this is not valid GLSL";
    int negative_length = -1, status = -1, log_length = -1;
    G(glShaderSource, bad, 1, P(&bad_source), P(&negative_length));
    G(glCompileShader, bad);
    G(glGetShaderiv, bad, 0x8b81, P(&status));
    require(status == 0, "bad shader must not compile");
    u8 log[96];
    for (unsigned i = 0; i < sizeof(log); i++) {
        log[i] = 0xa5;
    }
    G(glGetShaderInfoLog, bad, 64, P(&log_length), P(log));
    require(log_length > 0 && log_length < 64 && log[log_length] == 0,
            "bounded compiler log and NUL");
    for (unsigned i = 64; i < sizeof(log); i++) {
        require(log[i] == 0xa5, "shader log guard");
    }
    G(glDeleteShader, bad);
    say("\nN00_GLES_RENDER_SHADER_LOG_OK\n");
    u32 program = G(glCreateProgram, 0);
    G(glAttachShader, program, vs);
    G(glAttachShader, program, fs);
    G(glBindAttribLocation, program, 0, P("pos"));
    G(glBindAttribLocation, program, 1, P("uv"));
    G(glLinkProgram, program);
    G(glGetProgramiv, program, 0x8b82, P(&status));
    require(status == 1, "link textured program");
    G(glGetProgramInfoLog, program, 64, P(&log_length), P(log));
    require(log_length >= 0 && log_length < 64 && log[log_length] == 0,
            "program log writeback");
    require(G(glGetAttribLocation, program, P("uv")) == 1, "attribute name lookup");
    require(G(glGetUniformLocation, program, P("missing")) == 0xffffffffu,
            "signed location result");
    G(glUseProgram, program);
    int sampler = G(glGetUniformLocation, program, P("tex"));
    int matrix = G(glGetUniformLocation, program, P("matrix"));
    int tint = G(glGetUniformLocation, program, P("tint"));
    require(sampler >= 0 && matrix >= 0 && tint >= 0, "uniform locations");
    const float identity[16] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
    float color[4] = {1, 1, 1, 1};
    G(glUniform1i, sampler, 0);
    G(glUniformMatrix4fv, matrix, 1, 0, P(identity));
    G(glUniform4fv, tint, 1, P(color));
    u32 texture = 0;
    G(glGenTextures, 1, P(&texture));
    G(glActiveTexture, 0x84c0);
    G(glBindTexture, 0x0de1, texture);
    G(glTexParameteri, 0x0de1, 0x2801, 0x2600);
    G(glTexParameteri, 0x0de1, 0x2800, 0x2600);
    G(glTexParameteri, 0x0de1, 0x2802, 0x812f);
    G(glTexParameteri, 0x0de1, 0x2803, 0x812f);
    const u8 rgba[] = {255, 0, 0,   255, 0,   255, 0,   255,
                       0,   0, 255, 255, 255, 255, 255, 255};
    G(glTexImage2D, 0x0de1, 0, 0x1908, 2, 2, 0, 0x1908, 0x1401, P(rgba));
    const float client[7][4] = {{99, 99, 99, 99}, {-1, -1, 0, 0}, {1, -1, 1, 0},
                                {1, 1, 1, 1},     {-1, -1, 0, 0}, {1, 1, 1, 1},
                                {-1, 1, 0, 1}};
    G(glEnableVertexAttribArray, 0);
    G(glEnableVertexAttribArray, 1);
    vertex_pointers(P(client), P(client) + 8);
    G(glDrawArrays, 4, 1, 6);
    check_frame(0, display, surface);
    say("\nN00_GLES_RENDER_CLIENT_OK pixels=829440\n");
    u32 buffers[2] = {0, 0};
    G(glGenBuffers, 2, P(buffers));
    G(glBindBuffer, 0x8892, buffers[0]);
    G(glBufferData, 0x8892, 80, 0, 0x88e8);
    const float quad[4][4] = {
        {-1, -1, 0, 0}, {1, -1, 1, 0}, {1, 1, 1, 1}, {-1, 1, 0, 1}};
    G(glBufferSubData, 0x8892, 16, sizeof(quad), P(quad));
    vertex_pointers(16, 24);
    G(glBindBuffer, 0x8893, buffers[1]);
    const u16 indices[] = {99, 99, 0, 1, 2, 0, 2, 3};
    G(glBufferData, 0x8893, sizeof(indices), P(indices), 0x88e4);
#ifdef N00_RENDER_NEGATIVE
    reject_bad_inputs(vs);
#endif
    const u8 magenta[] = {255, 0, 255, 255};
    G(glTexSubImage2D, 0x0de1, 0, 0, 0, 1, 1, 0x1908, 0x1401, P(magenta));
    G(glDrawElements, 4, 6, 0x1403, 4);
    check_frame(1, display, surface);
    say("\nN00_GLES_RENDER_VBO_EBO_OK pixels=829440\n");
    G(glBindBuffer, 0x8892, 0);
    G(glBindBuffer, 0x8893, 0);
    vertex_pointers(P(quad), P(quad) + 8);
    /* RGB width=3: nine bytes per row, 12-byte aligned stride. */
    const u8 rgb[] = {255, 0, 0, 0,   255, 0,   255, 255, 0,   77, 88,
                      99,  0, 0, 255, 0,   255, 255, 255, 255, 255};
    G(glPixelStorei, 0x0cf5, 4);
    G(glTexImage2D, 0x0de1, 0, 0x1907, 3, 2, 0, 0x1907, 0x1401, P(rgb));
    G(glDrawElements, 4, 6, 0x1403, P(indices + 2));
    check_frame(2, display, surface);
    say("\nN00_GLES_RENDER_RGB_ALIGNMENT_OK pixels=829440\n");
    const u8 indices8[] = {0, 1, 2, 0, 2, 3};
    color[1] = 0;
    G(glUniform4fv, tint, 1, P(color));
    G(glDrawElements, 4, 6, 0x1401, P(indices8));
    check_frame(3, display, surface);
    say("\nN00_GLES_RENDER_INDEX8_TINT_OK pixels=829440\n");
    G(glPixelStorei, 0x0d05, 8);
    int alignment = 0;
    G(glGetIntegerv, 0x0d05, P(&alignment));
    require(alignment == 8, "query pack alignment");
    u8 packed[48];
    for (unsigned i = 0; i < sizeof(packed); i++) {
        packed[i] = 0xa5;
    }
    G(glReadPixels, 0, 0, 3, 2, 0x1908, 0x1401, P(packed));
    for (unsigned i = 0; i < sizeof(packed); i++) {
        unsigned inrow = i < 16 ? i : i - 16;
        u8 value =
            i < 28 && inrow < 12 ? (inrow % 4 == 0 || inrow % 4 == 3 ? 255 : 0) : 0xa5;
        require(packed[i] == value, "pack stride, padding and trailing guard");
    }
    G(glPixelStorei, 0x0d05, 4);
    say("\nN00_GLES_RENDER_PACK_ALIGNMENT_OK\n");
    long fb = linux_call(5, (long)"/dev/fb0", 1, 0, 0, 0, 0);
    require(fb >= 0 && linux_call(4, fb, (long)swapped, BYTES, 0, 0, 0) == BYTES,
            "present textured framebuffer");
    linux_call(6, fb, 0, 0, 0, 0, 0);
    G(glDisableVertexAttribArray, 0);
    G(glDisableVertexAttribArray, 1);
    G(glDeleteBuffers, 2, P(buffers));
    G(glDeleteTextures, 1, P(&texture));
    G(glUseProgram, 0);
    G(glDeleteProgram, program);
    G(glDeleteShader, vs);
    G(glDeleteShader, fs);
    require(!G(glGetError, 0), "render cleanup GL error");
    require(E(eglMakeCurrent, display, 0, 0, 0), "unbind render context");
    require(E(eglDestroySurface, display, surface), "destroy render surface");
    require(E(eglDestroyContext, display, context), "destroy render context");
    require(E(eglGetError, 0) == 0x3000, "render cleanup EGL error");
    linux_call(91, (long)gl, 4096, 0, 0, 0, 0);
    linux_call(91, (long)egl, 4096, 0, 0, 0, 0);
    linux_call(6, fd, 0, 0, 0, 0, 0);
    say("\nN00_GLES_RENDER_GUEST_OK\n");
    return 0;
}
