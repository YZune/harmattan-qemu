/* SPDX-License-Identifier: GPL-2.0-or-later
 * PR1.3 Qt 4.7 qDrawBorderPixmap source bounds, in the scoped call pixmap
 * preload only. The original slidehint is 8x8, but its CSS top border is 10.
 * Qt builds fragments extending two rows beyond the image; its raster path
 * reads unrelated pixels there. Limit each source edge to the source image,
 * retaining target margins, original pixels, tile rules and painter state.
 * Opposite source edges may overlap: Qt already omits non-positive centers.
 * QRect/QMargins value ABI is from the pinned Qt qrect.h/qmargins.h; QRect
 * stores inclusive endpoints. QFlags is passed indirectly on this ARM ABI.
 */
extern void *dlsym(void *, const char *);
extern int write(int, const void *, unsigned);
extern void _exit(int);
typedef struct { int left, top, right, bottom; } Rect;
typedef struct { int left, top, right, bottom; } Margins;
typedef void (*Draw)(void *, const Rect *, const Margins *, const void *,
                     const Rect *, const Margins *, const void *, const void *);

void n00_draw_border(void *, const Rect *, const Margins *, const void *,
                     const Rect *, const Margins *, const void *, const void *)
    __asm__("_Z17qDrawBorderPixmapP8QPainterRK5QRectRK8QMarginsRK7QPixmapS3_S6_RK10QTileRules6QFlagsIN17QDrawBorderPixmap11DrawingHintEE");

void n00_draw_border(void *painter, const Rect *target, const Margins *tm,
                     const void *pixmap, const Rect *source, const Margins *sm,
                     const void *rules, const void *hints)
{
    static Draw original;
    if (!original)
        original = (Draw)dlsym((void *)-1,
            "_Z17qDrawBorderPixmapP8QPainterRK5QRectRK8QMarginsRK7QPixmapS3_S6_RK10QTileRules6QFlagsIN17QDrawBorderPixmap11DrawingHintEE");
    if (!original) {
        const char error[] = "LIVE_FATAL border pixmap ABI\n";
        write(2, error, sizeof(error) - 1);
        _exit(90);
    }
    Margins bounded = *sm;
    long long width = (long long)source->right - source->left + 1;
    long long height = (long long)source->bottom - source->top + 1;
    if (width > 0 && height > 0) {
        if (bounded.left > width) bounded.left = (int)width;
        if (bounded.right > width) bounded.right = (int)width;
        if (bounded.top > height) bounded.top = (int)height;
        if (bounded.bottom > height) bounded.bottom = (int)height;
    }
    original(painter, target, tm, pixmap, source, &bounded, rules, hints);
}
