/* SPDX-License-Identifier: GPL-2.0-or-later
 * Opt-in display handoff for the pinned PR1.3 compositor and 864x480 X screen.
 * mcompositemanager.cpp:showOverlayWindow redirects the live client BEFORE
 * revealing its overlay. The software Xorg path clears the screen meanwhile.
 * Preserve actual root pixels in the compositor-owned windows until the next
 * successful original swap. Never classify/filter frames or change animation
 * timing, client windows, unredirect policy, or host scanout. Single GUI thread.
 * Overlay background None: Xorg compoverlay.c; local window None: original
 * mcompositor/main.cpp WA_NoSystemBackground. No private Qt object offsets.
 */
extern void *dlsym(void *, const char *);
extern int snprintf(char *, __SIZE_TYPE__, const char *, ...);
extern int write(int, const void *, unsigned);
extern void _exit(int);

typedef unsigned long Window;
typedef struct { short x, y; unsigned short width, height; } Rectangle;
typedef void (*Show)(void *, _Bool);
typedef void (*Shape)(void *, Window, int, int, int, Rectangle *, int, int, int);
typedef int (*Background)(void *, Window, unsigned long);
typedef int (*FreePixmap)(void *, unsigned long);
typedef unsigned long (*Root)(void *);
typedef int (*Geometry)(void *, Window, Window *, int *, int *, unsigned *, unsigned *, unsigned *, unsigned *);
typedef unsigned long (*CreatePixmap)(void *, Window, unsigned, unsigned, unsigned);
typedef void *(*CreateGC)(void *, Window, unsigned long, void *);
typedef int (*GCMode)(void *, void *, int);
typedef int (*Copy)(void *, Window, Window, void *, int, int, unsigned, unsigned, int, int);
typedef int (*Clear)(void *, Window);
typedef int (*FreeGC)(void *, void *);
typedef unsigned (*Swap)(void *, void *);

static void *manager, *xdpy;
static Window windows[2], retained;
static Rectangle fullscreen;
static unsigned serial;
static int recording, shape_count, hidden;
static Show show_original;
static Shape shape_original;
static Background background;
static FreePixmap free_pixmap;
static void fail(void)
{
    const char message[] = "N00_COMPOSITOR_HANDOFF_ERROR unsupported ABI or window state\n";
    write(2, message, sizeof(message) - 1);
    _exit(126);
}
static void *resolve(const char *name)
{
    void *p = dlsym((void *)-1, name);
    if (!p) fail();
    return p;
}
static void marker(const char *event)
{
    char line[80];
    int n = snprintf(line, sizeof(line), "N00_COMPOSITOR_HANDOFF_%s id=%u\n", event, serial);
    if (n <= 0 || n >= (int)sizeof(line)) fail();
    write(1, line, (unsigned)n);
}
static void release_retained(void)
{
    if (!retained) return;
    /* None restores both original compositor window backgrounds. X11 keeps
     * the pixmap alive for queued copies; free after the original submission. */
    for (int i = 0; i < 2; ++i) background(xdpy, windows[i], 0);
    free_pixmap(xdpy, retained);
    retained = 0;
    marker("RELEASED");
}
static void prefill(void)
{
    /* The first startup hide/show learns the original windows/full shape.
     * There is no ready desktop to preserve at that point. */
    if (!fullscreen.width) return;
    if (!xdpy || !windows[0] || !windows[1] || retained) fail();
    Root root_fn = (Root)resolve("XDefaultRootWindow");
    Geometry geometry = (Geometry)resolve("XGetGeometry");
    CreatePixmap create_pixmap = (CreatePixmap)resolve("XCreatePixmap");
    CreateGC create_gc = (CreateGC)resolve("XCreateGC");
    GCMode subwindows = (GCMode)resolve("XSetSubwindowMode");
    GCMode exposures = (GCMode)resolve("XSetGraphicsExposures");
    Copy copy = (Copy)resolve("XCopyArea");
    FreeGC free_gc = (FreeGC)resolve("XFreeGC");
    Clear clear = (Clear)resolve("XClearWindow");
    background = (Background)resolve("XSetWindowBackgroundPixmap");
    free_pixmap = (FreePixmap)resolve("XFreePixmap");
    Window root = root_fn(xdpy), rr;
    int x, y; unsigned w, h, border, depth;
    for (int i = -1; i < 2; ++i) {
        if (!geometry(xdpy, i < 0 ? root : windows[i], &rr, &x, &y, &w, &h, &border, &depth)
            || w != 864 || h != 480 || depth != 24 || x || y || border) fail();
    }
    retained = create_pixmap(xdpy, root, 864, 480, 24);
    void *gc = create_gc(xdpy, root, 0, 0);
    if (!retained || !gc) fail();
    subwindows(xdpy, gc, 1); /* IncludeInferiors: actual visible child pixels. */
    exposures(xdpy, gc, 0);
    copy(xdpy, root, retained, gc, 0, 0, 864, 480, 0, 0);
    free_gc(xdpy, gc);
    Rectangle empty = {0, 0, 0, 0};
    for (int i = 0; i < 2; ++i) {
        background(xdpy, windows[i], retained);
        /* Input must stay empty even during the earlier visual handoff. */
        shape_original(xdpy, windows[i], 2, 0, 0, &empty, 1, 0, 0);
        shape_original(xdpy, windows[i], 0, 0, 0, &fullscreen, 1, 0, 0);
        clear(xdpy, windows[i]);
    }
    ++serial;
    marker("PRESENTED");
}

void _ZN24MCompositeManagerPrivate17showOverlayWindowEb(void *self, _Bool show)
{
    if (recording || !self || (manager && self != manager)) fail();
    manager = self;
    if (!show_original) show_original = (Show)resolve("_ZN24MCompositeManagerPrivate17showOverlayWindowEb");
    if (show && hidden) prefill();
    if (!show) release_retained(); /* Also handle hide-before-first-swap. */
    recording = 1;
    shape_count = 0;
    show_original(self, show);
    recording = 0;
    if (shape_count && shape_count != 2) fail();
    hidden = !show;
}

void XShapeCombineRectangles(void *display, Window window, int kind, int x, int y,
                             Rectangle *rectangles, int count, int op, int order)
{
    if (!shape_original) shape_original = (Shape)resolve("XShapeCombineRectangles");
    if (recording && kind == 0) {
        if (shape_count >= 2 || !rectangles || count != 1 || x || y || op || order
            || rectangles[0].x || rectangles[0].y || !window || (xdpy && xdpy != display)) fail();
        if (windows[shape_count] && windows[shape_count] != window) fail();
        xdpy = display;
        windows[shape_count++] = window;
        if (rectangles[0].width || rectangles[0].height) {
            if (rectangles[0].width != 864 || rectangles[0].height != 480) fail();
            fullscreen = rectangles[0];
        }
    }
    shape_original(display, window, kind, x, y, rectangles, count, op, order);
}

unsigned eglSwapBuffers(void *display, void *surface)
{
    static Swap original;
    if (!original) original = (Swap)resolve("eglSwapBuffers");
    unsigned result = original(display, surface);
    /* Accept every successful original frame, including an entirely black
     * one. Failure retains the previous image until retry or overlay hide. */
    if (result) release_retained();
    return result;
}
