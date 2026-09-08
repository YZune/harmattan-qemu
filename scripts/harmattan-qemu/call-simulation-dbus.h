/* Integer/pointer ABI declarations for pinned guest D-Bus 1.4.6 and glibc.
 * DBusMessageIter layout follows dbus-message.h; fields remain opaque.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
typedef struct DBusConnection DBusConnection;
typedef struct DBusMessage DBusMessage;
typedef struct {
    void *p1, *p2;
    unsigned u;
    int pad[9];
    void *p3, *p4;
} Iter;
_Static_assert(sizeof(Iter) == 56, "Pinned ARM32 D-Bus iterator ABI required");
extern DBusConnection *dbus_bus_get(int, void *);
extern int dbus_bus_request_name(DBusConnection *, const char *, unsigned, void *);
extern int dbus_connection_read_write(DBusConnection *, int);
extern DBusMessage *dbus_connection_pop_message(DBusConnection *);
extern int dbus_connection_send(DBusConnection *, DBusMessage *, unsigned *);
extern void dbus_connection_flush(DBusConnection *);
extern const char *dbus_message_get_member(DBusMessage *);
extern const char *dbus_message_get_interface(DBusMessage *);
extern const char *dbus_message_get_path(DBusMessage *);
extern const char *dbus_message_get_signature(DBusMessage *);
extern const char *dbus_message_get_error_name(DBusMessage *);
extern int dbus_message_get_type(DBusMessage *);
extern DBusMessage *dbus_message_new_method_return(DBusMessage *);
extern DBusMessage *dbus_message_new_error(DBusMessage *, const char *, const char *);
extern DBusMessage *dbus_message_new_method_call(const char *, const char *, const char *, const char *);
extern DBusMessage *dbus_message_new_signal(const char *, const char *, const char *);
extern void dbus_message_unref(DBusMessage *);
extern int dbus_message_iter_init(DBusMessage *, Iter *);
extern void dbus_message_iter_init_append(DBusMessage *, Iter *);
extern int dbus_message_iter_next(Iter *);
extern int dbus_message_iter_get_arg_type(Iter *);
extern void dbus_message_iter_get_basic(Iter *, void *);
extern void dbus_message_iter_recurse(Iter *, Iter *);
extern int dbus_message_iter_append_basic(Iter *, int, const void *);
extern int dbus_message_iter_open_container(Iter *, int, const char *, Iter *);
extern int dbus_message_iter_close_container(Iter *, Iter *);
extern int printf(const char *, ...);
extern int fflush(void *);
extern int strcmp(const char *, const char *);
extern int snprintf(char *, unsigned, const char *, ...);
extern void exit(int);
extern unsigned dbus_message_get_reply_serial(DBusMessage *);
extern int getuid(void);
extern const char *getenv(const char *);
