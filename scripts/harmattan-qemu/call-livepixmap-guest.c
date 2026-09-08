/* SPDX-License-Identifier: GPL-2.0-or-later
 * Scoped PR1.3 call-ui/sysuid image sharing via the original X pixmap.
 * Contract: Nokia Qt 4.7.4 qmeegolivepixmap.cpp, qpixmap.cpp, qimage.h,
 * qflags.h and Xlib XImage. The launcher pins all participating binaries.
 * Producer: original QPainter writes ARGB32, then XPutImage publishes it.
 * Consumer: original QMeeGoLivePixmap constructor owns a raster QPixmapData.
 * No drawing/layout/animation replacement and no advertised EGL extension.
 * Only the call banner uses this path. Non-null fences are unsupported.
 */
_Static_assert(sizeof(void *) == 4, "Pinned Qt ARM32 ABI required");
extern void *dlsym(void *, const char *);
extern void *calloc(unsigned, unsigned);
extern void free(void *);
extern int printf(const char *, ...);
extern int fflush(void *);
extern void exit(int) __attribute__((noreturn));
extern void *XOpenDisplay(const char *);
extern int XGetGeometry(void *, unsigned, unsigned *, int *, int *, unsigned *, unsigned *, unsigned *,
                        unsigned *);
extern int XDefaultScreen(void *);
extern void *XDefaultVisual(void *, int);
extern void *XCreateGC(void *, unsigned, unsigned, void *);
extern int XFreeGC(void *, void *);
extern void *XCreateImage(void *, void *, unsigned, int, int, char *, unsigned, unsigned, int, int);
extern int XPutImage(void *, unsigned, void *, void *, int, int, int, int, unsigned, unsigned);
extern int XDestroyImage(void *);
extern int XSync(void *, int);
typedef struct {
    int width, height, xoffset, format;
    char *data;
} XImagePrefix;
extern int readlink(const char *, char *, unsigned);
extern int strcmp(const char *, const char *);
extern const char *getenv(const char *);
static void fail(int code, const char *why) __attribute__((noreturn));
static void fail(int code, const char *why) {
    printf("LIVE_FATAL %s\n", why);
    fflush(0);
    exit(code);
}
static void check_process(const char *expected) {
    char path[80];
    const char *enabled = getenv("N00_CALL_LIVE_PIXMAP");
    int n = readlink("/proc/self/exe", path, sizeof(path) - 1);
    if (n < 0 || n >= (int)sizeof(path) - 1 || !enabled || strcmp(enabled, "on"))
        fail(89, "process scope");
    path[n] = 0;
    if (strcmp(path, expected))
        fail(89, "process scope");
}
/* Qt ARM32 QImage/QPixmap/QMeeGoLivePixmap fit in this aligned reserved
 * storage; constructors, accessors and destructors exclusively own layout. */
static void *display, *image, *owner;
static unsigned width, height, depth, pixmap;
static void *sym(const char *n) {
    void *p = dlsym((void *)-1, n);
    if (!p) {
        printf("LIVE_FATAL %s\n", n);
        fflush(0);
        fail(90, "allocation or symbol");
    }
    return p;
}
void *live_lock(void *self, void *fence) __asm__("_ZN16QMeeGoLivePixmap4lockEP15QMeeGoFenceSync");
void *live_lock(void *self, void *fence) {
    check_process("/usr/bin/call-ui");
    if (image || fence)
        fail(91, "nested lock or unsupported fence");
    if (!display)
        display = XOpenDisplay(":9");
    unsigned root, border;
    int x, y;
    pixmap = ((unsigned (*)(void *))sym("_ZN16QMeeGoLivePixmap6handleEv"))(self);
    if (!display || !XGetGeometry(display, pixmap, &root, &x, &y, &width, &height, &border, &depth) ||
        depth != 32 || !width || width > 864 || !height || height > 864)
        fail(92, "producer geometry");
    image = calloc(1, 128);
    if (!image)
        fail(90, "allocation or symbol");
    owner = self;
    ((void (*)(void *, int, int, int))sym("_ZN6QImageC1EiiNS_6FormatE"))(image, width, height, 6);
    ((void (*)(void *, unsigned))sym("_ZN6QImage4fillEj"))(image, 0);
    printf("LIVE_LOCK %u %u %u\n", pixmap, width, height);
    fflush(0);
    return image;
}
void live_release(void *self, void *img) __asm__("_ZN16QMeeGoLivePixmap7releaseEP6QImage");
void live_release(void *self, void *img) {
    check_process("/usr/bin/call-ui");
    if (self != owner || img != image || !image)
        fail(93, "release ownership");
    char *bits = ((char *(*)(void *))sym("_ZN6QImage4bitsEv"))(image);
    int stride = ((int (*)(void *))sym("_ZNK6QImage12bytesPerLineEv"))(image);
    if (!bits || stride < (int)width * 4)
        fail(94, "producer image allocation");
    void *xi = XCreateImage(display, XDefaultVisual(display, XDefaultScreen(display)), depth, 2, 0, bits,
                            width, height, 32, stride);
    void *gc = XCreateGC(display, pixmap, 0, 0);
    if (!xi || !gc)
        fail(94, "X image publication");
    XPutImage(display, pixmap, gc, xi, 0, 0, 0, 0, width, height);
    XSync(display, 0);
    ((XImagePrefix *)xi)->data = 0;
    XDestroyImage(xi);
    XFreeGC(display, gc);
    ((void (*)(void *))sym("_ZN6QImageD1Ev"))(image);
    free(image);
    image = owner = 0;
    printf("LIVE_RELEASE %u\n", pixmap);
    fflush(0);
}
extern void *XGetImage(void *, unsigned, int, int, unsigned, unsigned, unsigned, int);
extern void *memcpy(void *, const void *, unsigned);
typedef struct {
    int width, height, xoffset, format;
    char *data;
    int byte_order, bitmap_unit, bitmap_bit_order, bitmap_pad, depth, bytes_per_line, bits_per_pixel;
} XReadImage;
void *live_import(unsigned handle) __asm__("_ZN16QMeeGoLivePixmap10fromHandleEm");
void *live_import(unsigned handle) {
    check_process("/usr/bin/sysuid");
    if (!display)
        display = XOpenDisplay(":9");
    unsigned root, border, w, h, dep;
    int x, y;
    if (!display || !XGetGeometry(display, handle, &root, &x, &y, &w, &h, &border, &dep) || dep != 32 || !w ||
        !h || w > 864 || h > 864)
        fail(95, "consumer geometry");
    XReadImage *xi = XGetImage(display, handle, 0, 0, w, h, ~0u, 2);
    if (!xi || !xi->data || xi->bits_per_pixel != 32 || xi->byte_order != 0 ||
        xi->bytes_per_line < (int)w * 4)
        fail(96, "consumer pixel format");
    void *im = calloc(1, 128);
    void *pm = calloc(1, 128);
    if (!im || !pm)
        fail(90, "allocation or symbol");
    ((void (*)(void *, int, int, int))sym("_ZN6QImageC1EiiNS_6FormatE"))(im, w, h, 6);
    char *bits = ((char *(*)(void *))sym("_ZN6QImage4bitsEv"))(im);
    int stride = ((int (*)(void *))sym("_ZNK6QImage12bytesPerLineEv"))(im);
    if (!bits || stride < (int)w * 4)
        fail(96, "consumer image allocation");
    for (unsigned row = 0; row < h; row++)
        memcpy(bits + row * stride, xi->data + row * xi->bytes_per_line, w * 4);
    XDestroyImage(xi);
    // Qt 4 QFlags has a non-trivial copy ctor: ARM passes its address.
    int flags = 0;
    ((void (*)(void *, void *, int *))sym(
        "_ZN7QPixmap9fromImageERK6QImage6QFlagsIN2Qt19ImageConversionFlagEE"))(pm, im, &flags);
    void *data = ((void *(*)(void *))sym("_ZNK7QPixmap10pixmapDataEv"))(pm);
    void *live = calloc(1, 128);
    if (!live || !data)
        fail(90, "allocation or symbol");
    ((void (*)(void *, void *))sym("_ZN16QMeeGoLivePixmapC1EP11QPixmapData"))(live, data);
    ((void (*)(void *))sym("_ZN7QPixmapD1Ev"))(pm);
    free(pm);
    ((void (*)(void *))sym("_ZN6QImageD1Ev"))(im);
    free(im);
    printf("LIVE_IMPORT %u %u %u\n", handle, w, h);
    fflush(0);
    return live;
}
