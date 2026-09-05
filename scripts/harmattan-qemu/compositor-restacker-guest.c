/* SPDX-License-Identifier: GPL-2.0-or-later
 * Pinned mcompositor 1.1.35, MRestacker::event(): its state contains children
 * of the root. StructureNotify on the root itself must not add the root as
 * its own child. Otherwise restack uses it as a sibling, XConfigureWindow
 * fails, and the zero-interval stacking timer retries indefinitely.
 * Only the restacker ignores this event; Qt and the compositor still receive
 * the original root resize notification. No private Qt object offsets.
 */
extern void *dlsym(void *, const char *);
extern int write(int, const void *, unsigned);
extern void _exit(int);

/* Public Xlib XConfigureEvent prefix, with native C ABI alignment. */
typedef struct {
    int type;
    unsigned long serial;
    int send_event;
    void *display;
    unsigned long event, window;
} ConfigureEvent;
typedef _Bool (*Event)(void *, const void *);
typedef unsigned long (*Root)(void *);

_Bool _ZN10MRestacker5eventEPK7_XEvent(void *self, const ConfigureEvent *event)
{
    static Event original;
    static Root root;
    static int reported;
    if (!original) {
        original = (Event)dlsym((void *)-1, "_ZN10MRestacker5eventEPK7_XEvent");
        root = (Root)dlsym((void *)-1, "XDefaultRootWindow");
    }
    if (!original || !root || !self || !event) {
        const char error[] = "N00_COMPOSITOR_RESTACKER_ERROR unsupported ABI\n";
        write(2, error, sizeof(error) - 1);
        _exit(127);
    }
    if (event->type == 22 && event->display && event->event == event->window
        && event->window == root(event->display)) {
        if (!reported) {
            const char marker[] = "N00_COMPOSITOR_ROOT_CONFIGURE_IGNORED\n";
            write(1, marker, sizeof(marker) - 1);
            reported = 1;
        }
        return 0; /* Not a child-stacking event. Do not claim a restack succeeded. */
    }
    return original(self, event);
}
