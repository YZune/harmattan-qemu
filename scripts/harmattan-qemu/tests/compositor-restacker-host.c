/* Synthetic Xlib protocol calls: validates the narrow adapter, not a real UI. */
#include <assert.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    int type;
    unsigned long serial;
    int send_event;
    void *display;
    unsigned long event, window;
} ConfigureEvent;
extern bool _ZN10MRestacker5eventEPK7_XEvent(void *, const ConfigureEvent *);
static int mode, calls;
static bool original_result;
static ConfigureEvent *expected;
static bool original(void *self, const ConfigureEvent *event)
{
    assert(self == (void *)42 && event == expected);
    ++calls;
    return original_result;
}
static unsigned long root(void *display)
{
    assert(display == (void *)43);
    return 84;
}
void *dlsym(void *handle, const char *name)
{
    assert(handle == (void *)-1);
    if (mode == 1) return 0;
    if (!strcmp(name, "_ZN10MRestacker5eventEPK7_XEvent")) return original;
    if (!strcmp(name, "XDefaultRootWindow")) return root;
    abort();
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    mode = atoi(argv[1]);
    ConfigureEvent event = {22, 7, 0, (void *)43, 84, 84};
    expected = &event;
    if (mode == 2) {
        _ZN10MRestacker5eventEPK7_XEvent((void *)42, 0);
        abort();
    }
    assert(!_ZN10MRestacker5eventEPK7_XEvent((void *)42, &event));
    assert(calls == 0);
    /* A root-delivered child configure and a child's own configure both pass. */
    event.window = 85;
    original_result = true;
    assert(_ZN10MRestacker5eventEPK7_XEvent((void *)42, &event));
    event.event = 85;
    assert(_ZN10MRestacker5eventEPK7_XEvent((void *)42, &event));
    /* Other root events pass, including the original false result. */
    event.event = event.window = 84;
    event.type = 28;
    original_result = false;
    assert(!_ZN10MRestacker5eventEPK7_XEvent((void *)42, &event));
    assert(calls == 3);
    return 0;
}
