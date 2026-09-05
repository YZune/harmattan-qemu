/* Real guest Xlib + original FGLES public API test. No MMIO gateway, no /dev/fb0.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#define MESA_EGL_NO_X11_HEADERS
#include <EGL/egl.h>
#include <GLES2/gl2.h>
#include <stddef.h>
#include <stdint.h>

/* Opaque Xlib handles and the small public ABI subset used by this test. */
typedef struct _XDisplay Display;
typedef struct _XImage XImage;
typedef unsigned long Window;
extern Display *XOpenDisplay(const char *);
extern int XDefaultScreen(Display *);
extern Window XRootWindow(Display *, int);
extern Window XCreateSimpleWindow(Display *, Window, int, int, unsigned, unsigned,
                                  unsigned, unsigned long, unsigned long);
extern int XMapWindow(Display *, Window);
extern int XSync(Display *, int);
extern int XDestroyWindow(Display *, Window);
extern int XCloseDisplay(Display *);
extern XImage *XGetImage(Display *, Window, int, int, unsigned, unsigned, unsigned long,
                         int);
extern unsigned long XGetPixel(XImage *, int, int);
extern int XDestroyImage(XImage *);
extern int printf(const char *, ...);
extern int fflush(void *);
extern int getchar(void);
extern char *getenv(const char *);
extern int open(const char *, int, ...);
extern long read(int, void *, unsigned);
extern long write(int, const void *, unsigned);
extern int close(int);
extern void exit(int) __attribute__((noreturn));
enum { W = 864, H = 480, BYTES = W * H * 4 };
static unsigned char pixels[BYTES + 32];
static int gl_current;

static void require(int ok, const char *message)
{
    if (!ok) {
        printf("\nN00_PUBLIC_FAIL: %s EGL=%04x GL=%04x\n", message, eglGetError(),
               gl_current ? glGetError() : 0);
        fflush(NULL);
        exit(1);
    }
}

static void report_mappings(void)
{
    int fd = open("/proc/self/maps", 0);
    require(fd >= 0, "read loaded library mappings");
    printf("\nN00_PUBLIC_MAPS_BEGIN\n");
    fflush(NULL);
    char buffer[2048];
    long count;
    while ((count = read(fd, buffer, sizeof(buffer))) > 0) {
        require(write(1, buffer, count) == count, "report mappings");
    }
    require(count == 0, "mapping read error");
    close(fd);
    printf("\nN00_PUBLIC_MAPS_END\n");
    fflush(NULL);
}

static GLuint make_shader(GLenum kind, const char **source, const GLint *lengths,
                          unsigned count)
{
    GLuint object = glCreateShader(kind);
    require(object != 0, "create shader");
    glShaderSource(object, count, source, lengths);
    glCompileShader(object);
    GLint status = 0;
    glGetShaderiv(object, GL_COMPILE_STATUS, &status);
    if (!status) {
        char info[1024];
        glGetShaderInfoLog(object, sizeof(info), NULL, info);
        printf("shader log: %s\n", info);
    }
    require(status == 1, "compile shader through original libGLESv2");
    return object;
}

static unsigned rgb(unsigned frame, unsigned x, unsigned y)
{
    if (y >= H / 2) {
        return x < W / 2 ? 0x0000ff : 0xffffff;
    }
    return x < W / 2 ? (frame ? 0xff00ff : 0xff0000) : 0x00ff00;
}

static void verify_pixels(Display *xdpy, Window window, unsigned frame)
{
    for (unsigned i = 0; i < sizeof(pixels); i++) {
        pixels[i] = 0xa5;
    }
    glReadPixels(0, 0, W, H, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
    require(glGetError() == GL_NO_ERROR, "RGBA readback");
    XImage *image = XGetImage(xdpy, window, 0, 0, W, H, ~0UL, 2);
    require(image != NULL, "XGetImage of actual EGL window");
    unsigned mismatches = 0;
    for (unsigned y = 0; y < H; y++) {
        for (unsigned x = 0; x < W; x++) {
            unsigned color = rgb(frame, x, y);
            unsigned index = (y * W + x) * 4;
            unsigned read_color =
                (pixels[index] << 16) | (pixels[index + 1] << 8) | pixels[index + 2];
            if (read_color != color ||
                (XGetPixel(image, x, H - 1 - y) & 0xffffff) != color) {
                mismatches++;
            }
        }
    }
    XDestroyImage(image);
    if (mismatches) {
        printf("mismatched pixels=%u\n", mismatches);
    }
    require(!mismatches, "GPU readback and X11 window pixels");
    for (unsigned i = BYTES; i < sizeof(pixels); i++) {
        require(pixels[i] == 0xa5, "readback buffer guard");
    }
}

#ifdef N00_SHELL_API_PROBE
#include "smoke-gles-shell-api.inc"
#endif

int main(void)
{
    const char *mode = getenv("FGLES2_NOXSHM");
    printf("N00_PUBLIC_START noxshm=%s\n", mode ? mode : "unset");
    fflush(NULL);
    Display *xdpy = XOpenDisplay(":9");
    if (!xdpy) {
        printf("N00_PUBLIC_FAIL: XOpenDisplay\n");
        return 1;
    }
    Window root = XRootWindow(xdpy, XDefaultScreen(xdpy));
    Window window = XCreateSimpleWindow(xdpy, root, 0, 0, W, H, 0, 0, 0);
    XMapWindow(xdpy, window);
    XSync(xdpy, 0);
    EGLDisplay dpy = eglGetDisplay(xdpy);
    /* Do not call GL error queries until a context exists. */
    if (!dpy) {
        printf("N00_PUBLIC_FAIL: eglGetDisplay\n");
        return 1;
    }
    EGLint major = 0, minor = 0;
    if (!eglInitialize(dpy, &major, &minor)) {
        printf("N00_PUBLIC_FAIL: eglInitialize error=%x\n", eglGetError());
        return 1;
    }
    printf("N00_PUBLIC_EGL version=%d.%d vendor=%s\n", major, minor,
           eglQueryString(dpy, EGL_VENDOR));
    fflush(NULL);
    EGLint attrs[] = {EGL_RED_SIZE,
                      8,
                      EGL_GREEN_SIZE,
                      8,
                      EGL_BLUE_SIZE,
                      8,
                      EGL_BUFFER_SIZE,
                      32,
                      EGL_RENDERABLE_TYPE,
                      EGL_OPENGL_ES2_BIT,
                      EGL_DEPTH_SIZE,
                      24,
                      EGL_STENCIL_SIZE,
                      8,
                      EGL_NONE};
    EGLConfig config = NULL;
    EGLint count = 0;
    require(eglBindAPI(EGL_OPENGL_ES_API), "bind API");
    require(eglChooseConfig(dpy, attrs, &config, 1, &count) && count, "choose config");
    EGLint ctx_attrs[] = {EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE};
    EGLContext context = eglCreateContext(dpy, config, EGL_NO_CONTEXT, ctx_attrs);
    require(context != EGL_NO_CONTEXT, "create context");
    EGLSurface surface = eglCreateWindowSurface(dpy, config, window, NULL);
    require(surface != EGL_NO_SURFACE, "create actual X11 EGL window surface");
    require(eglMakeCurrent(dpy, surface, surface, context), "make current");
    gl_current = 1;
    report_mappings();
    printf("N00_PUBLIC_GL renderer=%s version=%s\n", glGetString(GL_RENDERER),
           glGetString(GL_VERSION));
    fflush(NULL);
    EGLint width = 0, height = 0;
    require(eglQuerySurface(dpy, surface, EGL_WIDTH, &width) &&
                eglQuerySurface(dpy, surface, EGL_HEIGHT, &height) && width == W &&
                height == H,
            "public surface query");
#ifdef N00_SHELL_API_PROBE
    verify_shell_api();
#endif
    glViewport(0, 0, W, H);
    const char *vs_source[] = {
        "attribute vec2 pos; attribute vec2 uv; varying vec2 tc;",
        "void main(){tc=uv;gl_Position=vec4(pos,0.,1.);}"};
    /* NULL lengths exercise the original wrapper's strlen/malloc path. */
    GLuint vs = make_shader(GL_VERTEX_SHADER, vs_source, NULL, 2);
    const char *fs_source =
        "precision mediump float; varying vec2 tc; uniform sampler2D tex; void "
        "main(){gl_FragColor=texture2D(tex,tc);}";
    GLint explicit_length = 0;
    while (fs_source[explicit_length]) {
        explicit_length++;
    }
    GLuint fs = make_shader(GL_FRAGMENT_SHADER, &fs_source, &explicit_length, 1);
    GLuint program = glCreateProgram();
    glAttachShader(program, vs);
    glAttachShader(program, fs);
    glBindAttribLocation(program, 0, "pos");
    glBindAttribLocation(program, 1, "uv");
    glLinkProgram(program);
    GLint linked = 0;
    glGetProgramiv(program, GL_LINK_STATUS, &linked);
    require(linked == 1, "link program");
    glUseProgram(program);
    GLint sampler = glGetUniformLocation(program, "tex");
    require(sampler >= 0, "uniform lookup");
    glUniform1i(sampler, 0);
    GLuint texture;
    glGenTextures(1, &texture);
    glBindTexture(GL_TEXTURE_2D, texture);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    const unsigned char rgba[] = {255, 0, 0,   255, 0,   255, 0,   255,
                                  0,   0, 255, 255, 255, 255, 255, 255};
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 2, 2, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    const float vertices[] = {-1, -1, 0, 0, 1, -1, 1, 0, 1, 1, 1, 1, -1, 1, 0, 1};
    const unsigned short indices[] = {0, 1, 2, 0, 2, 3};
    glEnableVertexAttribArray(0);
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, vertices);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, vertices + 2);
    for (unsigned frame = 0; frame < 2; frame++) {
        if (frame) {
            const unsigned char magenta[] = {255, 0, 255, 255};
            glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE,
                            magenta);
        }
        glClearColor(0.25f, 0.5f, 0.75f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        unsigned char clear_pixel[4] = {0};
        glReadPixels(0, 0, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, clear_pixel);
        require(clear_pixel[0] == 64 && clear_pixel[1] == 128 && clear_pixel[2] == 191,
                "public hard-float ClearColor arguments");
        glDrawElements(GL_TRIANGLES, 6, GL_UNSIGNED_SHORT, indices);
        glFinish();
        require(eglSwapBuffers(dpy, surface), "public EGL swap via XImage/XShm");
        XSync(xdpy, 0);
        verify_pixels(xdpy, window, frame);
        printf("\nN00_PUBLIC_FRAME_%u_OK pixels=829440\n", frame);
        fflush(NULL);
        /* Keep the real X window mapped until the host independently captures it. */
        require(getchar() == 'c', "host screenshot acknowledgement");
        require(getchar() == '\n', "host acknowledgement terminator");
    }
    glDisableVertexAttribArray(0);
    glDisableVertexAttribArray(1);
    glDeleteTextures(1, &texture);
    glUseProgram(0);
    glDeleteProgram(program);
    glDeleteShader(vs);
    glDeleteShader(fs);
    require(glGetError() == GL_NO_ERROR, "GL cleanup");
    require(eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT),
            "unbind");
    gl_current = 0;
    /* This legacy wrapper does not reliably return a bool from DestroySurface. */
    eglDestroySurface(dpy, surface);
    require(eglDestroyContext(dpy, context), "destroy context");
    require(eglGetError() == EGL_SUCCESS, "EGL surface/context cleanup status");
    EGLBoolean terminated = eglTerminate(dpy);
    EGLint terminate_error = eglGetError();
    /* Original libEGL first terminates the real handle, then repeats with NULL.
     * Preserve and explicitly validate this defect; never fake EGL_TRUE for it.
     */
    printf("N00_PUBLIC_TERMINATE result=%u error=%04x\n", terminated, terminate_error);
    require(!terminated && terminate_error == EGL_BAD_DISPLAY,
            "known original-library double-terminate behavior");
    XDestroyWindow(xdpy, window);
    XCloseDisplay(xdpy);
    printf("\nN00_PUBLIC_GUEST_OK\n");
    fflush(NULL);
    return 0;
}
