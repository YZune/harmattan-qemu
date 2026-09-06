/* SPDX-License-Identifier: GPL-2.0-or-later
 * Grob 0.73.2 / libgrob-qtwebkit 0.73.0 only. The launcher verifies both
 * binaries before enabling this helper. The pinned qwk_1.0 setAttribute ABI
 * reads QWKPreferences -> private -> WKPreferencesRef (two pointer loads at
 * offset zero). Use that reference with the original exported preferences
 * APIs. Do not change JavaScript, TLS verification or GLES error handling.
 */
extern void *dlsym(void *, const char *);
extern int readlink(const char *, char *, unsigned int);
extern int strcmp(const char *, const char *);
extern char *getenv(const char *);
extern int write(int, const void *, unsigned int);
extern void _exit(int);

static void fail(void)
{
    const char marker[] = "N00_BROWSER_ERROR preferences ABI\n";
    write(2, marker, sizeof(marker) - 1);
    _exit(123);
}

static int enabled(void)
{
    char path[256];
    const char *mode = getenv("N00_BROWSER_RASTER");
    if (!mode || strcmp(mode, "6162b4b46f28d53e93b9fcba7f4f3f7b")) return 0;
    int length = readlink("/proc/self/exe", path, sizeof(path) - 1);
    if (length < 0 || length >= (int)sizeof(path) - 1) return 0;
    path[length] = 0;
    return !strcmp(path, "/usr/bin/grob");
}

void _ZN14QWKPreferences12setAttributeENS_12WebAttributeEb(void *self, int attr, _Bool on)
{
    typedef void (*Attribute)(void *, int, _Bool);
    typedef void (*Set)(void *, _Bool);
    typedef _Bool (*Get)(void *);
    Attribute original = (Attribute)dlsym((void *)-1,
        "_ZN14QWKPreferences12setAttributeENS_12WebAttributeEb");
    if (!original) fail();
    if (!enabled()) {
        original(self, attr, on);
        return;
    }
    if (!self || !*(void **)self || !**(void ***)self) fail();
    Set set = (Set)dlsym((void *)-1, "WKPreferencesSetAcceleratedCompositingEnabled");
    Get get = (Get)dlsym((void *)-1, "WKPreferencesGetAcceleratedCompositingEnabled");
    if (!set || !get) fail();
    original(self, attr, on);
    void *preferences = **(void ***)self;
    set(preferences, 0);
    if (get(preferences)) fail();
    const char marker[] = "N00_BROWSER_SOFTWARE_COMPOSITING verified\n";
    write(1, marker, sizeof(marker) - 1);
}
