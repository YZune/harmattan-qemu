/* Execute the production wire marshaller with adversarial guest memory and GL.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "n00_gles_wire.h"

typedef unsigned GLenum, GLuint;
typedef int GLint, GLsizei;
typedef unsigned char GLboolean;
#define MAX_TRANSFER (64 * 1024 * 1024)
#define g_new0(type, n) ((type *)calloc((n), sizeof(type)))
#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
#define cpu_to_le32(value) ((uint32_t)(value))
#define le32_to_cpu(value) ((uint32_t)(value))
#else
#define cpu_to_le32(value) __builtin_bswap32((uint32_t)(value))
#define le32_to_cpu(value) __builtin_bswap32((uint32_t)(value))
#endif
#define GL_COLOR_ATTACHMENT0 0x8CE0
#define GL_DEPTH_ATTACHMENT 0x8D00
#define GL_DEPTH_COMPONENT16 0x81A5
#define GL_FRAMEBUFFER 0x8D40
#define GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME 0x8CD1
#define GL_FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE 0x8CD0
#define GL_FRAMEBUFFER_ATTACHMENT_TEXTURE_CUBE_MAP_FACE 0x8CD3
#define GL_FRAMEBUFFER_ATTACHMENT_TEXTURE_LEVEL 0x8CD2
#define GL_FRAMEBUFFER_BINDING 0x8CA6
#define GL_NONE 0
#define GL_TEXTURE 0x1702
#define GL_FRAMEBUFFER_COMPLETE 0x8CD5
#define GL_INVALID_ENUM 0x0500
#define GL_INVALID_OPERATION 0x0502
#define GL_INVALID_VALUE 0x0501
#define GL_MAX_RENDERBUFFER_SIZE 0x84E8
#define GL_OUT_OF_MEMORY 0x0505
#define GL_RENDERBUFFER 0x8D41
#define GL_RENDERBUFFER_ALPHA_SIZE 0x8D53
#define GL_RENDERBUFFER_BINDING 0x8CA7
#define GL_RENDERBUFFER_BLUE_SIZE 0x8D52
#define GL_RENDERBUFFER_DEPTH_SIZE 0x8D54
#define GL_RENDERBUFFER_GREEN_SIZE 0x8D51
#define GL_RENDERBUFFER_HEIGHT 0x8D43
#define GL_RENDERBUFFER_INTERNAL_FORMAT 0x8D44
#define GL_RENDERBUFFER_RED_SIZE 0x8D50
#define GL_RENDERBUFFER_STENCIL_SIZE 0x8D55
#define GL_RENDERBUFFER_WIDTH 0x8D42
#define GL_RGB565 0x8D62
#define GL_RGB5_A1 0x8057
#define GL_RGBA4 0x8056
#define GL_STENCIL_ATTACHMENT 0x8D20
#define GL_STENCIL_INDEX8 0x8D48
#define GL_TEXTURE_2D 0x0DE1

typedef struct N00GLES {
    bool trace, trace_rejects;
    uint64_t render_rejects;
} N00GLES;
static N00GLES gpu;
typedef struct N00Client {
    N00GLES *s;
    unsigned nr, api, abi;
    uint32_t regs[16], call, result;
    GLenum gl_error;
    bool bad_memory, returned;
} N00Client;
typedef struct N00GL {
    void (*GenFramebuffers)(GLsizei, GLuint *);
    void (*GenRenderbuffers)(GLsizei, GLuint *);
    void (*DeleteFramebuffers)(GLsizei, const GLuint *);
    void (*DeleteRenderbuffers)(GLsizei, const GLuint *);
    void (*BindFramebuffer)(GLenum, GLuint);
    void (*BindRenderbuffer)(GLenum, GLuint);
    void (*FramebufferTexture2D)(GLenum, GLenum, GLenum, GLuint, GLint);
    void (*FramebufferRenderbuffer)(GLenum, GLenum, GLenum, GLuint);
    GLenum (*CheckFramebufferStatus)(GLenum);
    GLboolean (*IsFramebuffer)(GLuint);
    GLboolean (*IsRenderbuffer)(GLuint);
    void (*GetIntegerv)(GLenum, GLint *);
    void (*GetFramebufferAttachmentParameteriv)(GLenum, GLenum, GLenum, GLint *);
    void (*GetRenderbufferParameteriv)(GLenum, GLenum, GLint *);
    void (*RenderbufferStorage)(GLenum, GLenum, GLsizei, GLsizei);
} N00GL;
static uint8_t memory[4096];
static bool fail_write;
static unsigned guest_copies;
static bool guest_copy(N00Client *c, uint32_t address, void *data, size_t size, bool write)
{
    guest_copies++;
    if (!size) { return true; }
    if (!address || size > sizeof(memory) || address > sizeof(memory) - size ||
        (write && fail_write)) {
        c->bad_memory = true;
        return false;
    }
    if (write) { memcpy(memory + address, data, size); }
    else { memcpy(data, memory + address, size); }
    return true;
}
static uint32_t guest_word(N00Client *c, uint32_t address)
{
    uint32_t word = 0;
    guest_copy(c, address, &word, 4, false);
    return le32_to_cpu(word);
}
static bool put_word(N00Client *c, uint32_t address, uint32_t word)
{
    word = cpu_to_le32(word);
    return guest_copy(c, address, &word, 4, true);
}
#include "n00_gles_args.inc"
#include "n00_gles_render_error.inc"
#include "n00_gles_fbo.inc"

typedef struct Object {
    GLuint name;
    bool created, deleted;
    unsigned refs;
    struct Object *attachments[3];
    GLuint textures[3];
    GLint width, height, format;
} Object;
static Object fbos[512], rbos[512];
static GLuint bound_fbo, bound_rbo, next_name = 0x01020304;
static unsigned gen_calls, delete_calls, bind_calls, storage_calls, attach_calls, query_calls;
static bool fail_bind, fail_storage, fail_query, fail_gen, fail_attach;
static GLint host_maximum = 8192;
static GLenum host_error;

static Object *find(Object *objects, GLuint name, bool create)
{
    Object *empty = NULL;
    if (!name) { return NULL; }
    for (unsigned i = 0; i < 512; i++) {
        if (!objects[i].deleted && objects[i].name == name) { return &objects[i]; }
        if (!objects[i].name && !empty) { empty = &objects[i]; }
    }
    if (!create) { return NULL; }
    assert(empty);
    empty->name = name;
    return empty;
}
static void gen(Object *objects, GLsizei count, GLuint *names)
{
    gen_calls++;
    if (fail_gen) { host_error = GL_OUT_OF_MEMORY; return; }
    assert(count >= 0 && count <= R_FBO_NAMES);
    for (int i = 0; i < count; i++) {
        names[i] = next_name++;
        assert(!find(objects, names[i], false));
        find(objects, names[i], true);
    }
}
static void release_attachment(Object *fbo, unsigned slot)
{
    Object *rbo = fbo->attachments[slot];
    fbo->attachments[slot] = NULL;
    fbo->textures[slot] = 0;
    if (rbo && !--rbo->refs && rbo->deleted) { memset(rbo, 0, sizeof(*rbo)); }
}
static void delete(Object *objects, GLuint *binding, GLsizei count, const GLuint *names)
{
    delete_calls++;
    assert(count >= 0 && count <= R_FBO_NAMES);
    for (int i = 0; i < count; i++) {
        Object *o = find(objects, names[i], false);
        if (o) {
            if (objects == fbos) {
                for (unsigned j = 0; j < 3; j++) { release_attachment(o, j); }
                memset(o, 0, sizeof(*o));
            } else {
                Object *current = find(fbos, bound_fbo, false);
                o->deleted = true;
                for (unsigned j = 0; current && j < 3; j++) {
                    if (current->attachments[j] == o) { release_attachment(current, j); }
                }
                if (!o->refs) { memset(o, 0, sizeof(*o)); }
            }
        }
        if (*binding == names[i]) { *binding = 0; }
    }
}
static void gen_fbo(GLsizei n, GLuint *names) { gen(fbos, n, names); }
static void gen_rbo(GLsizei n, GLuint *names) { gen(rbos, n, names); }
static void delete_fbo(GLsizei n, const GLuint *names) { delete(fbos, &bound_fbo, n, names); }
static void delete_rbo(GLsizei n, const GLuint *names) { delete(rbos, &bound_rbo, n, names); }
static void bind(Object *objects, GLuint *binding, GLuint name)
{
    bind_calls++;
    if (fail_bind) { host_error = GL_INVALID_OPERATION; return; }
    *binding = name;
    Object *o = find(objects, name, true);
    if (o) { o->created = true; }
}
static void bind_fbo(GLenum target, GLuint name)
{
    assert(target == GL_FRAMEBUFFER); bind(fbos, &bound_fbo, name);
}
static void bind_rbo(GLenum target, GLuint name)
{
    assert(target == GL_RENDERBUFFER); bind(rbos, &bound_rbo, name);
}
static GLboolean is_fbo(GLuint name)
{
    Object *o = find(fbos, name, false); return o && o->created;
}
static GLboolean is_rbo(GLuint name)
{
    Object *o = find(rbos, name, false); return o && o->created;
}
static void get_integer(GLenum pname, GLint *value)
{
    switch (pname) {
    case GL_FRAMEBUFFER_BINDING: *value = bound_fbo; break;
    case GL_RENDERBUFFER_BINDING: *value = bound_rbo; break;
    case GL_MAX_RENDERBUFFER_SIZE: *value = host_maximum; break;
    default: assert(false);
    }
}
static void get_rbo(GLenum target, GLenum pname, GLint *value)
{
    assert(target == GL_RENDERBUFFER);
    query_calls++;
    if (fail_query) { host_error = GL_INVALID_OPERATION; return; }
    Object *o = find(rbos, bound_rbo, false);
    assert(o);
    switch (pname) {
    case GL_RENDERBUFFER_WIDTH: *value = o->width; break;
    case GL_RENDERBUFFER_HEIGHT: *value = o->height; break;
    case GL_RENDERBUFFER_INTERNAL_FORMAT: *value = o->format; break;
    case GL_RENDERBUFFER_DEPTH_SIZE: *value = 16; break;
    default: *value = 8; break;
    }
}
static void storage(GLenum target, GLenum format, GLsizei width, GLsizei height)
{
    storage_calls++;
    assert(target == GL_RENDERBUFFER && width >= 0 && height >= 0);
    Object *o = find(rbos, bound_rbo, false);
    assert(o);
    if (fail_storage) { host_error = GL_OUT_OF_MEMORY; return; }
    o->width = width; o->height = height; o->format = format;
}
static void get_attachment(GLenum target, GLenum attachment, GLenum pname, GLint *value)
{
    int slot = fbo_attachment(attachment);
    assert(target == GL_FRAMEBUFFER && slot >= 0);
    Object *fbo = find(fbos, bound_fbo, false);
    assert(fbo);
    query_calls++;
    if (fail_query) { host_error = GL_INVALID_OPERATION; return; }
    Object *rbo = fbo->attachments[slot];
    GLenum type = rbo ? GL_RENDERBUFFER : fbo->textures[slot] ? GL_TEXTURE : GL_NONE;
    if (pname == GL_FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE) { *value = type; }
    else if (pname == GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME && type != GL_NONE) {
        *value = rbo ? rbo->name : fbo->textures[slot];
    } else if (type == GL_TEXTURE) { *value = 0; }
    else { host_error = GL_INVALID_ENUM; }
}
static void attach_texture(GLenum target, GLenum attachment, GLenum textarget,
                           GLuint texture, GLint level)
{
    int slot = fbo_attachment(attachment);
    assert(target == GL_FRAMEBUFFER && slot >= 0);
    assert(textarget == GL_TEXTURE_2D && level == 0);
    Object *fbo = find(fbos, bound_fbo, false);
    assert(fbo);
    attach_calls++;
    if (fail_attach) { host_error = GL_INVALID_OPERATION; return; }
    release_attachment(fbo, slot);
    fbo->textures[slot] = texture;
}
static void attach_rbo(GLenum target, GLenum attachment, GLenum rbtarget, GLuint name)
{
    int slot = fbo_attachment(attachment);
    assert(target == GL_FRAMEBUFFER && slot >= 0 && rbtarget == GL_RENDERBUFFER);
    Object *fbo = find(fbos, bound_fbo, false);
    Object *rbo = find(rbos, name, false);
    assert(fbo);
    attach_calls++;
    if (fail_attach || (name && (!rbo || !rbo->created))) {
        host_error = GL_INVALID_OPERATION; return;
    }
    release_attachment(fbo, slot);
    fbo->attachments[slot] = rbo;
    if (rbo) { rbo->refs++; }
}
static GLenum status(GLenum target)
{
    assert(target == GL_FRAMEBUFFER); return GL_FRAMEBUFFER_COMPLETE;
}
static N00GL gl = {
    .GenFramebuffers = gen_fbo, .GenRenderbuffers = gen_rbo,
    .DeleteFramebuffers = delete_fbo, .DeleteRenderbuffers = delete_rbo,
    .BindFramebuffer = bind_fbo, .BindRenderbuffer = bind_rbo,
    .FramebufferTexture2D = attach_texture, .FramebufferRenderbuffer = attach_rbo,
    .CheckFramebufferStatus = status, .IsFramebuffer = is_fbo, .IsRenderbuffer = is_rbo,
    .GetIntegerv = get_integer, .GetFramebufferAttachmentParameteriv = get_attachment,
    .GetRenderbufferParameteriv = get_rbo, .RenderbufferStorage = storage,
};
static N00Client client;
static struct N00FBOState *state;
static void call(unsigned id, uint32_t a, uint32_t b, uint32_t c, uint32_t d)
{
    memset(&client, 0, sizeof(client));
    client.s = &gpu;
    client.nr = 1; client.api = 2; client.abi = 1;
    client.call = id;
    client.regs[0] = a; client.regs[1] = b; client.regs[2] = c; client.regs[3] = d;
    client.regs[13] = 128;
    assert(call_fbo(&client, &gl, &state));
}
#define CALL(name, a, b, c, d) call(N00_es20_gl##name, a, b, c, d)
static void ok(void) { assert(!client.gl_error && !client.bad_memory); }
static GLuint word(unsigned address) { return guest_word(&client, address); }
static unsigned active(Object *objects)
{
    unsigned n = 0;
    for (unsigned i = 0; i < 512; i++) { n += !!objects[i].name && !objects[i].deleted; }
    return n;
}

static void names_case(void)
{
    CALL(IsFramebuffer, 0, 0, 0, 0); ok();
    for (unsigned rb = 0; rb < 2; rb++) {
        unsigned genid = rb ? N00_es20_glGenRenderbuffers : N00_es20_glGenFramebuffers;
        unsigned delid = rb ? N00_es20_glDeleteRenderbuffers : N00_es20_glDeleteFramebuffers;
        unsigned before = gen_calls;
        call(genid, UINT32_MAX, 32, 0, 0);
        assert(client.gl_error == GL_INVALID_VALUE && gen_calls == before);
        call(genid, 129, 32, 0, 0);
        assert(client.gl_error == GL_INVALID_VALUE && gen_calls == before);
        uint32_t bad[] = { 0, sizeof(memory) - 2, UINT32_MAX - 1 };
        for (unsigned i = 0; i < sizeof(bad) / sizeof(*bad); i++) {
            call(genid, 1, bad[i], 0, 0);
            assert(client.bad_memory && gen_calls == before);
        }
        fail_write = true;
        call(genid, 2, 32, 0, 0);
        assert(client.bad_memory && gen_calls == before + 1);
        assert(active(rb ? rbos : fbos) == 0);
        fail_write = false;
        fail_gen = true;
        memset(memory + 32, 0xa5, 8);
        call(genid, 2, 32, 0, 0); ok();
        assert(word(32) == 0xa5a5a5a5 && active(rb ? rbos : fbos) == 0);
        fail_gen = false;
        if (rb) { state->next_renderbuffer = 0x01020303; }
        else { state->next_framebuffer = 0x01020303; }
        next_name = 0x01020304;
        memset(memory + 31, 0xa5, 10);
        call(genid, 2, 32, 0, 0); ok();
        assert(memory[31] == 0xa5 && memory[40] == 0xa5);
        assert(memory[32] == 4 && memory[33] == 3 && memory[34] == 2 && memory[35] == 1);
        assert(word(36) == 0x01020305 && active(rb ? rbos : fbos) == 2);
        unsigned deletes = delete_calls;
        call(delid, 2, sizeof(memory) - 4, 0, 0);
        assert(client.bad_memory && delete_calls == deletes);
        call(delid, UINT32_MAX, 32, 0, 0);
        assert(client.gl_error == GL_INVALID_VALUE && delete_calls == deletes);
        call(delid, 2, 32, 0, 0); ok();
        assert(active(rb ? rbos : fbos) == 0);
        call(genid, 0, 0, 0, 0); ok();
        call(delid, 0, 0, 0, 0); ok();
    }
}

static void limit_case(void)
{
    for (unsigned rb = 0; rb < 2; rb++) {
        unsigned genid = rb ? N00_es20_glGenRenderbuffers : N00_es20_glGenFramebuffers;
        unsigned delid = rb ? N00_es20_glDeleteRenderbuffers : N00_es20_glDeleteFramebuffers;
        unsigned bindid = rb ? N00_es20_glBindRenderbuffer : N00_es20_glBindFramebuffer;
        GLenum target = rb ? GL_RENDERBUFFER : GL_FRAMEBUFFER;
        fail_bind = true;
        call(bindid, target, 72, 0, 0); ok();
        assert(!fbo_object(state, !rb, 72, false) && host_error == GL_INVALID_OPERATION);
        fail_bind = false;
        call(bindid, target, 72, 0, 0); ok();
        assert(fbo_object(state, !rb, 72, false));
        call(genid, 127, 1024, 0, 0); ok();
        unsigned gens = gen_calls, binds = bind_calls;
        call(genid, 1, 32, 0, 0);
        assert(client.gl_error == GL_OUT_OF_MEMORY && gen_calls == gens);
        call(bindid, target, 9000, 0, 0);
        assert(client.gl_error == GL_OUT_OF_MEMORY && bind_calls == binds);
        call(bindid, target, 72, 0, 0); ok();
        call(bindid, target, 0, 0, 0); ok();
        put_word(&client, 32, 72); put_word(&client, 36, 72); put_word(&client, 40, 0);
        call(delid, 3, 32, 0, 0); ok();
        assert(!fbo_object(state, !rb, 72, false));
        if (rb) { state->next_renderbuffer = 71; }
        else { state->next_framebuffer = 71; }
        call(genid, 1, 32, 0, 0); ok();
        assert(word(32) == 72 && fbo_object(state, !rb, 72, false)->bytes == 0);
        call(delid, 1, 32, 0, 0); ok();
        call(delid, 127, 1024, 0, 0); ok();
        assert(active(rb ? rbos : fbos) == 0);
        next_name = 0x01020304;
    }
}

static void storage_case(void)
{
    CALL(BindRenderbuffer, GL_RENDERBUFFER, 7, 0, 0); ok();
    GLenum formats[] = {GL_RGBA4, GL_RGB5_A1, GL_RGB565, GL_DEPTH_COMPONENT16, GL_STENCIL_INDEX8};
    for (unsigned i = 0; i < sizeof(formats) / sizeof(*formats); i++) {
        CALL(RenderbufferStorage, GL_RENDERBUFFER, formats[i], 32, 16); ok();
        assert(state->bytes == 32 * 16 * 4);
    }
    unsigned calls = storage_calls;
    CALL(RenderbufferStorage, GL_FRAMEBUFFER, GL_RGBA4, 32, 16);
    assert(client.gl_error == GL_INVALID_ENUM && storage_calls == calls);
    CALL(RenderbufferStorage, GL_RENDERBUFFER, 0xdead, 32, 16);
    assert(client.gl_error == GL_INVALID_ENUM && storage_calls == calls);
    CALL(RenderbufferStorage, GL_RENDERBUFFER, GL_RGBA4, UINT32_MAX, 16);
    assert(client.gl_error == GL_INVALID_VALUE && storage_calls == calls);
    CALL(RenderbufferStorage, GL_RENDERBUFFER, GL_RGBA4, 4097, 16);
    assert(client.gl_error == GL_INVALID_VALUE && storage_calls == calls);
    host_maximum = 16;
    CALL(RenderbufferStorage, GL_RENDERBUFFER, GL_RGBA4, 32, 16);
    assert(client.gl_error == GL_INVALID_VALUE && storage_calls == calls);
    host_maximum = 8192;
    fail_storage = true;
    CALL(RenderbufferStorage, GL_RENDERBUFFER, GL_RGBA4, 4096, 4096); ok();
    assert(host_error == GL_OUT_OF_MEMORY && state->bytes == 32 * 16 * 4);
    fail_storage = false;
    CALL(RenderbufferStorage, GL_RENDERBUFFER, GL_RGBA4, 4096, 4096); ok();
    assert(state->bytes == MAX_TRANSFER);
    CALL(BindRenderbuffer, GL_RENDERBUFFER, 8, 0, 0); ok();
    calls = storage_calls;
    CALL(RenderbufferStorage, GL_RENDERBUFFER, GL_RGBA4, 1, 1);
    assert(client.gl_error == GL_OUT_OF_MEMORY && storage_calls == calls);
    CALL(BindRenderbuffer, GL_RENDERBUFFER, 7, 0, 0); ok();
    fail_storage = true;
    CALL(RenderbufferStorage, GL_RENDERBUFFER, GL_RGBA4, 1, 1); ok();
    assert(state->bytes == MAX_TRANSFER);
    fail_storage = false;
    CALL(RenderbufferStorage, GL_RENDERBUFFER, GL_RGBA4, 1, 1); ok();
    assert(state->bytes == 4);
    CALL(BindRenderbuffer, GL_RENDERBUFFER, 8, 0, 0); ok();
    CALL(RenderbufferStorage, GL_RENDERBUFFER, GL_RGB565, 1, 1); ok();
    assert(state->bytes == 8);
    put_word(&client, 32, 7); put_word(&client, 36, 8);
    CALL(DeleteRenderbuffers, 2, 32, 0, 0); ok();
    assert(state->bytes == 0 && bound_rbo == 0);
    CALL(RenderbufferStorage, GL_RENDERBUFFER, GL_RGBA4, 1, 1);
    assert(client.gl_error == GL_INVALID_OPERATION);
    CALL(BindRenderbuffer, GL_RENDERBUFFER, 7, 0, 0); ok();
    CALL(RenderbufferStorage, GL_RENDERBUFFER, GL_RGBA4, 0, 16); ok();
    assert(state->bytes == 0);
}

static void query_case(void)
{
    CALL(GenFramebuffers, 1, 32, 0, 0); ok();
    GLuint name = word(32);
    CALL(IsFramebuffer, name, 0, 0, 0); ok();
    assert(client.returned && client.result == 0);
    CALL(BindFramebuffer, GL_FRAMEBUFFER, name, 0, 0); ok();
    CALL(IsFramebuffer, name, 0, 0, 0); ok();
    assert(client.returned && client.result == 1);
    assert(fbo_guest_binding(state, GL_FRAMEBUFFER_BINDING, bound_fbo) == (GLint)name);
    assert(fbo_guest_binding(state, GL_FRAMEBUFFER_BINDING, 0) == 0);
    CALL(IsFramebuffer, 0, 0, 0, 0); ok(); assert(client.result == 0);
    CALL(CheckFramebufferStatus, GL_FRAMEBUFFER, 0, 0, 0); ok();
    assert(client.returned && client.result == GL_FRAMEBUFFER_COMPLETE);
    CALL(CheckFramebufferStatus, GL_RENDERBUFFER, 0, 0, 0);
    assert(client.returned && !client.result && client.gl_error == GL_INVALID_ENUM);
    put_word(&client, 136, 0);
    CALL(FramebufferTexture2D, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, 0x10203040); ok();
    memset(memory + 63, 0xa5, 6);
    CALL(GetFramebufferAttachmentParameteriv, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
         GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME, 64); ok();
    assert(word(64) == 0x10203040 && memory[64] == 0x40);
    assert(memory[63] == 0xa5 && memory[68] == 0xa5);
    unsigned queries = query_calls;
    CALL(GetFramebufferAttachmentParameteriv, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
         GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME, sizeof(memory) - 2);
    assert(client.bad_memory && query_calls == queries);
    CALL(GetFramebufferAttachmentParameteriv, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
         GL_RENDERBUFFER_WIDTH, 64);
    assert(client.gl_error == GL_INVALID_ENUM && word(64) == 0x10203040);
    CALL(GetFramebufferAttachmentParameteriv, GL_FRAMEBUFFER, 0xdead,
         GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME, 64);
    assert(client.gl_error == GL_INVALID_ENUM && word(64) == 0x10203040);
    fail_query = true;
    CALL(GetFramebufferAttachmentParameteriv, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
         GL_FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE, 64); ok();
    assert(word(64) == 0x10203040 && host_error == GL_INVALID_OPERATION);
    fail_query = false;
    CALL(BindFramebuffer, GL_FRAMEBUFFER, 0, 0, 0); ok();
    CALL(GetFramebufferAttachmentParameteriv, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
         GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME, 64);
    assert(client.gl_error == GL_INVALID_OPERATION && word(64) == 0x10203040);
    CALL(BindRenderbuffer, GL_RENDERBUFFER, 9, 0, 0); ok();
    CALL(IsRenderbuffer, 9, 0, 0, 0); ok(); assert(client.returned && client.result == 1);
    CALL(RenderbufferStorage, GL_RENDERBUFFER, GL_DEPTH_COMPONENT16, 31, 27); ok();
    CALL(GetRenderbufferParameteriv, GL_RENDERBUFFER, GL_RENDERBUFFER_WIDTH, 64, 0); ok();
    assert(word(64) == 31 && memory[68] == 0xa5);
    queries = query_calls;
    CALL(GetRenderbufferParameteriv, GL_RENDERBUFFER, GL_RENDERBUFFER_WIDTH, 0, 0);
    assert(client.bad_memory && queries == query_calls);
    CALL(GetRenderbufferParameteriv, GL_RENDERBUFFER, GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME, 64, 0);
    assert(client.gl_error == GL_INVALID_ENUM && word(64) == 31);
    struct N00FBOState *first = state;
    state = NULL;
    CALL(BindRenderbuffer, GL_RENDERBUFFER, 10, 0, 0); ok();
    assert(state != first && state->bytes == 0 && !fbo_object(state, false, 9, false));
    assert(first->bytes == 31 * 27 * 4);
    free(first);
    client.call = UINT32_MAX;
    assert(!call_fbo(&client, &gl, &state));
}

static void stack_case(void)
{
    CALL(BindFramebuffer, GL_FRAMEBUFFER, 1, 0, 0); ok();
    CALL(BindRenderbuffer, GL_RENDERBUFFER, 23, 0, 0); ok();
    put_word(&client, 136, 0);
    CALL(FramebufferTexture2D, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, 17); ok();
    assert(attach_calls == 1);
    put_word(&client, 136, 1);
    CALL(FramebufferTexture2D, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, 17);
    assert(client.gl_error == GL_INVALID_VALUE && attach_calls == 1);
    put_word(&client, 136, 0);
    CALL(FramebufferTexture2D, GL_FRAMEBUFFER, 0xdead, GL_TEXTURE_2D, 17);
    assert(client.gl_error == GL_INVALID_ENUM && attach_calls == 1);
    client.gl_error = 0; client.bad_memory = false;
    client.regs[1] = GL_COLOR_ATTACHMENT0;
    client.regs[13] = sizeof(memory) - 8;
    assert(call_fbo(&client, &gl, &state));
    assert(client.bad_memory && attach_calls == 1);
    client.bad_memory = false;
    client.regs[13] = UINT32_MAX - 3;
    assert(call_fbo(&client, &gl, &state));
    assert(client.bad_memory && attach_calls == 1);
    /* Four-register calls must never touch an invalid stack. */
    client.bad_memory = false;
    client.call = N00_es20_glFramebufferRenderbuffer;
    client.regs[2] = GL_RENDERBUFFER; client.regs[3] = 23;
    assert(call_fbo(&client, &gl, &state)); ok();
    assert(attach_calls == 2);
    CALL(FramebufferTexture2D, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, 17); ok();
    assert(attach_calls == 3);
}

static void lifetime_case(void)
{
    /* All 32 guest name bits survive signed GLint binding/query return values. */
    CALL(BindFramebuffer, GL_FRAMEBUFFER, UINT32_MAX, 0, 0); ok();
    CALL(BindRenderbuffer, GL_RENDERBUFFER, 0x80000000, 0, 0); ok();
    assert((uint32_t)fbo_guest_binding(state, GL_FRAMEBUFFER_BINDING, bound_fbo) == UINT32_MAX);
    assert((uint32_t)fbo_guest_binding(state, GL_RENDERBUFFER_BINDING, bound_rbo) == 0x80000000);
    CALL(FramebufferRenderbuffer, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, 0x80000000); ok();
    CALL(GetFramebufferAttachmentParameteriv, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
         GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME, 64); ok(); assert(word(64) == 0x80000000);
    put_word(&client, 32, UINT32_MAX); put_word(&client, 36, 0x80000000);
    CALL(DeleteFramebuffers, 1, 32, 0, 0); ok();
    CALL(DeleteRenderbuffers, 1, 36, 0, 0); ok();
    /* Private default objects occupy names that arbitrary guest names may match. */
    Object *internal_fbo = find(fbos, 1, true);
    Object *internal_rbo = find(rbos, 2, true);
    internal_fbo->created = internal_rbo->created = true;
    CALL(IsFramebuffer, 1, 0, 0, 0); ok(); assert(client.result == 0);
    CALL(IsRenderbuffer, 2, 0, 0, 0); ok(); assert(client.result == 0);
    put_word(&client, 32, 1); put_word(&client, 36, 2);
    unsigned deletes = delete_calls;
    CALL(DeleteFramebuffers, 1, 32, 0, 0); ok();
    CALL(DeleteRenderbuffers, 1, 36, 0, 0); ok();
    assert(delete_calls == deletes && internal_fbo->created && internal_rbo->created);
    CALL(BindFramebuffer, GL_FRAMEBUFFER, 1, 0, 0); ok();
    assert(bound_fbo != 1 && fbo_guest_binding(state, GL_FRAMEBUFFER_BINDING, bound_fbo) == 1);
    CALL(BindRenderbuffer, GL_RENDERBUFFER, 2, 0, 0); ok();
    assert(bound_rbo != 2 && fbo_guest_binding(state, GL_RENDERBUFFER_BINDING, bound_rbo) == 2);
    CALL(RenderbufferStorage, GL_RENDERBUFFER, GL_RGBA4, 4096, 4096); ok();
    CALL(FramebufferRenderbuffer, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, 2); ok();
    N00FBOObject *old = fbo_object(state, false, 2, false);
    GLuint old_host = old->host;
    assert(old->references == 1);
    CALL(BindFramebuffer, GL_FRAMEBUFFER, 0, 0, 0); ok();
    CALL(DeleteRenderbuffers, 1, 36, 0, 0); ok();
    assert(state->bytes == MAX_TRANSFER && !old->live && old->host == old_host);
    assert(find(rbos, old_host, false) && !bound_rbo);
    CALL(IsRenderbuffer, 2, 0, 0, 0); ok(); assert(client.result == 0);
    /* Reuse the guest name, retaining a different old host object and quota. */
    CALL(BindRenderbuffer, GL_RENDERBUFFER, 2, 0, 0); ok();
    N00FBOObject *replacement = fbo_object(state, false, 2, false);
    assert(replacement != old && replacement->host != old_host);
    unsigned allocations = storage_calls;
    CALL(RenderbufferStorage, GL_RENDERBUFFER, GL_RGBA4, 1, 1);
    assert(client.gl_error == GL_OUT_OF_MEMORY && storage_calls == allocations);
    CALL(BindFramebuffer, GL_FRAMEBUFFER, 1, 0, 0); ok();
    CALL(GetFramebufferAttachmentParameteriv, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
         GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME, 64); ok(); assert(word(64) == 2);
    fail_attach = true;
    CALL(FramebufferRenderbuffer, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, 2); ok();
    assert(state->bytes == MAX_TRANSFER && old->references == 1);
    fail_attach = false;
    /* Zero detaches ignore textarget and level, then release only the tombstone. */
    put_word(&client, 136, UINT32_MAX);
    CALL(FramebufferTexture2D, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, 0xdead, 0); ok();
    assert(state->bytes == 0 && !old->host && !find(rbos, old_host, false));
    CALL(RenderbufferStorage, GL_RENDERBUFFER, GL_RGBA4, 4, 4); ok();
    CALL(FramebufferRenderbuffer, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, 2); ok();
    CALL(FramebufferRenderbuffer, GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, 2); ok();
    assert(replacement->references == 2 && state->bytes == 64);
    CALL(GetFramebufferAttachmentParameteriv, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
         GL_FRAMEBUFFER_ATTACHMENT_TEXTURE_LEVEL, 64);
    assert(client.gl_error == GL_INVALID_ENUM && word(64) == 2);
    CALL(BindFramebuffer, GL_FRAMEBUFFER, 0, 0, 0); ok();
    CALL(DeleteRenderbuffers, 1, 36, 0, 0); ok();
    assert(state->bytes == 64 && !replacement->live);
    CALL(DeleteFramebuffers, 1, 32, 0, 0); ok();
    assert(state->bytes == 0 && !replacement->host);
    assert(internal_fbo->created && internal_rbo->created);
    /* Guest deletion of a currently attached RBO detaches, unbinds and reclaims. */
    CALL(BindFramebuffer, GL_FRAMEBUFFER, 1, 0, 0); ok();
    CALL(BindRenderbuffer, GL_RENDERBUFFER, 2, 0, 0); ok();
    CALL(RenderbufferStorage, GL_RENDERBUFFER, GL_RGBA4, 4, 4); ok();
    CALL(FramebufferRenderbuffer, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, 2); ok();
    CALL(DeleteRenderbuffers, 1, 36, 0, 0); ok();
    assert(state->bytes == 0 && !bound_rbo);
    CALL(GetFramebufferAttachmentParameteriv, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
         GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME, 64);
    assert(client.gl_error == GL_INVALID_ENUM && word(64) == 2);
    /* An unbound generated name must not replace an attachment. */
    CALL(GenRenderbuffers, 1, 80, 0, 0); ok();
    GLuint unbound = word(80);
    allocations = attach_calls;
    CALL(FramebufferRenderbuffer, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, unbound);
    assert(client.gl_error == GL_INVALID_OPERATION && attach_calls == allocations);
    CALL(FramebufferRenderbuffer, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, 0xdead, 0); ok();
    /* Failed manual detach conservatively retains its live storage reservation. */
    CALL(BindRenderbuffer, GL_RENDERBUFFER, 2, 0, 0); ok();
    CALL(RenderbufferStorage, GL_RENDERBUFFER, GL_RGBA4, 4, 4); ok();
    CALL(FramebufferRenderbuffer, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, 2); ok();
    fail_attach = true;
    CALL(DeleteRenderbuffers, 1, 36, 0, 0); ok();
    assert(state->bytes == 64);
    fail_attach = false;
    CALL(DeleteFramebuffers, 1, 32, 0, 0); ok();
    assert(state->bytes == 0);
}

static void diagnostic_case(void)
{
    client.s = &gpu;
    client.nr = 3; client.api = 2; client.abi = 2;
    client.call = N00_es20_glRenderbufferStorage;
    client.regs[0] = GL_RENDERBUFFER; client.regs[1] = 0x88f0;
    client.regs[2] = 864; client.regs[3] = 480;
    client.regs[13] = UINT32_MAX;
    unsigned copies = guest_copies;
    /* Quiet by default; preserve a preceding error while counting rejections. */
    assert(!render_error(&client, GL_INVALID_VALUE));
    assert(client.gl_error == GL_INVALID_VALUE && gpu.render_rejects == 1);
    gpu.render_rejects = 0;
    gpu.trace_rejects = true;
    for (unsigned i = 0; i < 70; i++) { assert(!render_error(&client, GL_INVALID_ENUM)); }
    assert(client.gl_error == GL_INVALID_VALUE && gpu.render_rejects == 70);
    assert(guest_copies == copies && !client.bad_memory);
}

static void wrong_binding_target_case(void)
{
    CALL(GenFramebuffers, 1, 32, 0, 0); ok();
    CALL(GenRenderbuffers, 1, 36, 0, 0); ok();
    GLuint fbo = word(32), rbo = word(36);
    unsigned binds = bind_calls;
    uint64_t rejects = gpu.render_rejects;
    /* Original compositor init() emitted precisely this call4/target8d41.
     * The wire dispatcher must reject it; caller adaptation cannot weaken GL. */
    CALL(BindFramebuffer, GL_RENDERBUFFER, fbo, 0, 0x000499c0);
    assert(client.gl_error == GL_INVALID_ENUM && !client.bad_memory);
    assert(bind_calls == binds && !bound_fbo && !bound_rbo);
    assert(gpu.render_rejects == rejects + 1);
    CALL(BindRenderbuffer, GL_RENDERBUFFER, rbo, 0, 0); ok();
    CALL(BindFramebuffer, GL_FRAMEBUFFER, fbo, 0, 0); ok();
    GLuint old_fbo = bound_fbo, old_rbo = bound_rbo;
    binds = bind_calls;
    CALL(BindFramebuffer, GL_RENDERBUFFER, fbo, 0, 0);
    assert(client.gl_error == GL_INVALID_ENUM && bind_calls == binds);
    CALL(BindRenderbuffer, GL_FRAMEBUFFER, rbo, 0, 0);
    assert(client.gl_error == GL_INVALID_ENUM && bind_calls == binds);
    assert(bound_fbo == old_fbo && bound_rbo == old_rbo);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    switch (atoi(argv[1])) {
    case 1: names_case(); break;
    case 2: limit_case(); break;
    case 3: storage_case(); break;
    case 4: query_case(); break;
    case 5: stack_case(); break;
    case 6: lifetime_case(); break;
    case 7: diagnostic_case(); break;
    case 8: wrong_binding_target_case(); break;
    default: assert(false);
    }
    free(state);
    puts("PASS");
    return 0;
}
