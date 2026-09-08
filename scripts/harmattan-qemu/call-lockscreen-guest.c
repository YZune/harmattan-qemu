/* SPDX-License-Identifier: GPL-2.0-or-later
 * Narrow bridge from the synthetic call bus to the original ScreenLock UI.
 * This is a presentation adapter, not an MCE, modem or security provider.
 */
#include "call-simulation-dbus.h"
extern DBusConnection *dbus_connection_open_private(const char *, void *);
extern int dbus_bus_register(DBusConnection *, void *);
extern DBusMessage *dbus_connection_send_with_reply_and_block(DBusConnection *, DBusMessage *, int, void *);
extern DBusMessage *dbus_message_copy(const DBusMessage *);
extern int dbus_message_set_destination(DBusMessage *, const char *);
extern int dbus_message_set_sender(DBusMessage *, const char *);
extern int dbus_message_set_reply_serial(DBusMessage *, unsigned);
extern void dbus_message_set_serial(DBusMessage *, unsigned);
extern DBusMessage *dbus_message_ref(DBusMessage *);
struct MonoTime {
    int seconds, nanos;
};
extern int clock_gettime(int, struct MonoTime *);
extern void dbus_message_set_no_reply(DBusMessage *, int);
extern int dbus_message_get_no_reply(DBusMessage *);
extern unsigned dbus_message_get_serial(DBusMessage *);
extern const char *dbus_message_get_sender(DBusMessage *);
extern int readlink(const char *, char *, unsigned);
extern void *popen(const char *, const char *);
extern int pclose(void *);
extern char *fgets(char *, int, void *);
extern int sscanf(const char *, const char *, ...);
#define LOCK "com.nokia.systemui.ScreenLock"
#define CLIENT LOCK "Client"
#define RELAY "org.harmattan.CallSimulation.LockUi"
#define CONTROL "/org/harmattan/CallSimulation/LockUi"
static DBusConnection *priv, *desk;
static unsigned saved_mapped, saved_low, active, sysuid_pid;
static void fatal(const char *why) {
    printf("LOCK_FATAL %s\n", why);
    fflush(0);
    exit(2);
}
static void send(DBusConnection *b, DBusMessage *m) {
    if (!m || !dbus_connection_send(b, m, 0))
        fatal("send");
    dbus_connection_flush(b);
    dbus_message_unref(m);
}
static void str(Iter *i, const char *s) {
    if (!dbus_message_iter_append_basic(i, 's', &s))
        fatal("append");
}
static void error(DBusConnection *b, DBusMessage *m, const char *kind) {
    send(b, dbus_message_new_error(m, kind, "Scoped simulated-call lock UI bridge"));
}
static unsigned sender_pid(DBusConnection *b, const char *sender) {
    if (!sender || sender[0] != ':')
        return 0;
    DBusMessage *q = dbus_message_new_method_call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                                  "org.freedesktop.DBus", "GetConnectionUnixProcessID");
    Iter i;
    dbus_message_iter_init_append(q, &i);
    str(&i, sender);
    DBusMessage *r = dbus_connection_send_with_reply_and_block(b, q, 3000, 0);
    dbus_message_unref(q);
    unsigned pid = 0;
    if (r && dbus_message_get_type(r) == 2 && !strcmp(dbus_message_get_signature(r), "u")) {
        dbus_message_iter_init(r, &i);
        dbus_message_iter_get_basic(&i, &pid);
    }
    if (r)
        dbus_message_unref(r);
    return pid;
}
static int identity(DBusConnection *b, DBusMessage *m, const char *expected) {
    unsigned pid = sender_pid(b, dbus_message_get_sender(m));
    char path[64], actual[128];
    if (!pid || (b == desk && pid != sysuid_pid))
        return 0;
    snprintf(path, sizeof(path), "/proc/%u/exe", pid);
    int n = readlink(path, actual, sizeof(actual) - 1);
    if (n <= 0 || n >= (int)sizeof(actual) - 1)
        return 0;
    actual[n] = 0;
    return !strcmp(actual, expected);
}
static void observe(const char *action, unsigned *mapped, unsigned *low) {
    /* Only literal actions from this source enter the shell command. The
     * helper checks original binary hashes, bus owner and X11 window PID. */
    char cmd[180], line[256];
    unsigned window, pid, count = 0;
    snprintf(cmd, sizeof(cmd), "N00_CALL_LOCKSCREEN=on perl /tmp/n00-ui-helpers/screenlock-guest.pl %s",
             action);
    void *p = popen(cmd, "r");
    if (!p)
        fatal("lock helper start");
    while (fgets(line, sizeof(line), p)) {
        if (sscanf(line, "N00_LOCKSCREEN window=%x pid=%u mapped=%u low_power=%u", &window, &pid, mapped,
                   low) == 4) {
            if (++count != 1 || *mapped > 1 || *low > 1 || (!window && (*mapped || *low)) ||
                (sysuid_pid && sysuid_pid != pid))
                fatal("lock identity/state changed");
            sysuid_pid = pid;
        }
    }
    if (pclose(p) || count != 1)
        fatal("lock helper failed");
    printf("LOCK_OBSERVED %s mapped=%u low=%u pid=%u\n", action, *mapped, *low, sysuid_pid);
    fflush(0);
}
static void mode(unsigned mapped) {
    DBusMessage *m =
        dbus_message_new_signal("/com/nokia/mce/signal", "com.nokia.mce.signal", "tklock_mode_ind");
    Iter i;
    dbus_message_iter_init_append(m, &i);
    str(&i, mapped ? "locked" : "unlocked");
    send(priv, m);
}
/* insertEvent can synchronously call eventShown before returning. Forward
 * asynchronously in both directions, otherwise the two original Qt services
 * deadlock waiting for a callback which this relay has not yet dispatched. */
static struct Pending {
    DBusConnection *from, *to;
    DBusMessage *original;
    unsigned serial;
    int expires;
} pending[16];
static int seconds(void) {
    struct MonoTime t;
    if (clock_gettime(1, &t))
        fatal("monotonic clock");
    return t.seconds;
}
static void forward(DBusConnection *from, DBusConnection *to, DBusMessage *m, DBusMessage *n) {
    dbus_message_set_serial(n, 0);
    dbus_message_set_no_reply(n, dbus_message_get_no_reply(m));
    if (dbus_message_get_no_reply(m)) {
        send(to, n);
        return;
    }
    for (unsigned k = 0; k < 16; k++) {
        if (pending[k].original)
            continue;
        pending[k].from = from;
        pending[k].to = to;
        pending[k].original = dbus_message_ref(m);
        pending[k].expires = seconds() + 15;
        if (!dbus_connection_send(to, n, &pending[k].serial))
            fatal("forward send");
        dbus_connection_flush(to);
        dbus_message_unref(n);
        return;
    }
    fatal("too many pending calls");
}
static void forwarded_reply(DBusConnection *from, DBusMessage *m) {
    for (unsigned k = 0; k < 16; k++) {
        struct Pending *p = &pending[k];
        if (!p->original || p->to != from || p->serial != dbus_message_get_reply_serial(m))
            continue;
        if (!identity(from, m, from == desk ? "/usr/bin/sysuid" : "/usr/bin/call-ui"))
            fatal("reply sender identity");
        if (dbus_message_get_type(m) == 3) {
            printf("LOCK_FORWARD_ERROR %s %s\n", dbus_message_get_member(p->original),
                   dbus_message_get_error_name(m));
            fflush(0);
        }
        DBusMessage *r = dbus_message_copy(m);
        dbus_message_set_serial(r, 0);
        dbus_message_set_sender(r, 0);
        dbus_message_set_destination(r, dbus_message_get_sender(p->original));
        dbus_message_set_reply_serial(r, dbus_message_get_serial(p->original));
        send(p->from, r);
        dbus_message_unref(p->original);
        p->original = 0;
        return;
    }
}
static void request(DBusConnection *from, DBusConnection *to, DBusMessage *m) {
    if (dbus_message_get_type(m) != 1) {
        if (dbus_message_get_type(m) == 2 || dbus_message_get_type(m) == 3)
            forwarded_reply(from, m);
        return;
    }
    const char *iface = dbus_message_get_interface(m), *method = dbus_message_get_member(m),
               *path = dbus_message_get_path(m), *sig = dbus_message_get_signature(m);
    if (!iface || !method || !path) {
        error(from, m, "org.freedesktop.DBus.Error.UnknownMethod");
        return;
    }
    if (from == priv && !strcmp(iface, RELAY) && !strcmp(path, CONTROL)) {
        if (!identity(priv, m, "/tmp/n00-ui-helpers/n00-call-simulation"))
            goto denied;
        if (*sig)
            goto invalid;
        unsigned mapped, low;
        if (!strcmp(method, "Begin") && !active) {
            observe("inspect", &saved_mapped, &saved_low);
            observe("call-wake", &mapped, &low);
            active = 1;
            mode(mapped);
            printf("LOCK_BEGIN mapped=%u low=%u\n", saved_mapped, saved_low);
        } else if (!strcmp(method, "Finish") && active) {
            observe(saved_mapped ? (saved_low ? "call-clock" : "call-wallpaper") : "inspect", &mapped, &low);
            active = 0;
            mode(mapped);
            printf("LOCK_FINISH mapped=%u low=%u\n", mapped, low);
        } else {
            error(from, m, "org.freedesktop.DBus.Error.NotSupported");
            return;
        }
        fflush(0);
        send(from, dbus_message_new_method_return(m));
        return;
    }
    if (from == priv && !strcmp(iface, "com.nokia.mce.request") && !strcmp(path, "/com/nokia/mce/request")) {
        if (!identity(priv, m, "/usr/bin/call-ui"))
            goto denied;
        if (!strcmp(method, "get_tklock_mode") && !*sig) {
            unsigned mapped, low;
            observe("inspect", &mapped, &low);
            DBusMessage *r = dbus_message_new_method_return(m);
            Iter i;
            dbus_message_iter_init_append(r, &i);
            str(&i, mapped ? "locked" : "unlocked");
            send(from, r);
        } else
            error(from, m, "org.freedesktop.DBus.Error.NotSupported");
        return;
    }
    if (from == priv && !strcmp(iface, LOCK) && !strcmp(path, "/screenlock")) {
        if (!identity(priv, m, "/usr/bin/call-ui"))
            goto denied;
        int insert = !strcmp(method, "insertEvent");
        if ((insert && strcmp(sig, "sssssu") && strcmp(sig, "sssssus")) ||
            (!insert && (strcmp(method, "removeEvent") || strcmp(sig, "s"))))
            goto invalid;
        Iter in, out;
        dbus_message_iter_init(m, &in);
        const char *s;
        dbus_message_iter_get_basic(&in, &s);
        if (strcmp(s, "call"))
            goto invalid;
        DBusMessage *n = dbus_message_new_method_call(LOCK, "/screenlock", LOCK, method);
        dbus_message_iter_init_append(n, &out);
        int k = 0;
        do {
            if (dbus_message_iter_get_arg_type(&in) == 's') {
                dbus_message_iter_get_basic(&in, &s);
                if ((k == 1 && strcmp(s, "com.nokia.call-ui")) ||
                    (k == 2 && strcmp(s, "/ScreenLockClient"))) {
                    dbus_message_unref(n);
                    goto invalid;
                }
                str(&out, k == 1 ? RELAY : s);
            } else {
                unsigned value;
                dbus_message_iter_get_basic(&in, &value);
                if (!dbus_message_iter_append_basic(&out, 'u', &value))
                    fatal("pixmap append");
            }
            k++;
        } while (dbus_message_iter_next(&in));
        printf("LOCK_EVENT %s\n", method);
        fflush(0);
        forward(from, to, m, n);
        return;
    }
    if (from == desk && !strcmp(iface, CLIENT) && !strcmp(path, "/ScreenLockClient")) {
        if (!identity(desk, m, "/usr/bin/sysuid"))
            goto denied;
        if (!strcmp(method, "actionTriggered")) {
            if (strcmp(sig, "s"))
                goto invalid;
            Iter in;
            const char *s;
            dbus_message_iter_init(m, &in);
            dbus_message_iter_get_basic(&in, &s);
            if (strcmp(s, "swipe-up") && strcmp(s, "swipe-down") && strcmp(s, "power-key"))
                goto invalid;
            printf("LOCK_ACTION %s\n", s);
        } else if ((strcmp(method, "eventShown") && strcmp(method, "eventHidden")) || *sig)
            goto invalid;
        fflush(0);
        DBusMessage *n = dbus_message_copy(m);
        dbus_message_set_destination(n, "com.nokia.call-ui");
        dbus_message_set_sender(n, 0);
        forward(from, to, m, n);
        return;
    }
    error(from, m, "org.freedesktop.DBus.Error.UnknownMethod");
    return;
invalid:
    error(from, m, "org.freedesktop.DBus.Error.InvalidArgs");
    return;
denied:
    error(from, m, "org.freedesktop.DBus.Error.AccessDenied");
}
int main(void) {
    const char *enabled = getenv("N00_CALL_LOCKSCREEN"), *address = getenv("DBUS_SESSION_BUS_ADDRESS");
    if (getuid() != 0 || !enabled || strcmp(enabled, "on") || !address ||
        strcmp(address, "unix:path=/tmp/n00-call-simulation/bus"))
        return 2;
    unsigned mapped, low;
    observe("inspect", &mapped, &low);
    priv = dbus_bus_get(0, 0);
    desk = dbus_connection_open_private("unix:path=/tmp/n00-shell-session-bus", 0);
    if (!priv || !desk || !dbus_bus_register(desk, 0))
        fatal("bus connection");
    if (dbus_bus_request_name(priv, LOCK, 4, 0) != 1 ||
        dbus_bus_request_name(priv, "com.nokia.mce", 4, 0) != 1 ||
        dbus_bus_request_name(priv, RELAY, 4, 0) != 1 || dbus_bus_request_name(desk, RELAY, 4, 0) != 1)
        fatal("bus ownership");
    printf("LOCK_READY\n");
    fflush(0);
    while (dbus_connection_read_write(priv, 10) && dbus_connection_read_write(desk, 10)) {
        for (unsigned k = 0; k < 16; k++) {
            if (pending[k].original && seconds() >= pending[k].expires) {
                printf("LOCK_TIMEOUT %s\n", dbus_message_get_member(pending[k].original));
                fatal("forward timeout");
            }
        }
        DBusMessage *m;
        while ((m = dbus_connection_pop_message(priv))) {
            request(priv, desk, m);
            dbus_message_unref(m);
        }
        while ((m = dbus_connection_pop_message(desk))) {
            request(desk, priv, m);
            dbus_message_unref(m);
        }
    }
    return 0;
}
