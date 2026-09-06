/* Bounded playback via the guest's original PulseAudio/GStreamer libraries.
 * ABI declarations follow PulseAudio 0.9.19 and GStreamer 0.10 headers.
 * Only pointer/integer arguments cross the original ARMEL library ABI.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
typedef struct pa_simple pa_simple;
typedef struct { int format; unsigned rate; unsigned char channels; } pa_sample_spec;
extern pa_simple *pa_simple_new(const char *, const char *, int, const char *, const char *, const pa_sample_spec *, const void *, const void *, int *);
extern int pa_simple_write(pa_simple *, const void *, unsigned, int *);
extern int pa_simple_drain(pa_simple *, int *);
extern void pa_simple_free(pa_simple *);
extern void gst_init(int *, char ***);
extern void *gst_parse_launch(const char *, void **);
extern int gst_element_set_state(void *, int);
extern void *gst_element_get_bus(void *);
extern void *gst_bus_timed_pop_filtered(void *, unsigned long long, unsigned);
extern void gst_mini_object_unref(void *);
extern void gst_object_unref(void *);
extern int strcmp(const char *, const char *);
extern int printf(const char *, ...);
extern unsigned alarm(unsigned);
extern void *fopen(const char *, const char *);
extern unsigned fwrite(const void *, unsigned, unsigned, void *);
extern int fclose(void *);
extern int unlink(const char *);

static void fill(short *buffer, unsigned block)
{
    for (unsigned i = 0; i < 4410; i++) {
        unsigned phase = ((block * 4410 + i) * 440) % 44100;
        int sample = phase < 22050 ? (int)(phase * 8000 / 22050) - 4000 :
                                    12000 - (int)(phase * 8000 / 22050);
        buffer[2 * i] = buffer[2 * i + 1] = (short)sample;
    }
}

static int pulse(void)
{
    int error = 0;
    pa_sample_spec spec = {3, 44100, 2}; /* PA_SAMPLE_S16LE */
    short buffer[8820];
    pa_simple *stream = pa_simple_new(0, "Harmattan QEMU PCM test", 1, 0,
        "Original libpulse PCM", &spec, 0, 0, &error);
    if (!stream) { printf("N00_AUDIO_CONNECT_ERROR %d\n", error); return 1; }
    for (unsigned block = 0; block < 30; block++) {
        fill(buffer, block);
        if (pa_simple_write(stream, buffer, sizeof(buffer), &error) < 0) {
            printf("N00_AUDIO_WRITE_ERROR %d\n", error);
            pa_simple_free(stream);
            return 1;
        }
    }
    int result = pa_simple_drain(stream, &error);
    pa_simple_free(stream);
    if (result < 0) { printf("N00_AUDIO_DRAIN_ERROR %d\n", error); return 1; }
    printf("N00_AUDIO_PULSE_DRAINED frames=132300\n");
    return 0;
}

static int gstreamer(void)
{
    unsigned char header[] = {'R','I','F','F',0,0,0,0,'W','A','V','E',
        'f','m','t',' ',16,0,0,0,1,0,2,0,0x44,0xac,0,0,0x10,0xb1,2,0,
        4,0,16,0,'d','a','t','a',0,0,0,0};
    unsigned bytes = 132300 * 4;
    for (unsigned i = 0; i < 4; i++) {
        header[4 + i] = (bytes + 36) >> (8 * i);
        header[40 + i] = bytes >> (8 * i);
    }
    void *file = fopen("/tmp/n00-audio.wav", "wb");
    if (!file) return 1;
    if (fwrite(header, 1, sizeof(header), file) != sizeof(header)) return 1;
    short buffer[8820];
    for (unsigned block = 0; block < 30; block++) {
        fill(buffer, block);
        if (fwrite(buffer, 1, sizeof(buffer), file) != sizeof(buffer)) return 1;
    }
    if (fclose(file)) return 1;
    void *error = 0;
    gst_init(0, 0);
    void *pipeline = gst_parse_launch("filesrc location=/tmp/n00-audio.wav ! wavparse ! audioconvert ! audioresample ! pulsesink", &error);
    if (!pipeline || error) { printf("N00_AUDIO_GST_PARSE_ERROR\n"); return 1; }
    void *bus = gst_element_get_bus(pipeline);
    int started = gst_element_set_state(pipeline, 4); /* GST_STATE_PLAYING */
    void *eos = started ? gst_bus_timed_pop_filtered(bus, 15ULL * 1000000000ULL, 1) : 0;
    /* Only GST_MESSAGE_EOS is accepted. Error/no-output paths time out. */
    gst_element_set_state(pipeline, 1); /* GST_STATE_NULL */
    if (eos) gst_mini_object_unref(eos);
    gst_object_unref(bus);
    gst_object_unref(pipeline);
    unlink("/tmp/n00-audio.wav");
    if (!eos) { printf("N00_AUDIO_GST_NO_EOS\n"); return 1; }
    printf("N00_AUDIO_GSTREAMER_EOS\n");
    return 0;
}

int main(int argc, char **argv)
{
    alarm(25);
    if (argc == 2 && !strcmp(argv[1], "pulse")) return pulse();
    if (argc == 2 && !strcmp(argv[1], "gstreamer")) return gstreamer();
    printf("Usage: n00-audio-probe pulse|gstreamer\n");
    return 2;
}
