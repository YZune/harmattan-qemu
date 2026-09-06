/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <assert.h>
#include <stdlib.h>
#include <string.h>

extern void _ZN14QWKPreferences12setAttributeENS_12WebAttributeEb(void *, int, _Bool);
static int mode, calls, sets, queries;
static char reference;
static void *private = &reference;
static void **owner = &private;

static void attribute(void *self, int attr, _Bool on)
{
    assert(self == &owner && attr == 1 && on);
    calls++;
}

static void set(void *ref, _Bool on)
{
    assert(calls == 1 && ref == &reference && !on);
    sets++;
}

static _Bool get(void *ref)
{
    assert(sets == 1 && ref == &reference);
    return mode == 9;
}

void *dlsym(void *handle, const char *name)
{
    assert(handle == (void *)-1);
    if (!strcmp(name, "_ZN14QWKPreferences12setAttributeENS_12WebAttributeEb"))
        return mode == 6 ? 0 : (void *)attribute;
    queries++;
    if (!strcmp(name, "WKPreferencesSetAcceleratedCompositingEnabled")) return mode == 7 ? 0 : (void *)set;
    if (!strcmp(name, "WKPreferencesGetAcceleratedCompositingEnabled")) return mode == 8 ? 0 : (void *)get;
    abort();
}

char *getenv(const char *name)
{
    assert(!strcmp(name, "N00_BROWSER_RASTER"));
    if (mode == 2) return "unverified";
    if (mode == 3) return 0;
    return "6162b4b46f28d53e93b9fcba7f4f3f7b";
}

int readlink(const char *name, char *data, unsigned int size)
{
    assert(!strcmp(name, "/proc/self/exe"));
    if (mode == 4) return -1;
    if (mode == 5) return (int)size;
    const char *value = mode == 1 ? "/usr/bin/other" : "/usr/bin/grob";
    assert(strlen(value) < size);
    memcpy(data, value, strlen(value));
    return (int)strlen(value);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    mode = atoi(argv[1]);
    if (mode == 11) owner = 0;
    if (mode == 12) private = 0;
    _ZN14QWKPreferences12setAttributeENS_12WebAttributeEb(mode == 10 ? 0 : &owner, 1, 1);
    assert(calls == 1);
    assert(sets == (mode == 0));
    assert(queries == (mode == 0 ? 2 : 0));
    return 0;
}
