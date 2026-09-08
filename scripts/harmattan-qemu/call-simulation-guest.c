/* Explicit synthetic Telepathy calls on a private bus. The pinned original
 * call-ui renders and handles the interaction. Ring names exist ONLY on this
 * isolated bus to select its cellular presentation; no SIM, modem or real call.
 * Contracts: Telepathy StreamedMedia/Group (0.17 era), original MNGF Play/Stop.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "call-simulation-dbus.h"

#define TP "org.freedesktop.Telepathy"
#define CH TP ".Channel"
#define CO TP ".Connection"
#define GR CH ".Interface.Group"
#define SM CH ".Type.StreamedMedia"
#define AC TP ".Account"
#define AM TP ".AccountManager"
#define CN CO ".ring.tel.ring"
#define CP "/org/freedesktop/Telepathy/Connection/ring/tel/ring"
#define AP "/org/freedesktop/Telepathy/Account/ring/tel/ring"
#define AMP "/org/freedesktop/Telepathy/AccountManager"
#define DEMO "org.harmattan.CallSimulation"
#define HOLD CH ".Interface.Hold"
#include "call-simulation-audio.inc"
static DBusConnection *bus;
static char channel[180] = CP "/call1";
static unsigned seq = 0, state = 0, handled_serial = 0, held = 0; /* idle, incoming, active, ended */
static const char *caller = "N9 simulation";
static void ck(int ok) {
    if (!ok) {
        printf("DEMO_FATAL allocation\n");
        fflush(0);
        exit(1);
    }
}
static void basic(Iter *i, int t, const void *p) { ck(dbus_message_iter_append_basic(i, t, p)); }
static void str(Iter *i, int t, const char *s) { basic(i, t, &s); }
static void num(Iter *i, unsigned u) { basic(i, 'u', &u); }
static void open(Iter *i, int t, const char *sig, Iter *o) {
    ck(dbus_message_iter_open_container(i, t, sig, o));
}
static void close(Iter *i, Iter *o) { ck(dbus_message_iter_close_container(i, o)); }
static void array(Iter *i, const char *sig) {
    Iter a;
    open(i, 'a', sig, &a);
    close(i, &a);
}
static void strings(Iter *i, const char **v) {
    Iter a;
    open(i, 'a', "s", &a);
    while (*v)
        str(&a, 's', *v++);
    close(i, &a);
}
static const char *empty[] = {0};
static const char *chifs[] = {GR, HOLD, 0};
static const char *coifs[] = {CO ".Interface.Aliasing", 0};
static void handles(Iter *i, unsigned bits) {
    Iter a;
    open(i, 'a', "u", &a);
    for (unsigned n = 1; n <= 2; n++)
        if (bits & (1u << n))
            num(&a, n);
    close(i, &a);
}
static void prop(Iter *i, const char *key, const char *sig, const void *p) {
    Iter e, v;
    open(i, 'e', 0, &e);
    str(&e, 's', key);
    open(&e, 'v', sig, &v);
    if (sig[0] == 'a') {
        if (sig[1] == 's')
            strings(&v, (const char **)p);
        else if (sig[1] == 'u')
            handles(&v, *(unsigned *)p);
        else {
            Iter a;
            open(&v, 'a', sig + 1, &a);
            if (sig[1] == 'o' && p)
                str(&a, 'o', p);
            close(&v, &a);
        }
    } else
        basic(&v, sig[0], p);
    close(&e, &v);
    close(i, &e);
}
static void ps(Iter *i, const char *k, const char *s) { prop(i, k, "s", &s); }
static void po(Iter *i, const char *k, const char *s) { prop(i, k, "o", &s); }
static void pu(Iter *i, const char *k, unsigned n) { prop(i, k, "u", &n); }
static void pb(Iter *i, const char *k, unsigned n) { prop(i, k, "b", &n); }
static void presence(Iter *i, const char *k) {
    Iter e, v, s;
    open(i, 'e', 0, &e);
    str(&e, 's', k);
    open(&e, 'v', "(uss)", &v);
    open(&v, 'r', 0, &s);
    num(&s, 2);
    str(&s, 's', "available");
    str(&s, 's', "Simulation only");
    close(&v, &s);
    close(&e, &v);
    close(i, &e);
}
static void immutable(Iter *a, int qualified) {
    const char *prefix = qualified ? CH "." : "";
    char k[200];
#define K(s) (snprintf(k, sizeof(k), "%s%s", prefix, s), k)
    ps(a, K("ChannelType"), SM);
    pu(a, K("TargetHandleType"), 1);
    pu(a, K("TargetHandle"), 2);
    ps(a, K("TargetID"), caller);
    pu(a, K("InitiatorHandle"), 2);
    ps(a, K("InitiatorID"), caller);
    pb(a, K("Requested"), 0);
    prop(a, K("Interfaces"), "as", chifs);
#undef K
    if (qualified) {
        pb(a, SM ".InitialAudio", 1);
        pb(a, SM ".InitialVideo", 0);
        pb(a, SM ".ImmutableStreams", 1);
    }
}
static int properties(Iter *a, const char *iface) {
    if (!strcmp(iface, AM)) {
        prop(a, "Interfaces", "as", empty);
        prop(a, "ValidAccounts", "ao", AP);
        prop(a, "InvalidAccounts", "ao", 0);
    } else if (!strcmp(iface, AC)) {
        prop(a, "Interfaces", "as", empty);
        ps(a, "DisplayName", "N9 simulated call");
        ps(a, "Nickname", "N9 simulation");
        ps(a, "Icon", "general_call");
        ps(a, "NormalizedName", "simulation");
        ps(a, "Service", "n00demo");
        pb(a, "Valid", 1);
        pb(a, "Enabled", 1);
        pb(a, "ConnectAutomatically", 0);
        pb(a, "HasBeenOnline", 1);
        pb(a, "ChangingPresence", 0);
        po(a, "Connection", CP);
        pu(a, "ConnectionStatus", 0);
        pu(a, "ConnectionStatusReason", 0);
        ps(a, "ConnectionError", "");
        prop(a, "Parameters", "a{sv}", 0);
        prop(a, "ConnectionErrorDetails", "a{sv}", 0);
        presence(a, "CurrentPresence");
        presence(a, "RequestedPresence");
        presence(a, "AutomaticPresence");
    } else if (!strcmp(iface, CO)) {
        prop(a, "Interfaces", "as", coifs);
        pu(a, "Status", 0);
        pu(a, "SelfHandle", 1);
        pb(a, "HasImmortalHandles", 1);
    } else if (!strcmp(iface, CH))
        immutable(a, 0);
    else if (!strcmp(iface, SM)) {
        pb(a, "InitialAudio", 1);
        pb(a, "InitialVideo", 0);
        pb(a, "ImmutableStreams", 1);
    } else if (!strcmp(iface, GR)) {
        pu(a, "GroupFlags", 2048 | 1 | 2 | 4);
        pu(a, "SelfHandle", 1);
        unsigned members = state == 1 ? 4 : state == 2 ? 6 : 0, pending = state == 1 ? 2 : 0;
        prop(a, "Members", "au", &members);
        prop(a, "RemotePendingMembers", "au", &(unsigned){0});
        prop(a, "HandleOwners", "a{uu}", 0);
        Iter e, v, ar, s;
        open(a, 'e', 0, &e);
        str(&e, 's', "LocalPendingMembers");
        open(&e, 'v', "a(uuus)", &v);
        open(&v, 'a', "(uuus)", &ar);
        if (pending) {
            open(&ar, 'r', 0, &s);
            num(&s, 1);
            num(&s, 2);
            num(&s, 0);
            str(&s, 's', "");
            close(&ar, &s);
        }
        close(&v, &ar);
        close(&e, &v);
        close(a, &e);
    } else
        return 0;
    return 1;
}
static unsigned send(DBusMessage *m) {
    unsigned serial = 0;
    ck(m != 0);
    ck(dbus_connection_send(bus, m, &serial));
    dbus_message_unref(m);
    dbus_connection_flush(bus);
    return serial;
}
static void error(DBusMessage *m, const char *name, const char *why) {
    send(dbus_message_new_error(m, name, why));
}
static void members(unsigned added, unsigned removed, unsigned pending, unsigned actor, unsigned reason) {
    DBusMessage *m = dbus_message_new_signal(channel, GR, "MembersChanged");
    Iter i;
    dbus_message_iter_init_append(m, &i);
    str(&i, 's', "");
    handles(&i, added);
    handles(&i, removed);
    handles(&i, pending);
    handles(&i, 0);
    num(&i, actor);
    num(&i, reason);
    send(m);
}
static void streams(Iter *i) {
    Iter a, s;
    open(i, 'a', "(uuuuuu)", &a);
    if (state == 1 || state == 2) {
        open(&a, 'r', 0, &s);
        num(&s, 1);
        num(&s, 2);
        num(&s, 0);
        num(&s, state == 2 ? 2 : 1);
        num(&s, state == 2 ? 3 : 2);
        num(&s, state == 1 ? 1 : 0);
        close(&a, &s);
    }
    close(i, &a);
}
extern DBusMessage *dbus_connection_send_with_reply_and_block(DBusConnection *, DBusMessage *, int, void *);
static int lock_ui(const char *method) {
    const char *enabled = getenv("N00_CALL_LOCKSCREEN");
    if (!enabled || strcmp(enabled, "on")) return 1;
    DBusMessage *m = dbus_message_new_method_call("org.harmattan.CallSimulation.LockUi",
        "/org/harmattan/CallSimulation/LockUi", "org.harmattan.CallSimulation.LockUi", method);
    DBusMessage *r = dbus_connection_send_with_reply_and_block(bus, m, 15000, 0);
    dbus_message_unref(m);
    int ok = r && dbus_message_get_type(r) == 2 && !*dbus_message_get_signature(r);
    if (r) dbus_message_unref(r);
    if (!ok) { printf("DEMO_FATAL lock bridge %s\n", method); fflush(0); }
    return ok;
}
static void finish(unsigned actor, const char *why) {
    if (state != 1 && state != 2)
        return;
    tone_stop();
    members(0, 6, 0, actor, 0);
    state = 3;
    send(dbus_message_new_signal(channel, CH, "Closed"));
    if (!lock_ui("Finish")) exit(2);
    printf("DEMO_STATE ended cause=%s sequence=%u\n", why, seq);
    fflush(0);
}
static void incoming(void) {
    held = 0;
    seq++;
    snprintf(channel, sizeof(channel), CP "/call%u", seq);
    state = 1;
    DBusMessage *m =
        dbus_message_new_method_call(TP ".Client.CallUi", "/org/freedesktop/Telepathy/Client/CallUi",
                                     TP ".Client.Handler", "HandleChannels");
    Iter i, a, s, p;
    dbus_message_iter_init_append(m, &i);
    str(&i, 'o', AP);
    str(&i, 'o', CP);
    open(&i, 'a', "(oa{sv})", &a);
    open(&a, 'r', 0, &s);
    str(&s, 'o', channel);
    open(&s, 'a', "{sv}", &p);
    immutable(&p, 1);
    close(&s, &p);
    close(&a, &s);
    close(&i, &a);
    array(&i, "o");
    unsigned long long timestamp = 0;
    basic(&i, 't', &timestamp);
    array(&i, "{sv}");
    handled_serial = send(m);
    printf("DEMO_STATE incoming sequence=%u\n", seq);
    fflush(0);
}
static void process(DBusMessage *m) {
    const char *method = dbus_message_get_member(m), *iface = dbus_message_get_interface(m),
               *path = dbus_message_get_path(m);
    if (dbus_message_get_type(m) != 1) {
        if (handled_serial && dbus_message_get_reply_serial(m) == handled_serial) {
            handled_serial = 0;
            if (dbus_message_get_type(m) == 3) {
                printf("DEMO_REMOTE_ERROR %s\n", dbus_message_get_error_name(m));
                finish(2, "handler-failed");
            } else
                printf("DEMO_UI_HANDLED sequence=%u\n", seq);
        }
        fflush(0);
        return;
    }
    if (!method || !iface || !path)
        return;
    if (!strcmp(iface, DEMO)) {
        if (strcmp(path, "/org/harmattan/CallSimulation")) {
            error(m, "org.freedesktop.DBus.Error.UnknownObject", "Unknown control object");
            return;
        }
    } else if (!strcmp(iface, "com.nokia.NonGraphicFeedback1")) {
        if (strcmp(path, "/com/nokia/NonGraphicFeedback1")) {
            error(m, "org.freedesktop.DBus.Error.UnknownObject", "Unknown feedback object");
            return;
        }
    } else if (strcmp(path, AMP) && strcmp(path, AP) && strcmp(path, CP) && strcmp(path, channel)) {
        error(m, "org.freedesktop.DBus.Error.UnknownObject", "Unknown or stale simulation object");
        return;
    }
    const char *sig = dbus_message_get_signature(m), *expected = "";
    if (!strcmp(method, "GetAll"))
        expected = "s";
    else if (!strcmp(method, "InspectHandles") || !strcmp(method, "HoldHandles") ||
             !strcmp(method, "ReleaseHandles"))
        expected = "uau";
    else if (!strcmp(method, "GetAliases") || !strcmp(method, "RequestAliases"))
        expected = "au";
    else if (!strcmp(method, "AddMembers") || !strcmp(method, "RemoveMembers"))
        expected = "aus";
    else if (!strcmp(method, "RemoveMembersWithReason"))
        expected = "ausu";
    else if (!strcmp(method, "Play"))
        expected = "sa{sv}";
    else if (!strcmp(method, "Stop"))
        expected = "u";
    else if (!strcmp(method, "Pause"))
        expected = "ub";
    else if (!strcmp(method, "RequestHold"))
        expected = "b";
    else if (!strcmp(method, "RequestStreamDirection"))
        expected = "uu";
    if (strcmp(sig, expected)) {
        error(m, "org.freedesktop.DBus.Error.InvalidArgs", "Unexpected simulation method signature");
        return;
    }
    if (!strcmp(iface, GR) && (!strcmp(method, "AddMembers") || !strcmp(method, "RemoveMembers") ||
                               !strcmp(method, "RemoveMembersWithReason"))) {
        Iter a, h;
        unsigned self = 0;
        dbus_message_iter_init(m, &a);
        dbus_message_iter_recurse(&a, &h);
        if (dbus_message_iter_get_arg_type(&h) == 'u')
            dbus_message_iter_get_basic(&h, &self);
        if (self != 1 || dbus_message_iter_next(&h)) {
            error(m, TP ".Error.InvalidArgument", "Only the simulated local participant may be changed");
            return;
        }
    }
    printf("DEMO_REQUEST %s %s %s %s\n", path, iface, method, dbus_message_get_signature(m));
    fflush(0);
    DBusMessage *r = dbus_message_new_method_return(m);
    Iter out, in;
    dbus_message_iter_init_append(r, &out);
    dbus_message_iter_init(m, &in);
    for (Iter args = in; dbus_message_iter_get_arg_type(&args); dbus_message_iter_next(&args)) {
        int t = dbus_message_iter_get_arg_type(&args);
        if (t == 's' || t == 'o') {
            const char *v;
            dbus_message_iter_get_basic(&args, &v);
            printf("DEMO_ARG %s\n", v);
        }
        if (t == 'u') {
            unsigned v;
            dbus_message_iter_get_basic(&args, &v);
            printf("DEMO_ARG %u\n", v);
        }
    }
    fflush(0);

    if (!strcmp(iface, "org.freedesktop.DBus.Properties") && !strcmp(method, "GetAll")) {
        const char *name = "";
        if (dbus_message_iter_get_arg_type(&in) == 's')
            dbus_message_iter_get_basic(&in, &name);
        Iter a;
        open(&out, 'a', "{sv}", &a);
        int ok = properties(&a, name);
        close(&out, &a);
        if (!ok) {
            dbus_message_unref(r);
            error(m, "org.freedesktop.DBus.Error.UnknownInterface", name);
            return;
        }
    } else if (!strcmp(iface, DEMO)) {
        if (!strcmp(method, "Incoming")) {
            if (state == 1 || state == 2) {
                dbus_message_unref(r);
                error(m, TP ".Error.NotAvailable", "A simulated call is already open");
                return;
            }
            if (!lock_ui("Begin")) {
                dbus_message_unref(r);
                error(m, "org.freedesktop.DBus.Error.Failed", "Original lock UI bridge failed");
                return;
            }
            send(r);
            incoming();
            return;
        } else if (!strcmp(method, "End")) {
            finish(2, "remote-ended");
        } else if (!strcmp(method, "Status")) {
            num(&out, state);
            num(&out, seq);
            num(&out, tone != 0);
        } else {
            dbus_message_unref(r);
            error(m, "org.freedesktop.DBus.Error.UnknownMethod", method);
            return;
        }
    } else if (!strcmp(iface, "com.nokia.NonGraphicFeedback1") && !strcmp(method, "Play")) {
        const char *event = "";
        dbus_message_iter_get_basic(&in, &event);
        if (strcmp(event, "ringtone") || state != 1) {
            dbus_message_unref(r);
            error(m, TP ".Error.NotAvailable", "Only simulated incoming ringtone is available");
            return;
        }
        tone_play();
        tone_id++;
        num(&out, tone_id);
        printf("DEMO_TONE_REQUEST sequence=%u\n", seq);
        fflush(0);
    } else if (!strcmp(iface, "com.nokia.NonGraphicFeedback1") &&
               (!strcmp(method, "Stop") || !strcmp(method, "Pause"))) {
        unsigned id = 0;
        dbus_message_iter_get_basic(&in, &id);
        if (id != tone_id) {
            dbus_message_unref(r);
            error(m, TP ".Error.InvalidArgument", "Unknown ringtone event");
            return;
        }
        unsigned paused = 1;
        if (!strcmp(method, "Pause")) {
            dbus_message_iter_next(&in);
            dbus_message_iter_get_basic(&in, &paused);
        }
        if (paused)
            tone_stop();
        else if (state == 1)
            tone_play();
    } else if (!strcmp(iface, CO) && !strcmp(method, "GetInterfaces"))
        strings(&out, coifs);
    else if (!strcmp(iface, CO) && !strcmp(method, "GetStatus"))
        num(&out, 0);
    else if (!strcmp(iface, CO) && !strcmp(method, "GetSelfHandle"))
        num(&out, 1);
    else if (!strcmp(iface, CO) && (!strcmp(method, "HoldHandles") || !strcmp(method, "ReleaseHandles"))) {
    } else if (!strcmp(iface, CO) && !strcmp(method, "InspectHandles")) {
        Iter h, a;
        dbus_message_iter_next(&in);
        dbus_message_iter_recurse(&in, &h);
        open(&out, 'a', "s", &a);
        while (dbus_message_iter_get_arg_type(&h) == 'u') {
            unsigned n;
            dbus_message_iter_get_basic(&h, &n);
            str(&a, 's', n == 1 ? "simulation" : caller);
            dbus_message_iter_next(&h);
        }
        close(&out, &a);
    } else if (!strcmp(iface, CO ".Interface.Aliasing") && !strcmp(method, "GetAliasFlags"))
        num(&out, 0);
    else if (!strcmp(iface, CO ".Interface.Aliasing") &&
             (!strcmp(method, "RequestAliases") || !strcmp(method, "GetAliases"))) {
        Iter h, a;
        int map = !strcmp(method, "GetAliases");
        dbus_message_iter_recurse(&in, &h);
        open(&out, 'a', map ? "{us}" : "s", &a);
        while (dbus_message_iter_get_arg_type(&h) == 'u') {
            unsigned n;
            dbus_message_iter_get_basic(&h, &n);
            const char *v = n == 1 ? "Simulation" : caller;
            if (map) {
                Iter e;
                open(&a, 'e', 0, &e);
                num(&e, n);
                str(&e, 's', v);
                close(&a, &e);
            } else
                str(&a, 's', v);
            dbus_message_iter_next(&h);
        }
        close(&out, &a);
    } else if (!strcmp(iface, CH) && !strcmp(method, "GetInterfaces"))
        strings(&out, chifs);
    else if (!strcmp(iface, CH) && !strcmp(method, "GetChannelType"))
        str(&out, 's', SM);
    else if (!strcmp(iface, CH) && !strcmp(method, "GetHandle")) {
        num(&out, 1);
        num(&out, 2);
    } else if (!strcmp(iface, CH) && !strcmp(method, "Close")) {
        finish(1, state == 1 ? "rejected" : "local-ended");
    } else if (!strcmp(iface, SM) && !strcmp(method, "ListStreams"))
        streams(&out);
    else if (!strcmp(iface, GR) && !strcmp(method, "GetSelfHandle"))
        num(&out, 1);
    else if (!strcmp(iface, GR) && !strcmp(method, "GetGroupFlags"))
        num(&out, 2055);
    else if (!strcmp(iface, GR) && !strcmp(method, "GetAllMembers")) {
        handles(&out, state == 1 ? 4 : 6);
        handles(&out, state == 1 ? 2 : 0);
        handles(&out, 0);
    } else if (!strcmp(iface, GR) && !strcmp(method, "AddMembers")) {
        if (state != 1) {
            dbus_message_unref(r);
            error(m, TP ".Error.NotAvailable", "No pending simulated call");
            return;
        }
        tone_stop();
        state = 2;
        members(2, 0, 0, 1, 0);
        DBusMessage *s = dbus_message_new_signal(channel, SM, "StreamStateChanged");
        Iter i;
        dbus_message_iter_init_append(s, &i);
        num(&i, 1);
        num(&i, 2);
        send(s);
        s = dbus_message_new_signal(channel, SM, "StreamDirectionChanged");
        dbus_message_iter_init_append(s, &i);
        num(&i, 1);
        num(&i, 3);
        num(&i, 0);
        send(s);
        printf("DEMO_STATE active sequence=%u\n", seq);
        fflush(0);
    } else if (!strcmp(iface, GR) &&
               (!strcmp(method, "RemoveMembersWithReason") || !strcmp(method, "RemoveMembers")))
        finish(1, state == 1 ? "rejected" : "local-ended");
    else if (!strcmp(iface, HOLD) && !strcmp(method, "GetHoldState")) {
        num(&out, held);
        num(&out, 0);
    } else if (!strcmp(iface, HOLD) && !strcmp(method, "RequestHold")) {
        if (state != 2) {
            dbus_message_unref(r);
            error(m, TP ".Error.NotAvailable", "No active simulated call");
            return;
        }
        dbus_message_iter_get_basic(&in, &held);
        DBusMessage *event = dbus_message_new_signal(channel, HOLD, "HoldStateChanged");
        Iter e;
        dbus_message_iter_init_append(event, &e);
        num(&e, held);
        num(&e, 1);
        send(event);
    } else if (!strcmp(iface, SM) && !strcmp(method, "RequestStreamDirection")) {
    } else {
        dbus_message_unref(r);
        error(m, "org.freedesktop.DBus.Error.UnknownMethod", method);
        return;
    }
    send(r);
}
int main(int argc, char **argv) {
    const char *address = getenv("DBUS_SESSION_BUS_ADDRESS");
    if (getuid() != 29999 || !address || strcmp(address, "unix:path=/tmp/n00-call-simulation/bus") ||
        argc != 2 || (strcmp(argv[1], "off") && strcmp(argv[1], "pulse"))) {
        printf("Requires the isolated guest call-simulation launcher and off|pulse.\n");
        return 2;
    }
    audio_enabled = !strcmp(argv[1], "pulse");
    bus = dbus_bus_get(0, 0);
    if (!bus)
        return 1;
    const char *names[] = {AM, CN, DEMO, "com.nokia.NonGraphicFeedback1", 0};
    for (int n = 0; names[n]; n++)
        if (dbus_bus_request_name(bus, names[n], 4, 0) != 1) {
            printf("DEMO_FATAL bus-name-unavailable %s\n", names[n]);
            return 1;
        }
    printf("DEMO_READY synthetic calls only; no modem, SIM or media\n");
    fflush(0);
    while (dbus_connection_read_write(bus, 100)) {
        tone_poll();
        DBusMessage *m;
        while ((m = dbus_connection_pop_message(bus))) {
            process(m);
            dbus_message_unref(m);
        }
    }
    return 0;
}
