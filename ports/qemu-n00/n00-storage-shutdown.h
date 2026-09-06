/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef N00_STORAGE_SHUTDOWN_H
#define N00_STORAGE_SHUTDOWN_H
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

/* The owning controller syncs the guest and then requests QMP quit. */
static int n00_storage_shutdown_request(void)
{
    const char *path = getenv("N00_COCOA_STORAGE_SHUTDOWN");
    if (!path || !*path) {
        return 0;
    }
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (fd < 0) {
        perror("Cannot request guest filesystem sync");
        return -1;
    }
    ssize_t written = write(fd, "sync\n", 5);
    int closed = close(fd);
    if (written != 5 || closed != 0) {
        perror("Cannot finish guest filesystem sync request");
        return -1;
    }
    return 1;
}
#endif
