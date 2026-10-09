/* Host-only test of Nokia DGLES2, not evidence of guest/QEMU rendering. */
#define MESA_EGL_NO_X11_HEADERS
#include <EGL/egl.h>
#include <EGL/eglext.h>
#ifdef DGLES_TEST_ES1
#include <GLES/gl.h>
#else
#include <GLES2/gl2.h>
#endif
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#ifdef __linux__
#include <dlfcn.h>
#include <sys/mman.h>
#include <unistd.h>
#endif

enum { WIDTH = 64, HEIGHT = 48 };
#ifdef __linux__
static unsigned char *pixels;
static int cleanup_mode, cleanup_done, worker_ready, release_worker;
static pthread_mutex_t exit_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t exit_cond = PTHREAD_COND_INITIALIZER;

static void process_exit_marker(void)
{
    if (!cleanup_done) {
        fputs("FAIL: process exit before graphics cleanup\n", stderr);
        _exit(1);
    }
    puts("PROCESS_EXIT_AFTER_JOIN_OK");
}

static void finish_worker(pthread_t worker)
{
    if (cleanup_done) return;
    pthread_mutex_lock(&exit_lock);
    release_worker = 1;
    pthread_cond_broadcast(&exit_cond);
    pthread_mutex_unlock(&exit_lock);
    if (pthread_join(worker, NULL) != 0) _exit(1);
    cleanup_done = 1;
    puts("GLES_WORKER_JOIN_OK");
}
#else
static unsigned char pixels[WIDTH * HEIGHT * 4];
#endif
static unsigned swap_count;

static void swapped(void *opaque)
{
    ++*(unsigned *)opaque;
}

static void require(int ok, const char *operation)
{
    if (!ok) {
        fprintf(stderr, "FAIL: %s (EGL=0x%x)\n", operation, eglGetError());
        exit(1);
    }
}

#ifndef DGLES_TEST_ES1
static GLuint shader(GLenum type, const char *source)
{
    GLuint object = glCreateShader(type);
    GLint compiled = 0;
    glShaderSource(object, 1, &source, NULL);
    glCompileShader(object);
    glGetShaderiv(object, GL_COMPILE_STATUS, &compiled);
    if (!compiled) {
        char message[4096] = {0};
        glGetShaderInfoLog(object, sizeof(message), NULL, message);
        fprintf(stderr, "%s\n", message);
    }
    require(compiled, "compile GLES2 shader");
    return object;
}
#endif

static int rgb_matches(size_t pixel, unsigned r, unsigned g, unsigned b)
{
    /* Nokia's offscreen swap returns BGRA; alpha is not part of this test. */
    const unsigned char *p = pixels + pixel * 4;
    return p[0] == b && p[1] == g && p[2] == r;
}

static void *graphics_worker(void *opaque)
{
    (void)opaque;
#ifdef __linux__
    pixels = mmap(NULL, WIDTH * HEIGHT * 4, PROT_READ | PROT_WRITE,
                  MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    require(pixels != MAP_FAILED, "allocate protected test pixels");
#endif
    setvbuf(stdout, NULL, _IONBF, 0);
    setenv("DGLES2_FRONTEND", "offscreen", 1);
#ifdef __linux__
    setenv("DGLES2_BACKEND", "osmesa", 1);
#else
    setenv("DGLES2_BACKEND", "cocoa", 1);
#endif
    setenv("DGLES2_NO_ALPHA", "1", 1);
    setenv("DGLES2_COCOA_FBO", "1", 0);
    EGLDisplay display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    EGLint major = 0, minor = 0, count = 0;
    EGLConfig config = NULL;
    const EGLint attributes[] = {
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8,
        EGL_BUFFER_SIZE, 32,
#ifdef DGLES_TEST_ES1
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES_BIT,
#else
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
#endif
        EGL_DEPTH_SIZE, 24, EGL_STENCIL_SIZE, 8,
        EGL_NONE
    };
    const EGLint context_attributes[] = {
        EGL_CONTEXT_CLIENT_VERSION,
#ifdef DGLES_TEST_ES1
        1,
#else
        2,
#endif
        EGL_NONE
    };
    DEGLDrawable drawable = {
        .width = WIDTH, .height = HEIGHT, .depth = 24, .bpp = 4,
        .pixels = pixels, .userdata = &swap_count, .swap = swapped
    };
    require(display != EGL_NO_DISPLAY, "get display");
    require(eglInitialize(display, &major, &minor), "initialize display");
    require(eglBindAPI(EGL_OPENGL_ES_API), "bind GLES API");
    require(eglChooseConfig(display, attributes, &config, 1, &count) && count,
            "choose RGBA8888 GLES config");
    EGLSurface surface = eglCreateOffscreenSurfaceDGLES(display, config,
                                                        &drawable);
    require(surface != EGL_NO_SURFACE, "create Nokia offscreen surface");
    EGLContext context = eglCreateContext(display, config, EGL_NO_CONTEXT,
                                         context_attributes);
    require(context != EGL_NO_CONTEXT, "create GLES context");
    require(eglMakeCurrent(display, surface, surface, context), "make current");
    printf("EGL %d.%d\nGL_VENDOR=%s\nGL_RENDERER=%s\nGL_VERSION=%s\n",
           major, minor, glGetString(GL_VENDOR), glGetString(GL_RENDERER),
           glGetString(GL_VERSION));
    glViewport(0, 0, WIDTH, HEIGHT);

    for (unsigned frame = 0; frame < 2; ++frame) {
        unsigned r = frame ? 0 : 255, gb = frame ? 255 : 0;
        memset(pixels, 0xa5, (WIDTH * HEIGHT * 4));
        glClearColor(r / 255.f, gb / 255.f, gb / 255.f, 1.f);
        glClear(GL_COLOR_BUFFER_BIT);
        require(eglSwapBuffers(display, surface), "swap clear frame");
        require(glGetError() == GL_NO_ERROR, "clear/swap GL error");
        for (size_t i = 0; i < WIDTH * HEIGHT; ++i) {
            if (!rgb_matches(i, r, gb, gb)) {
                fprintf(stderr, "frame %u pixel %zu: BGRA=%u,%u,%u,%u\n",
                        frame + 1, i, pixels[i * 4], pixels[i * 4 + 1],
                        pixels[i * 4 + 2], pixels[i * 4 + 3]);
                require(0, "full-frame RGB comparison");
            }
        }
        printf("CLEAR_FRAME_%u_OK pixels=%u\n", frame + 1, WIDTH * HEIGHT);
    }

    const GLfloat vertices[] = { -.8f, -.8f, .8f, -.8f, 0.f, .8f };
#ifdef DGLES_TEST_ES1
    glMatrixMode(GL_PROJECTION);
    glLoadIdentity();
    glMatrixMode(GL_MODELVIEW);
    glLoadIdentity();
    glVertexPointer(2, GL_FLOAT, 0, vertices);
    glEnableClientState(GL_VERTEX_ARRAY);
    glColor4f(0.f, 1.f, 0.f, 1.f);
#else
    GLuint vertex = shader(GL_VERTEX_SHADER,
        "attribute vec2 position;\n"
        "void main() { gl_Position = vec4(position, 0.0, 1.0); }\n");
    GLuint fragment = shader(GL_FRAGMENT_SHADER,
        "precision mediump float;\n"
        "void main() { gl_FragColor = vec4(0.0, 1.0, 0.0, 1.0); }\n");
    GLuint program = glCreateProgram();
    glAttachShader(program, vertex);
    glAttachShader(program, fragment);
    glBindAttribLocation(program, 0, "position");
    glLinkProgram(program);
    GLint linked = 0;
    glGetProgramiv(program, GL_LINK_STATUS, &linked);
    require(linked, "link GLES2 program");
    glUseProgram(program);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, vertices);
    glEnableVertexAttribArray(0);
#endif
    glClearColor(0.f, 0.f, 1.f, 1.f);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    require(eglSwapBuffers(display, surface), "swap shader triangle");
    require(glGetError() == GL_NO_ERROR, "draw/swap GL error");
    require(rgb_matches((HEIGHT / 2) * WIDTH + WIDTH / 2, 0, 255, 0),
            "green shader triangle center");
    require(rgb_matches(0, 0, 0, 255), "blue triangle background");
    printf("TRIANGLE_OK center=green corner=blue\n");
#ifndef DGLES_TEST_ES1
    GLint binding = -1;
    GLfloat binding_f = -1.f;
    GLboolean binding_b = GL_TRUE;
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &binding);
    glGetFloatv(GL_FRAMEBUFFER_BINDING, &binding_f);
    glGetBooleanv(GL_FRAMEBUFFER_BINDING, &binding_b);
    require(binding == 0 && binding_f == 0 && binding_b == GL_FALSE,
            "hide internal framebuffer binding");
    GLuint user_fbo, user_color;
    glGenFramebuffers(1, &user_fbo);
    glGenRenderbuffers(1, &user_color);
    glBindRenderbuffer(GL_RENDERBUFFER, user_color);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA4, 16, 16);
    glBindFramebuffer(GL_FRAMEBUFFER, user_fbo);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                              GL_RENDERBUFFER, user_color);
    require(glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE,
            "create application-owned framebuffer");
    glClearColor(1.f, 0.f, 1.f, 1.f);
    glClear(GL_COLOR_BUFFER_BIT);
    require(eglSwapBuffers(display, surface), "swap with user FBO bound");
    require(rgb_matches((HEIGHT / 2) * WIDTH + WIDTH / 2, 0, 255, 0) &&
            rgb_matches(0, 0, 0, 255), "swap reads EGL surface, not user FBO");
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &binding);
    require(binding == (GLint)user_fbo, "swap preserves user FBO binding");
    require(eglMakeCurrent(display, surface, surface, context),
            "rebind existing context with user FBO bound");
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &binding);
    require(binding == (GLint)user_fbo, "make current preserves user FBO binding");
    unsigned char rgba[4] = {0};
    glReadPixels(0, 0, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    require(rgba[0] == 255 && rgba[1] == 0 && rgba[2] == 255,
            "user FBO readback remains magenta");
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    require(glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE,
            "bind zero restores offscreen framebuffer");
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                              GL_RENDERBUFFER, user_color);
    require(glGetError() == GL_INVALID_OPERATION,
            "cannot replace logical default framebuffer attachment");
    glBindFramebuffer(GL_FRAMEBUFFER, user_fbo);
    glDeleteFramebuffers(1, &user_fbo);
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &binding);
    require(binding == 0 &&
            glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE,
            "deleting bound user FBO restores logical default");
    glDeleteRenderbuffers(1, &user_color);
    puts("USER_FBO_SWITCH_OK");
    glDisableVertexAttribArray(0);
    glDeleteProgram(program);
    glDeleteShader(vertex);
    glDeleteShader(fragment);
#else
    glDisableClientState(GL_VERTEX_ARRAY);
#endif

    glClearColor(0.f, 0.f, 1.f, 1.f);
    glClear(GL_COLOR_BUFFER_BIT);
    glEnable(GL_SCISSOR_TEST);
    glScissor(0, HEIGHT / 2, WIDTH, HEIGHT / 2);
    glClearColor(1.f, 0.f, 0.f, 1.f);
    glClear(GL_COLOR_BUFFER_BIT);
    glDisable(GL_SCISSOR_TEST);
    glPixelStorei(GL_PACK_ALIGNMENT, 8);
    require(eglSwapBuffers(display, surface), "swap asymmetric scissor frame");
    GLint pack_alignment = 0;
    glGetIntegerv(GL_PACK_ALIGNMENT, &pack_alignment);
    require(pack_alignment == 8, "swap preserves pixel pack alignment");
    for (size_t i = 0; i < WIDTH * HEIGHT; ++i) {
        unsigned top = i / WIDTH < HEIGHT / 2;
        require(rgb_matches(i, top ? 255 : 0, 0, top ? 0 : 255),
                "top-down BGRA orientation");
    }
    puts("ORIENTATION_AND_PACK_STATE_OK pixels=3072");
    glEnable(0xffff);
    require(eglSwapBuffers(display, surface), "swap with pending client error");
    require(glGetError() == GL_INVALID_ENUM, "swap preserves pending GL error");
    require(glGetError() == GL_NO_ERROR, "client error is consumed once");
    puts("CLIENT_GL_ERROR_PRESERVED_OK");

#ifdef __linux__
    for (unsigned mask = 1; mask < 7; ++mask) {
        require(!eglMakeCurrent(display, mask & 2 ? surface : EGL_NO_SURFACE,
                                mask & 4 ? surface : EGL_NO_SURFACE,
                                mask & 1 ? context : EGL_NO_CONTEXT) &&
                eglGetError() == EGL_BAD_MATCH, "reject partial-null binding");
        require(eglGetCurrentContext() == context &&
                eglGetCurrentSurface(EGL_DRAW) == surface,
                "partial-null rejection preserves current state");
    }
    puts("PARTIAL_NULL_BINDINGS_REJECTED_OK");

#endif

    /* Validate the explicit limits instead of silently reusing the wrong FBO. */
    EGLContext other = eglCreateContext(display, config, context,
                                        context_attributes);
    require(other != EGL_NO_CONTEXT, "create second context");
    require(!eglMakeCurrent(display, surface, surface, other) &&
            eglGetError() == EGL_BAD_ACCESS, "reject cross-context surface reuse");
    require(eglGetCurrentContext() == context, "failed bind preserves context");
    require(eglSwapBuffers(display, surface), "original context still renders");
    require(eglDestroyContext(display, other), "destroy second context");
    drawable.width = 4097;
    require(!eglMakeCurrent(display, surface, surface, context) &&
            eglGetError() == EGL_BAD_MATCH, "reject excessive surface dimensions");
#ifdef __linux__
    /* Repeat invalid swap attempts: neither may commit an invalid size. */
    unsigned before_rejected_swaps = swap_count;
    for (unsigned attempt = 0; attempt < 2; ++attempt) {
        require(!eglSwapBuffers(display, surface) && eglGetError() == EGL_BAD_MATCH,
                "repeated invalid resize remains rejected");
        require(eglGetCurrentContext() == context, "invalid resize preserves context");
        require(swap_count == before_rejected_swaps, "rejected resize has no callback");
    }
#endif
    drawable.width = WIDTH;
    require(eglMakeCurrent(display, surface, surface, context), "restore valid size");
#ifdef __linux__
    unsigned char foreign_pixels[WIDTH * HEIGHT * 4];
    DEGLDrawable foreign_drawable = drawable;
    foreign_drawable.pixels = foreign_pixels;
    EGLSurface foreign_surface = eglCreateOffscreenSurfaceDGLES(display, config, &foreign_drawable);
    require(foreign_surface != EGL_NO_SURFACE, "create unbound foreign surface");
    foreign_drawable.width = WIDTH - 1;
    require(!eglSwapBuffers(display, foreign_surface) && eglGetError() == EGL_BAD_SURFACE,
            "foreign resize cannot acquire the current context");
    require(eglGetCurrentSurface(EGL_DRAW) == surface, "foreign swap preserves draw surface");
    require(swap_count == before_rejected_swaps, "foreign swap has no callback");
    require(eglDestroySurface(display, foreign_surface), "destroy never-bound surface");
    puts("REPEATED_INVALID_RESIZE_AND_FOREIGN_SWAP_REJECTED_OK");
#endif
    puts("UNSUPPORTED_SURFACE_GUARDS_OK");

    /* Same-context resize creates a fresh attachment; redraw before checking. */
    drawable.width = WIDTH - 1;
    drawable.height = HEIGHT - 1;
    require(eglMakeCurrent(display, surface, surface, context), "resize surface");
    glClearColor(1.f, 1.f, 0.f, 1.f);
    glClear(GL_COLOR_BUFFER_BIT);
    memset(pixels, 0xa5, (WIDTH * HEIGHT * 4));
    require(eglSwapBuffers(display, surface), "swap resized surface");
    for (size_t i = 0; i < (WIDTH - 1) * (HEIGHT - 1); ++i)
        require(rgb_matches(i, 255, 255, 0), "resized RGB comparison");
    for (size_t i = (WIDTH - 1) * (HEIGHT - 1) * 4; i < (WIDTH * HEIGHT * 4); ++i)
        require(pixels[i] == 0xa5, "resize readback buffer boundary");
    require(glGetError() == GL_NO_ERROR, "no GL error after resize");
    printf("RESIZE_OK pixels=%u\n", (WIDTH - 1) * (HEIGHT - 1));
#ifdef DGLES_TEST_ES1
    require(swap_count == 7, "all GLES1 swaps invoke callback exactly once");
#else
    require(swap_count == 8, "all GLES2 swaps invoke callback exactly once");
#endif
#ifdef __linux__
    if (cleanup_mode == 2) {
        pthread_mutex_lock(&exit_lock);
        worker_ready = 1;
        pthread_cond_broadcast(&exit_cond);
        while (!release_worker) pthread_cond_wait(&exit_cond, &exit_lock);
        pthread_mutex_unlock(&exit_lock);
    }
#endif
    require(eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE,
                           EGL_NO_CONTEXT), "release current context");
#ifdef __linux__
    void *native_library = dlopen("libOSMesa.so.8", RTLD_NOW | RTLD_LOCAL);
    require(native_library != NULL, "open pinned OSMesa runtime");
    void *(*native_current)(void) = (void *(*)(void))dlsym(native_library, "OSMesaGetCurrentContext");
    require(native_current && native_current() == NULL, "native OSMesa context is unbound");
    dlclose(native_library);
    puts("NATIVE_CONTEXT_UNBOUND_OK");
    if (cleanup_mode) {
        require(eglDestroySurface(display, surface), "destroy surface before context");
        require(mprotect(pixels, WIDTH * HEIGHT * 4, PROT_NONE) == 0,
                "retire pixel target");
        require(eglDestroyContext(display, context), "destroy context after retired surface");
        puts("SURFACE_BEFORE_CONTEXT_PROTECTED_PIXEL_LIFETIME_OK");
    } else {
#endif
        require(eglDestroyContext(display, context), "destroy context");
        require(eglDestroySurface(display, surface), "destroy surface");
#ifdef __linux__
    }
    require(munmap(pixels, WIDTH * HEIGHT * 4) == 0, "release test pixels");
#endif
    require(eglTerminate(display), "terminate display");
#ifdef DGLES_TEST_ES1
    puts("HARMATTAN_DGLES1_HOST_SMOKE_OK");
#else
    puts("HARMATTAN_DGLES2_HOST_SMOKE_OK");
#endif
    return NULL;
}

int main(int argc, char **argv)
{
#ifdef __linux__
    if (argc == 2 && !strcmp(argv[1], "--surface-first")) cleanup_mode = 1;
    else if (argc == 2 && !strcmp(argv[1], "--early-cleanup")) cleanup_mode = 2;
    else if (argc != 1) return 2;
    /* Register before Mesa, as QEMU's legacy atexit notifier is. */
    if (atexit(process_exit_marker) != 0) return 1;
#else
    (void)argv;
    if (argc != 1) return 2;
#endif
    /* Nokia QEMU dispatches each GLES client on a host worker thread. */
    pthread_t worker;
    if (pthread_create(&worker, NULL, graphics_worker, NULL) != 0) return 1;
#ifdef __linux__
    if (cleanup_mode == 2) {
        pthread_mutex_lock(&exit_lock);
        while (!worker_ready) pthread_cond_wait(&exit_cond, &exit_lock);
        pthread_mutex_unlock(&exit_lock);
        finish_worker(worker);
        finish_worker(worker);
        puts("EARLY_CLEANUP_IDEMPOTENT_OK");
    } else {
        if (pthread_join(worker, NULL) != 0) return 1;
        cleanup_done = 1;
        puts("GLES_WORKER_JOIN_OK");
    }
#else
    if (pthread_join(worker, NULL) != 0) return 1;
    puts("GLES_WORKER_JOIN_OK");
#endif
    return 0;
}
