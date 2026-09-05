/* Synthetic public-X11 call flow, not guest pixel/GPU acceptance. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned long Window;
typedef struct { short x, y; unsigned short width, height; } Rectangle;
extern void _ZN24MCompositeManagerPrivate17showOverlayWindowEb(void *, _Bool);
extern void XShapeCombineRectangles(void *, Window, int, int, int, Rectangle *, int, int, int);
extern unsigned eglSwapBuffers(void *, void *);
static int mode, manager, other, display, gc, surface, swaps, original_shows, copies, frees, allocations;
static int visible, input_empty[2], order, phase, presented, released, retained, swap_ok = 1;
static unsigned screen_value = 42, pixmap_value, next_frame = 99;
static unsigned long backgrounds[2];
static unsigned root_depth = 24;
static int index_of(Window w) { assert(w == 11 || w == 12); return (int)w - 11; }
static void shape(void *d, Window w, int kind, int x, int y, Rectangle *r, int n, int op, int sort)
{
    assert(d == &display && !x && !y && n == 1 && !op && !sort);
    int i = index_of(w);
    if (kind == 2) { assert(!r->width && !r->height); input_empty[i] = 1; }
    else {
        assert(kind == 0);
        if (phase == 1 && r->width) assert(input_empty[i]);
        visible = r->width != 0;
    }
}
static void show(void *self, _Bool on)
{
    assert(self == &manager); ++original_shows;
    if (phase == 1 && on) {
        /* Original redirects after prefill. It must see a visible overlay,
         * both backgrounds holding this cycle's real screen value. */
        assert(visible && backgrounds[0] == 100 && backgrounds[1] == 100);
        assert(screen_value == pixmap_value && presented == allocations);
    }
    Rectangle r = {0, 0, on ? 864 : 0, on ? 480 : 0};
    if (mode == 4) r.width = 800;
    XShapeCombineRectangles(&display, 11, 0, 0, 0, &r, 1, 0, 0);
    if (mode != 5) XShapeCombineRectangles(&display, 12, 0, 0, 0, &r, 1, 0, 0);
}
static Window root(void *d) { assert(d == &display); return 10; }
static int geometry(void *d, Window w, Window *r, int *x, int *y, unsigned *width, unsigned *height, unsigned *border, unsigned *depth)
{
    assert(d == &display && w >= 10 && w <= 12);
    *r = 10; *x = *y = 0; *width = 864; *height = 480; *border = 0; *depth = root_depth;
    return 1;
}
static Window create_pixmap(void *d, Window w, unsigned width, unsigned height, unsigned depth)
{
    assert(d == &display && w == 10 && width == 864 && height == 480 && depth == 24);
    assert(!retained); retained = 1; ++allocations; return 100;
}
static void *create_gc(void *d, Window w, unsigned long mask, void *values)
{
    assert(d == &display && w == 10 && !mask && !values); order = 0; return &gc;
}
static int subwindows(void *d, void *g, int value) { assert(d == &display && g == &gc && value == 1 && order++ == 0); return 1; }
static int exposures(void *d, void *g, int value) { assert(d == &display && g == &gc && value == 0 && order++ == 1); return 1; }
static int copy(void *d, Window src, Window dst, void *g, int sx, int sy, unsigned w, unsigned h, int dx, int dy)
{
    assert(d == &display && src == 10 && dst == 100 && g == &gc && !sx && !sy && !dx && !dy);
    assert(w == 864 && h == 480 && order++ == 2);
    pixmap_value = screen_value; ++copies; return 1;
}
static int free_gc(void *d, void *g) { assert(d == &display && g == &gc && order++ == 3); return 1; }
static int background(void *d, Window w, Window pixmap)
{
    assert(d == &display && (pixmap == 100 || !pixmap)); backgrounds[index_of(w)] = pixmap; return 1;
}
static int clear(void *d, Window w)
{
    assert(d == &display && visible && backgrounds[index_of(w)] == 100 && order == 4);
    screen_value = pixmap_value; return 1;
}
static int free_pixmap(void *d, Window pixmap)
{
    assert(d == &display && pixmap == 100 && retained && !backgrounds[0] && !backgrounds[1]);
    retained = 0; ++frees; return 1;
}
static unsigned swap(void *d, void *s)
{
    assert(d == &display && s == &surface); ++swaps;
    if (swap_ok) screen_value = next_frame;
    return (unsigned)swap_ok;
}
void *dlsym(void *handle, const char *name)
{
    assert(handle == (void *)-1);
    if (mode == 3 && !strcmp(name, "XCopyArea")) return 0;
    if (mode == 6 && !strcmp(name, "eglSwapBuffers")) return 0;
#define SYM(n, f) if (!strcmp(name, n)) return f
    SYM("_ZN24MCompositeManagerPrivate17showOverlayWindowEb", show);
    SYM("XShapeCombineRectangles", shape); SYM("XDefaultRootWindow", root); SYM("XGetGeometry", geometry);
    SYM("XCreatePixmap", create_pixmap); SYM("XCreateGC", create_gc); SYM("XSetSubwindowMode", subwindows);
    SYM("XSetGraphicsExposures", exposures); SYM("XCopyArea", copy); SYM("XFreeGC", free_gc);
    SYM("XSetWindowBackgroundPixmap", background); SYM("XClearWindow", clear); SYM("XFreePixmap", free_pixmap);
    SYM("eglSwapBuffers", swap);
#undef SYM
    assert(0); return 0;
}
int write(int fd, const void *data, unsigned length)
{
    assert(data && length && (fd == 1 || fd == 2));
    char expected[80];
    if (fd == 2) { assert(strstr(data, "N00_COMPOSITOR_HANDOFF_ERROR")); return (int)length; }
    if (strstr(data, "PRESENTED")) {
        ++presented; snprintf(expected, sizeof(expected), "N00_COMPOSITOR_HANDOFF_PRESENTED id=%d\n", presented);
    } else {
        ++released; snprintf(expected, sizeof(expected), "N00_COMPOSITOR_HANDOFF_RELEASED id=%d\n", released);
    }
    assert(!strcmp(data, expected)); return (int)length;
}
void _exit(int code) { exit(code); }
int main(int argc, char **argv)
{
    assert(argc == 2); mode = atoi(argv[1]);
    _ZN24MCompositeManagerPrivate17showOverlayWindowEb(&manager, 0);
    _ZN24MCompositeManagerPrivate17showOverlayWindowEb(&manager, 1);
    assert(!copies); /* Nothing usable before original windows/fullscreen learned. */
    eglSwapBuffers(&display, &surface);
    _ZN24MCompositeManagerPrivate17showOverlayWindowEb(&manager, 0);
    phase = 1;
    if (mode == 2) root_depth = 32;
    if (mode == 7) _ZN24MCompositeManagerPrivate17showOverlayWindowEb(&other, 1);
    if (mode == 8) {
        Rectangle r = {0, 0, 0, 0};
        /* Outside original show: simply delegate, do not replace stored IDs. */
        XShapeCombineRectangles(&display, 11, 2, 0, 0, &r, 1, 0, 0);
    }
    for (int i = 0; i < 3; ++i) {
        screen_value = i == 0 ? 0 : (unsigned)i + 50; /* Also preserve real black source. */
        _ZN24MCompositeManagerPrivate17showOverlayWindowEb(&manager, 1);
        assert(copies == i + 1 && retained && screen_value == pixmap_value);
        if (mode == 1) { /* Failure holds; retry submits even a black frame. */
            swap_ok = 0; assert(!eglSwapBuffers(&display, &surface)); assert(retained);
        }
        next_frame = 0;
        if (i != 2) {
            swap_ok = 1; assert(eglSwapBuffers(&display, &surface));
            assert(!retained && screen_value == 0); /* Never filter black. */
        }
        _ZN24MCompositeManagerPrivate17showOverlayWindowEb(&manager, 0);
        assert(!retained && frees == i + 1 && released == i + 1);
    }
    assert(allocations == frees && allocations == 3 && copies == 3 && original_shows == 9);
    return 0;
}
