/* Synthetic call-flow tests only: not guest/GPU/image acceptance. */
#include <assert.h>
#include <stdlib.h>
#include <string.h>

extern void _ZN18MTextureFromPixmap4bindEm(void *, unsigned long);
extern void _ZN18MTextureFromPixmap6updateEv(void *);
extern void _ZN24MCompositeManagerPrivate13splashTimeoutEv(void *);
extern void _ZN24MCompositeManagerPrivate13setCurrentAppEP16MCompositeWindowb(void *, void *, _Bool);
static int a, b, c, mode, binds, updates, timeouts, calls, nested, reenter;
static int null_markers, refresh_markers;
static void *seen_manager[16], *seen_window[16];
static _Bool seen_restacked[16];

static void original_update(void *self) { assert(self); ++updates; }
static void original_bind(void *self, unsigned long drawable)
{
    ++binds;
    if (mode == 1 && !drawable && !nested) {
        nested = 1;
        _ZN18MTextureFromPixmap4bindEm(&b, 41);
        _ZN18MTextureFromPixmap6updateEv(&c);
        nested = 0;
    }
    _ZN18MTextureFromPixmap6updateEv(self);
}
static void original_timeout(void *self) { assert(self == &a); ++timeouts; }
static void original_set(void *self, void *window, _Bool restacked)
{
    assert(calls < 16);
    seen_manager[calls] = self;
    seen_window[calls] = window;
    seen_restacked[calls++] = restacked;
    if (reenter) {
        reenter = 0;
        _ZN24MCompositeManagerPrivate13setCurrentAppEP16MCompositeWindowb(self, &c, 0);
    }
}
void *dlsym(void *handle, const char *name)
{
    assert(handle == (void *)-1);
    if (!strcmp(name, "_ZN18MTextureFromPixmap4bindEm")) return mode == 3 ? 0 : original_bind;
    if (!strcmp(name, "_ZN18MTextureFromPixmap6updateEv")) return mode == 4 ? 0 : original_update;
    if (!strcmp(name, "_ZN24MCompositeManagerPrivate13splashTimeoutEv")) return mode == 5 ? 0 : original_timeout;
    if (!strcmp(name, "_ZN24MCompositeManagerPrivate13setCurrentAppEP16MCompositeWindowb")) return mode == 6 ? 0 : original_set;
    assert(0); return 0;
}
int write(int fd, const void *buffer, unsigned length)
{
    assert(buffer && length && (fd == 1 || fd == 2));
    const char *line = buffer;
    if (strstr(line, "NULL_BIND_DEFERRED")) {
        assert(!strcmp(line, "N00_COMPOSITOR_SPLASH_NULL_BIND_DEFERRED\n"));
        ++null_markers;
    } else if (strstr(line, "CURRENT_APP_REFRESH")) {
        assert(!strcmp(line, "N00_COMPOSITOR_SPLASH_CURRENT_APP_REFRESH\n"));
        ++refresh_markers;
    }
    else assert(fd == 2 && strstr(line, "SPLASH_ERROR"));
    return (int)length;
}
void _exit(int status) { exit(status); }
int main(int argc, char **argv)
{
    assert(argc == 2); mode = atoi(argv[1]);
    if (mode == 3) _ZN18MTextureFromPixmap4bindEm(&a, 0);
    if (mode == 4) _ZN18MTextureFromPixmap6updateEv(&a);
    if (mode == 5) _ZN24MCompositeManagerPrivate13splashTimeoutEv(&a);
    if (mode == 6) _ZN24MCompositeManagerPrivate13setCurrentAppEP16MCompositeWindowb(&a, &c, 0);
    if (mode < 2) {
        _ZN18MTextureFromPixmap4bindEm(&a, 0);
        assert(binds == 1 + mode && updates == 2 * mode && null_markers == 1);
        _ZN18MTextureFromPixmap6updateEv(&a); /* Outside bind(None): must delegate. */
        assert(updates == 2 * mode + 1);
        _ZN18MTextureFromPixmap4bindEm(&a, 99);
        assert(updates == 2 * mode + 2 && binds == 2 + mode);
        _ZN18MTextureFromPixmap4bindEm(&a, 0);
        assert(null_markers == 1 && updates == 4 * mode + 2);
    } else if (mode == 2) {
        _ZN24MCompositeManagerPrivate13setCurrentAppEP16MCompositeWindowb(&a, &c, 0);
        _ZN24MCompositeManagerPrivate13setCurrentAppEP16MCompositeWindowb(&a, &c, 1);
        _ZN24MCompositeManagerPrivate13splashTimeoutEv(&a);
        assert(timeouts == 1 && refresh_markers == 0);
        _ZN24MCompositeManagerPrivate13setCurrentAppEP16MCompositeWindowb(&b, &c, 0);
        _ZN24MCompositeManagerPrivate13setCurrentAppEP16MCompositeWindowb(&a, &b, 0);
        _ZN24MCompositeManagerPrivate13setCurrentAppEP16MCompositeWindowb(&a, &c, 0);
        assert(calls == 5 && !seen_restacked[0] && seen_restacked[1]);
        assert(!seen_restacked[2] && seen_restacked[3] && !seen_restacked[4]);
        assert(seen_manager[2] == &b && seen_window[3] == &b && refresh_markers == 1);
        _ZN24MCompositeManagerPrivate13splashTimeoutEv(&a);
        _ZN24MCompositeManagerPrivate13splashTimeoutEv(&a);
        reenter = 1;
        _ZN24MCompositeManagerPrivate13setCurrentAppEP16MCompositeWindowb(&a, 0, 0);
        assert(calls == 7 && seen_restacked[5] && !seen_restacked[6]);
        assert(seen_window[5] == 0 && seen_window[6] == &c);
        assert(refresh_markers == 2 && timeouts == 3);
    } else assert(0);
    return 0;
}
