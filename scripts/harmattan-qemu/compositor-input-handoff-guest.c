/* SPDX-License-Identifier: GPL-2.0-or-later
 * Pinned PR1.3 compositor, fullscreen self-composited input method on the
 * 864x480 software Xorg. mapRequestEvent redirects the app before mapping the
 * IM window, without showOverlayWindow(true). On IM unmap, the app is still
 * redirected until possiblyUnredirectTopmostWindow runs. Xorg exposes and
 * paints the black root in both gaps.
 *
 * Copy the actual screen before redirection, then bind the application's live
 * backing pixmap as root background after the original map handler. Xorg uses
 * those real pixels for the exposed root while the two original clients hand
 * over. Background None is NOT usable for root: old Xorg makes a stipple tile.
 * Restore the launcher's Xorg -br background after original direct-render
 * restoration or when the app goes away. No fabricated images, pixel tests,
 * polling, sleep, extra windows, input grabs or private Qt fields.
 */
extern void *dlsym(void *, const char *);
extern int snprintf(char *, __SIZE_TYPE__, const char *, ...);
extern int write(int, const void *, unsigned);
extern void _exit(int);

typedef unsigned long Xid;
/* Public XMapRequest/Unmap/Destroy event common prefix. */
typedef struct {
    int type;
    unsigned long serial;
    int send_event;
    void *display;
    Xid event, window;
} WindowEvent;
typedef void (*EventFunction)(void *, const WindowEvent *);
typedef Xid (*AtomFunction)(void *, const char *, int);
typedef int (*PropertyFunction)(void *, Xid, Xid, long, long, int, Xid,
                               Xid *, int *, unsigned long *, unsigned long *, unsigned char **);
typedef int (*GeometryFunction)(void *, Xid, Xid *, int *, int *, unsigned *, unsigned *, unsigned *, unsigned *);
typedef int (*SetBackground)(void *, Xid, Xid);

static void *current_display;
static Xid current_parent, current_input, current_root;
static Xid retained;
static unsigned generation;

static void fail(void)
{
    const char message[] = "N00_COMPOSITOR_INPUT_HANDOFF_ERROR unsupported ABI\n";
    write(2, message, sizeof(message) - 1);
    _exit(125);
}

static void *resolve(const char *name)
{
    void *function = dlsym((void *)-1, name);
    if (!function) fail();
    return function;
}

static void report(const char *phase, const char *reason)
{
    char line[180];
    int size = snprintf(line, sizeof(line),
        "N00_COMPOSITOR_INPUT_HANDOFF_%s id=%u parent=%lx input=%lx reason=%s\n",
        phase, generation, current_parent, current_input, reason);
    if (size <= 0 || size >= (int)sizeof(line)) fail();
    write(1, line, (unsigned)size);
}

static Xid atom(void *display, const char *name)
{
    return ((AtomFunction)resolve("XInternAtom"))(display, name, 0);
}

static Xid first_property(void *display, Xid window, const char *name, Xid expected_type)
{
    Xid actual_type = 0;
    int format = 0;
    unsigned long count = 0, after = 0;
    unsigned char *data = 0;
    int status = ((PropertyFunction)resolve("XGetWindowProperty"))(
        display, window, atom(display, name), 0, 1, 0, expected_type,
        &actual_type, &format, &count, &after, &data);
    Xid value = !status && actual_type == expected_type && format == 32
        && count == 1 && data ? *(Xid *)data : 0;
    if (data) ((int (*)(void *))resolve("XFree"))(data);
    return value;
}

static int fullscreen(void *display, Xid window, Xid root)
{
    Xid actual_root = 0;
    int x = 0, y = 0;
    unsigned width = 0, height = 0, border = 0, depth = 0;
    return ((GeometryFunction)resolve("XGetGeometry"))(display, window,
        &actual_root, &x, &y, &width, &height, &border, &depth)
        && actual_root == root && !x && !y && !border
        && width == 864 && height == 480 && depth == 24;
}

static void preserve_screen(void)
{
    typedef Xid (*CreatePixmap)(void *, Xid, unsigned, unsigned, unsigned);
    typedef void *(*CreateGC)(void *, Xid, unsigned long, void *);
    typedef int (*GCMode)(void *, void *, int);
    typedef int (*Copy)(void *, Xid, Xid, void *, int, int, unsigned, unsigned, int, int);
    if (retained) fail();
    retained = ((CreatePixmap)resolve("XCreatePixmap"))(current_display, current_root, 864, 480, 24);
    void *gc = ((CreateGC)resolve("XCreateGC"))(current_display, current_root, 0, 0);
    if (!retained || !gc) fail();
    ((GCMode)resolve("XSetSubwindowMode"))(current_display, gc, 1); /* IncludeInferiors */
    ((GCMode)resolve("XSetGraphicsExposures"))(current_display, gc, 0);
    ((Copy)resolve("XCopyArea"))(current_display, current_root, retained, gc, 0, 0, 864, 480, 0, 0);
    ((int (*)(void *, void *))resolve("XFreeGC"))(current_display, gc);
    ((SetBackground)resolve("XSetWindowBackgroundPixmap"))(current_display, current_root, retained);
}

static void share_parent_backing(void)
{
    Xid pixmap = ((Xid (*)(void *, Xid))resolve("XCompositeNameWindowPixmap"))(current_display, current_parent);
    if (pixmap && fullscreen(current_display, pixmap, current_root)) {
        ((SetBackground)resolve("XSetWindowBackgroundPixmap"))(current_display, current_root, pixmap);
        ((int (*)(void *, Xid))resolve("XFreePixmap"))(current_display, retained);
        retained = pixmap;
        report("SHARED", "parent-backing");
    } else {
        if (pixmap) ((int (*)(void *, Xid))resolve("XFreePixmap"))(current_display, pixmap);
        /* Keep the real captured screen on a failed backing lookup; never
         * upload uninitialized data. The original unredirect still releases
         * it. A full diagnostic requires successful live backing handoffs. */
        report("PENDING", "parent-backing");
    }
}

static void finish(const char *reason, int expose_root)
{
    if (!current_parent) return;
    int screen = ((int (*)(void *))resolve("XDefaultScreen"))(current_display);
    Xid black = ((Xid (*)(void *, int))resolve("XBlackPixel"))(current_display, screen);
    ((SetBackground)resolve("XSetWindowBackground"))(current_display, current_root, black);
    ((int (*)(void *, Xid))resolve("XFreePixmap"))(current_display, retained);
    retained = 0;
    /* Parent disappearance has no subsequent direct-render restore. Expose
     * only the root's uncovered region using its original black background. */
    if (expose_root)
        ((int (*)(void *, Xid))resolve("XClearWindow"))(current_display, current_root);
    report("RESTORED", reason);
    current_parent = current_input = current_root = 0;
    current_display = 0;
}

void _ZN24MCompositeManagerPrivate15mapRequestEventEP16XMapRequestEvent(void *self, const WindowEvent *event)
{
    static EventFunction original;
    if (!original) original = (EventFunction)resolve("_ZN24MCompositeManagerPrivate15mapRequestEventEP16XMapRequestEvent");
    if (!self || !event || !event->display) fail();
    void *display = event->display;
    Xid root = ((Xid (*)(void *))resolve("XDefaultRootWindow"))(display), parent = 0;
    int prepared = 0;
    if (event->type == 20 && event->event == root
        && first_property(display, event->window, "_NET_WM_WINDOW_TYPE", 4) == atom(display, "_NET_WM_WINDOW_TYPE_INPUT")
        && ((int (*)(void *, Xid, Xid *))resolve("XGetTransientForHint"))(display, event->window, &parent)
        && parent && parent != root && parent != event->window
        && first_property(display, root, "_NET_ACTIVE_WINDOW", 33) == parent
        /* The unmapped IM window may still be 432x192. The original handler
         * below resizes it to fullscreen after mapping; do not require that
         * future geometry before preserving the currently visible app. */
        && fullscreen(display, parent, root)
        && fullscreen(display, root, root)) {
        if (current_parent != parent || current_input != event->window || current_display != display) {
            finish("replacement", 0);
            current_display = display;
            current_parent = parent;
            current_input = event->window;
            current_root = root;
            ++generation;
            preserve_screen();
            report("PRESERVED", "input-map");
            prepared = 1;
        }
    }
    original(self, event);
    if (prepared && current_display == display && current_input == event->window && current_parent == parent)
        share_parent_backing();
}

void XCompositeUnredirectWindow(void *display, Xid window, int update)
{
    typedef void (*Unredirect)(void *, Xid, int);
    static Unredirect original;
    if (!original) original = (Unredirect)resolve("XCompositeUnredirectWindow");
    original(display, window, update);
    /* X11 orders the original backing-to-window copy before restoring the
     * root background; changing a background does not clear visible pixels. */
    if (display == current_display && window == current_parent && update == 1)
        finish("direct", 0);
}

void _ZN24MCompositeManagerPrivate10unmapEventEP11XUnmapEvent(void *self, const WindowEvent *event)
{
    static EventFunction original;
    if (!original) original = (EventFunction)resolve("_ZN24MCompositeManagerPrivate10unmapEventEP11XUnmapEvent");
    if (!self || !event) fail();
    if (!event->send_event && event->display == current_display
        && event->event == current_root && event->window == current_parent)
        finish("parent-unmap", 1);
    original(self, event);
}

void _ZN24MCompositeManagerPrivate12destroyEventEP19XDestroyWindowEvent(void *self, const WindowEvent *event)
{
    static EventFunction original;
    if (!original) original = (EventFunction)resolve("_ZN24MCompositeManagerPrivate12destroyEventEP19XDestroyWindowEvent");
    if (!self || !event) fail();
    if (!event->send_event && event->display == current_display
        && event->event == current_root && event->window == current_parent)
        finish("parent-destroy", 1);
    original(self, event);
}
