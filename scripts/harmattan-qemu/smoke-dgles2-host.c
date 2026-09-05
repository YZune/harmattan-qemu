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

enum { WIDTH = 64, HEIGHT = 48 };
static unsigned char pixels[WIDTH * HEIGHT * 4];
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
    setvbuf(stdout, NULL, _IONBF, 0);
    setenv("DGLES2_FRONTEND", "offscreen", 1);
    setenv("DGLES2_BACKEND", "cocoa", 1);
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
        memset(pixels, 0xa5, sizeof(pixels));
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
    drawable.width = WIDTH;
    require(eglMakeCurrent(display, surface, surface, context), "restore valid size");
    puts("UNSUPPORTED_SURFACE_GUARDS_OK");

    /* Same-context resize creates a fresh attachment; redraw before checking. */
    drawable.width = WIDTH - 1;
    drawable.height = HEIGHT - 1;
    require(eglMakeCurrent(display, surface, surface, context), "resize surface");
    glClearColor(1.f, 1.f, 0.f, 1.f);
    glClear(GL_COLOR_BUFFER_BIT);
    memset(pixels, 0xa5, sizeof(pixels));
    require(eglSwapBuffers(display, surface), "swap resized surface");
    for (size_t i = 0; i < (WIDTH - 1) * (HEIGHT - 1); ++i)
        require(rgb_matches(i, 255, 255, 0), "resized RGB comparison");
    for (size_t i = (WIDTH - 1) * (HEIGHT - 1) * 4; i < sizeof(pixels); ++i)
        require(pixels[i] == 0xa5, "resize readback buffer boundary");
    require(glGetError() == GL_NO_ERROR, "no GL error after resize");
    printf("RESIZE_OK pixels=%u\n", (WIDTH - 1) * (HEIGHT - 1));
#ifdef DGLES_TEST_ES1
    require(swap_count == 7, "all GLES1 swaps invoke callback exactly once");
#else
    require(swap_count == 8, "all GLES2 swaps invoke callback exactly once");
#endif
    require(eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE,
                           EGL_NO_CONTEXT), "release current context");
    require(eglDestroyContext(display, context), "destroy context");
    require(eglDestroySurface(display, surface), "destroy surface");
    require(eglTerminate(display), "terminate display");
#ifdef DGLES_TEST_ES1
    puts("HARMATTAN_DGLES1_HOST_SMOKE_OK");
#else
    puts("HARMATTAN_DGLES2_HOST_SMOKE_OK");
#endif
    return NULL;
}

int main(void)
{
    /* Nokia QEMU dispatches each GLES client on a host worker thread. */
    pthread_t worker;
    if (pthread_create(&worker, NULL, graphics_worker, NULL) != 0) return 1;
    if (pthread_join(worker, NULL) != 0) return 1;
    puts("GLES_WORKER_JOIN_OK");
    return 0;
}
