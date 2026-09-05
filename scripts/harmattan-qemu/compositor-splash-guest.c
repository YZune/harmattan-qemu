/* SPDX-License-Identifier: GPL-2.0-or-later
 * Opt-in addition for the pinned PR1.3 libmcompositor.so.1.1.3 only.
 * Source: mtexturefrompixmap_egl.cpp and mcompositemanager.cpp (1.1.35).
 * Original exported methods own the state. No Qt/private object offsets,
 * replacement images, animation timing changes or forced gesture decisions.
 * These methods run on the compositor's single GUI/render event thread.
 */
extern void *dlsym(void *, const char *);
extern int write(int, const void *, unsigned int);
extern void _exit(int);

static void *resolve(const char *name)
{
    void *symbol = dlsym((void *)-1, name);
    if (!symbol) {
        const char error[] = "N00_COMPOSITOR_SPLASH_ERROR missing original symbol\n";
        write(2, error, sizeof(error) - 1);
        _exit(125);
    }
    return symbol;
}

static void *null_binding;

void _ZN18MTextureFromPixmap4bindEm(void *self, unsigned long drawable)
{
    typedef void (*Bind)(void *, unsigned long);
    static Bind original;
    if (!original) original = (Bind)resolve("_ZN18MTextureFromPixmap4bindEm");
    void *previous = null_binding;
    null_binding = drawable ? 0 : self;
    /* Keep original drawable/valid bookkeeping and EGLImage cleanup. Only
     * its synchronous non-EGLImage update(None) below is deferred. */
    original(self, drawable);
    null_binding = previous;
}

void _ZN18MTextureFromPixmap6updateEv(void *self)
{
    typedef void (*Update)(void *);
    static Update original;
    if (self && self == null_binding) {
        static int logged;
        if (!logged) {
            logged = 1;
            const char marker[] = "N00_COMPOSITOR_SPLASH_NULL_BIND_DEFERRED\n";
            write(1, marker, sizeof(marker) - 1);
        }
        return;
    }
    if (!original) original = (Update)resolve("_ZN18MTextureFromPixmap6updateEv");
    original(self);
}

static void *refresh_pending;

void _ZN24MCompositeManagerPrivate13splashTimeoutEv(void *self)
{
    typedef void (*Timeout)(void *);
    static Timeout original;
    if (!original) original = (Timeout)resolve("_ZN24MCompositeManagerPrivate13splashTimeoutEv");
    original(self);
    /* Original removes the virtual splash and schedules dirtyStacking().
     * It is absent from the real-client order, so the ordinary restacked flag
     * can remain false even though the swipe plugin must replace its target. */
    refresh_pending = self;
}

void _ZN24MCompositeManagerPrivate13setCurrentAppEP16MCompositeWindowb(void *self, void *window, _Bool restacked)
{
    typedef void (*SetCurrent)(void *, void *, _Bool);
    static SetCurrent original;
    if (!original) original = (SetCurrent)resolve("_ZN24MCompositeManagerPrivate13setCurrentAppEP16MCompositeWindowb");
    if (self == refresh_pending) {
        refresh_pending = 0;
        restacked = 1;
        const char marker[] = "N00_COMPOSITOR_SPLASH_CURRENT_APP_REFRESH\n";
        write(1, marker, sizeof(marker) - 1);
    }
    /* Do not choose an app or emit a synthetic X11 activation. Let the
     * original manager notify its actual current app through its own path. */
    original(self, window, restacked);
}
