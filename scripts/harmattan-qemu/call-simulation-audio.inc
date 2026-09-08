/* Synthetic ringtone output through original GStreamer 0.10; no microphone.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
extern void gst_init(int *, char ***);
extern const void *gst_message_get_structure(void *);
extern int gst_structure_has_name(const void *, const char *);
extern void gst_message_parse_error(void *, void **, char **);
extern void *gst_parse_launch(const char *, void **);
extern int gst_element_set_state(void *, int);
extern void *gst_element_get_bus(void *);
extern void *gst_bus_timed_pop_filtered(void *, unsigned long long, unsigned);
extern void gst_mini_object_unref(void *);
extern void gst_object_unref(void *);
static void *tone, *tone_bus;
static unsigned tone_id = 0;
static int audio_enabled;
static void tone_stop(void) {
    if (tone) {
        gst_element_set_state(tone, 1);
        gst_object_unref(tone_bus);
        gst_object_unref(tone);
        tone = tone_bus = 0;
        printf("DEMO_TONE stopped\n");
        fflush(0);
    }
}
static void tone_play(void) {
    tone_stop();
    if (!audio_enabled)
        return;
    void *e = 0;
    gst_init(0, 0);
    tone = gst_parse_launch("filesrc location=\"/usr/share/sounds/ring-tones/Nokia tune.mp3\" ! decodebin2 ! "
                            "audioconvert ! audioresample ! pulsesink",
                            &e);
    if (!tone || e) {
        printf("DEMO_TONE_ERROR parse\n");
        exit(1);
    }
    tone_bus = gst_element_get_bus(tone);
    if (!gst_element_set_state(tone, 4)) {
        printf("DEMO_TONE_ERROR start\n");
        exit(1);
    }
    printf("DEMO_TONE playing\n");
    fflush(0);
}
static void tone_poll(void) {
    if (!tone)
        return;
    void *m = gst_bus_timed_pop_filtered(tone_bus, 0, 3);
    if (m && gst_message_get_structure(m) &&
        gst_structure_has_name(gst_message_get_structure(m), "GstMessageError")) {
        struct {
            unsigned domain;
            int code;
            char *message;
        } *err = 0;
        char *debug = 0;
        gst_message_parse_error(m, (void **)&err, &debug);
        printf("DEMO_GST_ERROR %s %s\n", err ? err->message : "", debug ? debug : "");
        gst_mini_object_unref(m);
        printf("DEMO_TONE_ERROR stream\n");
        fflush(0);
        exit(1);
    }
    if (m) {
        gst_mini_object_unref(m);
        tone_play();
    }
}
