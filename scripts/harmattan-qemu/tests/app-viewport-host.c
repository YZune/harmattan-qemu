/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <assert.h>
#include <stdlib.h>
#include <string.h>

extern void _ZN19QAbstractScrollArea11setViewportEP7QWidget(void *, void *);
static int mode, called, deleted, queried_qt;
static char owner, viewport, meta;
static void *received;

static void original(void *self, void *widget)
{
    assert(self == &owner);
    called++;
    received = widget;
}

static void *cast(const void *metadata, void *widget)
{
    assert(metadata == &meta && widget == &viewport);
    return mode == 3 ? 0 : widget;
}

static void later(void *widget)
{
    assert(called == 1 && received == 0 && widget == &viewport);
    deleted++;
}

void *dlsym(void *handle, const char *name)
{
    assert(handle == (void *)-1);
    if (!strcmp(name, "_ZN19QAbstractScrollArea11setViewportEP7QWidget"))
        return mode == 5 ? 0 : (void *)original;
    queried_qt++;
    if (!strcmp(name, "_ZNK11QMetaObject4castEP7QObject")) return mode == 6 ? 0 : (void *)cast;
    if (!strcmp(name, "_ZN7QObject11deleteLaterEv")) return mode == 7 ? 0 : (void *)later;
    if (!strcmp(name, "_ZN9QGLWidget16staticMetaObjectE")) return mode == 8 ? 0 : &meta;
    abort();
}

char *getenv(const char *name)
{
    if (strcmp(name, "N00_FB_READER_RASTER")) return 0;
    return mode == 2 ? "unverified" : "a4f60e9b2da8416348101b04140950c0";
}

int readlink(const char *name, char *data, unsigned int size)
{
    assert(!strcmp(name, "/proc/self/exe"));
    if (mode == 10) return -1;
    if (mode == 9) return (int)size;
    const char *value = mode == 1 ? "/opt/other/program" : "/opt/fbreader/bin/FBReader";
    assert(strlen(value) < size);
    memcpy(data, value, strlen(value));
    return (int)strlen(value);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    mode = atoi(argv[1]);
    _ZN19QAbstractScrollArea11setViewportEP7QWidget(&owner, mode == 4 ? 0 : &viewport);
    assert(called == 1);
    assert(deleted == (mode == 0));
    assert(received == ((mode == 0 || mode == 4) ? 0 : &viewport));
    if (mode == 1 || mode == 2 || mode == 4 || mode == 9 || mode == 10) assert(queried_qt == 0);
    return 0;
}
