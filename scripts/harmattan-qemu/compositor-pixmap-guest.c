/* SPDX-License-Identifier: GPL-2.0-or-later
 * Pinned PR1.3 MTextureFromPixmap software readback. XComposite may return a
 * pixmap XID that the server cannot name during a redirect/resize handoff.
 * Qt 4.7's unchecked geometry then becomes an arbitrary XGetImage size and
 * throws bad_alloc. Keep the original last texture until a valid backing is
 * available; every valid pixmap still uses the original conversion/upload.
 * Public MTextureFromPixmap prefix from mtexturefrompixmap.h; ARM32 binary
 * 49985bb59bf13ae22d20075feb11818a, update() at 0x4c9f2158 reads drawable at
 * self+4 (ldr r1,[r5,#4] at 0x4c9f218c). No Qt private object layout.
 */
extern void *dlsym(void *, const char *);
extern int snprintf(char *, __SIZE_TYPE__, const char *, ...);
extern int write(int, const void *, unsigned);
extern void _exit(int);
typedef struct { void *vtable; unsigned long drawable; } TexturePrefix;
typedef void (*Update)(void *);
typedef void *(*Display)(void);
typedef int (*Geometry)(void *, unsigned long, unsigned long *, int *, int *, unsigned *, unsigned *, unsigned *, unsigned *);

void _ZN18MTextureFromPixmap6updateEv(TexturePrefix *self)
{
    static Update original;
    static Display display;
    static Geometry geometry;
    if (!original) {
        original = (Update)dlsym((void *)-1, "_ZN18MTextureFromPixmap6updateEv");
        display = (Display)dlsym((void *)-1, "_ZN8QX11Info7displayEv");
        geometry = (Geometry)dlsym((void *)-1, "XGetGeometry");
    }
    if (!original || !display || !geometry || !self || !self->vtable) {
        const char error[] = "N00_COMPOSITOR_PIXMAP_ERROR unsupported ABI\n";
        write(2, error, sizeof(error) - 1);
        _exit(128);
    }
    unsigned long root = 0;
    int x = 0, y = 0;
    unsigned width = 0, height = 0, border = 0, depth = 0;
    if (!self->drawable || !geometry(display(), self->drawable, &root, &x, &y,
                                    &width, &height, &border, &depth)) {
        char line[100];
        int n = snprintf(line, sizeof(line), "N00_COMPOSITOR_PIXMAP_PENDING drawable=%lx\n", self->drawable);
        write(1, line, (unsigned)n);
        return;
    }
    original(self);
}

/* Inverted textures are exactly the original EGL pixmap path. Software
 * readback owns an ordinary GL image, so there is no EGLImage to release.
 * Preserve it across direct/redirected rendering until update() can replace
 * it: a queued transition can still sample it after unbind(). Cleanup still
 * clears the image in EglTextureManager::closeTexture before pool reuse.
 */
void _ZN18MTextureFromPixmap6unbindEv(TexturePrefix *self)
{
    typedef unsigned char (*Inverted)(void *);
    static Update original;
    static Inverted inverted;
    if (!original) {
        original = (Update)dlsym((void *)-1, "_ZN18MTextureFromPixmap6unbindEv");
        inverted = (Inverted)dlsym((void *)-1, "_ZNK18MTextureFromPixmap15invertedTextureEv");
    }
    if (!original || !inverted || !self || !self->vtable) {
        const char error[] = "N00_COMPOSITOR_PIXMAP_ERROR unsupported unbind ABI\n";
        write(2, error, sizeof(error) - 1);
        _exit(128);
    }
    if (inverted(self))
        original(self);
}
