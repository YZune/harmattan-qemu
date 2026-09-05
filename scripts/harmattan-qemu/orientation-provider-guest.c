/* Virtual display pose, not physical sensor data. Uses the original PR1.3
 * libcontextprovider C API and its GLib dispatcher. ABI declarations follow
 * contextkit 0.5.41 contextc.h and GLib 2.28; only integer/pointer arguments.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
typedef struct _GMainLoop GMainLoop;
typedef struct _GIOChannel GIOChannel;
extern int context_provider_init(int bus_type, const char *bus_name);
extern void context_provider_stop(void);
extern void context_provider_install_key(const char *, int, void (*)(int, void *), void *);
extern void context_provider_set_string(const char *, const char *);
extern void context_provider_set_boolean(const char *, int);
extern GMainLoop *g_main_loop_new(void *, int);
extern void g_main_loop_run(GMainLoop *);
extern void g_main_loop_quit(GMainLoop *);
extern void g_main_loop_unref(GMainLoop *);
extern GIOChannel *g_io_channel_unix_new(int);
extern void g_io_channel_unref(GIOChannel *);
extern unsigned g_io_add_watch(GIOChannel *, int, int (*)(GIOChannel *, int, void *), void *);
extern int read(int, void *, unsigned);
extern int strcmp(const char *, const char *);
extern int printf(const char *, ...);
extern int fflush(void *);

static GMainLoop *loop;

static int valid_edge(const char *edge)
{
    return !strcmp(edge, "top") || !strcmp(edge, "left") ||
           !strcmp(edge, "bottom") || !strcmp(edge, "right");
}

static void publish(const char *edge)
{
    context_provider_set_string("Screen.TopEdge", edge);
    context_provider_set_boolean("Position.IsFlat", 0);
    printf("N00_ORIENTATION_VALUE edge=%s flat=0\n", edge);
    fflush((void *)0);
}

static int control_input(GIOChannel *channel, int condition, void *unused)
{
    static char line[16];
    static unsigned length;
    static int overflow;
    char bytes[64];
    int count;
    (void)channel;
    (void)unused;
    if (!(condition & 1)) { /* G_IO_IN; HUP/ERR/NVAL terminate, never busy-loop. */
        g_main_loop_quit(loop);
        return 0;
    }
    count = read(0, bytes, sizeof(bytes));
    if (count <= 0) {
        g_main_loop_quit(loop);
        return 0;
    }
    for (int i = 0; i < count; ++i) {
        if (bytes[i] == '\n') {
            line[length] = 0;
            if (!overflow && valid_edge(line)) {
                publish(line);
            } else {
                printf("N00_ORIENTATION_REJECT invalid-edge\n");
                fflush((void *)0);
            }
            length = 0;
            overflow = 0;
        } else if (bytes[i] == '\0') {
            overflow = 1; /* Never accept a valid prefix before an embedded NUL. */
        } else if (length + 1 < sizeof(line)) {
            line[length++] = bytes[i];
        } else {
            overflow = 1;
        }
    }
    return 1;
}

int main(int argc, char **argv)
{
    if (argc != 2 || !valid_edge(argv[1])) {
        printf("Usage: n00-orientation-provider top|left|bottom|right\n");
        return 2;
    }
    /* DBUS_BUS_SESSION = 0. Never claim SensorService or Commander. */
    if (!context_provider_init(0, "org.harmattan.QemuOrientation")) {
        return 1;
    }
    context_provider_install_key("Screen.TopEdge", 0, (void *)0, (void *)0);
    context_provider_install_key("Position.IsFlat", 0, (void *)0, (void *)0);
    publish(argv[1]);
    loop = g_main_loop_new((void *)0, 0);
    GIOChannel *input = g_io_channel_unix_new(0);
    g_io_add_watch(input, 1 | 8 | 16 | 32, control_input, (void *)0);
    g_main_loop_run(loop);
    g_io_channel_unref(input);
    g_main_loop_unref(loop);
    context_provider_stop();
    return 0;
}
