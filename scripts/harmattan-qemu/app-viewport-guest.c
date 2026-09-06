/* SPDX-License-Identifier: GPL-2.0-or-later
 * Pinned FBReader 0.99.5 viewport adaptation. The guest launcher verifies the
 * executable and Qt library hashes before enabling this inherited helper.
 * Qt 4.7.4 qabstractscrollarea.cpp: setViewport(NULL) creates a plain QWidget.
 * Use exported Qt APIs only; no QObject layout or application code changes.
 */
extern void *dlsym(void *, const char *);
extern int readlink(const char *, char *, unsigned int);
extern int strcmp(const char *, const char *);
extern char *getenv(const char *);
extern int write(int, const void *, unsigned int);
extern void _exit(int);

static void fail(void)
{
    const char marker[] = "N00_APP_VIEWPORT_ERROR Qt ABI\n";
    write(2, marker, sizeof(marker) - 1);
    _exit(122);
}

static int reader_enabled(void)
{
    char path[256];
    const char *mode = getenv("N00_FB_READER_RASTER");
    if (!mode || strcmp(mode, "a4f60e9b2da8416348101b04140950c0")) return 0;
    int length = readlink("/proc/self/exe", path, sizeof(path) - 1);
    if (length < 0 || length >= (int)sizeof(path) - 1) return 0;
    path[length] = 0;
    return !strcmp(path, "/opt/fbreader/bin/FBReader");
}

void _ZN19QAbstractScrollArea11setViewportEP7QWidget(void *self, void *widget)
{
    typedef void (*Set)(void *, void *);
    typedef void *(*Cast)(const void *, void *);
    typedef void (*Later)(void *);
    Set original = (Set)dlsym((void *)-1,
        "_ZN19QAbstractScrollArea11setViewportEP7QWidget");
    if (!original) fail();
    if (!widget || !reader_enabled()) {
        original(self, widget);
        return;
    }
    Cast cast = (Cast)dlsym((void *)-1, "_ZNK11QMetaObject4castEP7QObject");
    Later later = (Later)dlsym((void *)-1, "_ZN7QObject11deleteLaterEv");
    void *meta = dlsym((void *)-1, "_ZN9QGLWidget16staticMetaObjectE");
    if (!cast || !later || !meta) fail();
    if (cast(meta, widget)) {
        original(self, 0);
        /* The unused original QGLWidget must be destroyed by Qt's event loop. */
        later(widget);
        const char marker[] = "N00_APP_VIEWPORT_FB_READER_RASTER\n";
        write(1, marker, sizeof(marker) - 1);
    } else {
        original(self, widget);
    }
}
