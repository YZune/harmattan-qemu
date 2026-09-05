/* Synthetic calls: no generated UI pixels or substitute GL implementation. */
#include <assert.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

typedef struct { void *vtable; unsigned long drawable; } TexturePrefix;
extern void _ZN18MTextureFromPixmap6updateEv(TexturePrefix *);
static TexturePrefix texture = {(void *)1, 99};
static int mode, reads, updates;
static bool available;
static void original(void *self)
{
    assert(self == &texture && available);
    ++updates;
}
static void *display(void) { return (void *)42; }
static int geometry(void *dpy, unsigned long drawable, unsigned long *root,
                    int *x, int *y, unsigned *w, unsigned *h, unsigned *b, unsigned *depth)
{
    assert(dpy == (void *)42 && drawable == 99);
    ++reads;
    /* Failed queries are permitted to leave every output untouched. */
    if (!available) return 0;
    *root = 84; *x = *y = 0; *w = 864; *h = 480; *b = 0; *depth = 24;
    return 1;
}
void *dlsym(void *handle, const char *name)
{
    assert(handle == (void *)-1);
    if (mode == 1) return 0;
    if (!strcmp(name, "_ZN18MTextureFromPixmap6updateEv")) return original;
    if (!strcmp(name, "_ZN8QX11Info7displayEv")) return display;
    if (!strcmp(name, "XGetGeometry")) return geometry;
    abort();
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    mode = atoi(argv[1]);
    if (mode == 2) texture.vtable = 0;
    _ZN18MTextureFromPixmap6updateEv(&texture);
    assert(reads == 1 && updates == 0 && texture.drawable == 99);
    available = true;
    _ZN18MTextureFromPixmap6updateEv(&texture);
    assert(reads == 2 && updates == 1 && texture.drawable == 99);
    texture.drawable = 0;
    _ZN18MTextureFromPixmap6updateEv(&texture);
    assert(reads == 2 && updates == 1 && texture.drawable == 0);
    return 0;
}
