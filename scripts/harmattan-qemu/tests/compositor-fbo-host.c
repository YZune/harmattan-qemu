/* Synthetic callsite/ABI checks of the actual guest shim; no guest/UI claim. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../compositor-fbo-guest.c"

static unsigned code[64];
static int mode, calls;
static unsigned observed_target, observed_name;
static void forward(unsigned target, unsigned name)
{
    calls++;
    observed_target = target;
    observed_name = name;
}
void *dlsym(void *scope, const char *name)
{
    assert(scope == (void *)-1);
    if (!strcmp(name, "glBindFramebuffer")) {
        return mode == 3 ? NULL : mode == 7 ? glBindFramebuffer : forward;
    }
    assert(!strcmp(name, "_ZN21MCompositeWindowGroup4initEv"));
    if (mode == 4) return NULL;
    return (unsigned char *)code + (mode == 5);
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    mode = atoi(argv[1]);
    unsigned char *bytes = (unsigned char *)code;
    const unsigned char entry[] = {0xf0, 0x49, 0x2d, 0xe9, 0x02, 0x8b, 0x2d, 0xed};
    const unsigned char site[] = {0x41, 0x0d, 0x08, 0xe3, 0x08, 0x10, 0x95, 0xe5,
                                 0x34, 0x70, 0x4b, 0xe2, 0x04, 0xf0, 0xff, 0xeb};
    memcpy(bytes, entry, sizeof(entry));
    memcpy(bytes + 0x64, site, sizeof(site));
    if (mode == 1) bytes[0] ^= 1;
    if (mode == 2) bytes[0x64] ^= 1;
    if (mode == 6) bytes[0x70] ^= 1;
    /* The corrected target and every bit of the guest object name survive. */
    bind_from(0x8d41, 0xffffffff, bytes + 0x74);
    assert(calls == 1 && observed_target == 0x8d40 && observed_name == 0xffffffff);
    bind_from(0x8d41, 7, bytes + 0x74);
    assert(calls == 2 && observed_target == 0x8d40 && observed_name == 7);
    /* Nearby/different callers and unrelated invalid targets remain untouched. */
    bind_from(0x8d41, 8, bytes + 0x70);
    assert(calls == 3 && observed_target == 0x8d41 && observed_name == 8);
    bind_from(0x8d41, 9, bytes + 0x78);
    assert(calls == 4 && observed_target == 0x8d41 && observed_name == 9);
    bind_from(0xdead, 10, bytes + 0x74);
    assert(calls == 5 && observed_target == 0xdead && observed_name == 10);
    bind_from(0x8d40, 11, bytes + 0x74);
    assert(calls == 6 && observed_target == 0x8d40 && observed_name == 11);
    glBindFramebuffer(0x8d41, 12);
    assert(calls == 7 && observed_target == 0x8d41 && observed_name == 12);
    puts("PASS");
    return 0;
}
