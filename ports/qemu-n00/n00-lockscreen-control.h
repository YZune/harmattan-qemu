/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef N00_LOCKSCREEN_CONTROL_H
#define N00_LOCKSCREEN_CONTROL_H
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* A private, per-run mailbox consumed by the existing guest controller.
 * Publish only complete requests, coalesce clicks until acknowledgement,
 * and do not accept presses until the original desktop passes its gates. */
static int n00_lockscreen_ready(void)
{
    const char *directory = getenv("N00_COCOA_LOCKSCREEN");
    char path[4096], data[7];
    if (!directory || snprintf(path, sizeof(path), "%s/ready", directory) >= (int)sizeof(path)) return 0;
    int fd = open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) return 0;
    ssize_t size = read(fd, data, sizeof(data));
    close(fd);
    return size == 6 && !memcmp(data, "ready\n", 6);
}

static int n00_lockscreen_request(void)
{
    if (!n00_lockscreen_ready()) return 0;
    const char *directory = getenv("N00_COCOA_LOCKSCREEN");
    char temporary[4096], request[4096];
    if (snprintf(temporary, sizeof(temporary), "%s/request.tmp", directory) >= (int)sizeof(temporary) ||
        snprintf(request, sizeof(request), "%s/request", directory) >= (int)sizeof(request)) return -1;
    int fd = open(temporary, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (fd < 0) return -1;
    ssize_t size = write(fd, "press\n", 6);
    int closed = close(fd);
    int result = -1;
    if (size == 6 && closed == 0) {
        result = link(temporary, request);
        if (result < 0 && errno == EEXIST) result = 0;
    }
    unlink(temporary);
    return result < 0 ? -1 : 1;
}
#endif
