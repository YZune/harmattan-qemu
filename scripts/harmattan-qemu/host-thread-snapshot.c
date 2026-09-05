/* Read-only macOS thread counters for a single explicitly selected process. */
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <libproc.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/proc_info.h>
#include <time.h>

static void string_json(const char *text, size_t max)
{
    putchar('"');
    for (size_t i = 0; i < max && text[i]; i++) {
        unsigned char ch = (unsigned char)text[i];
        if (ch == '"' || ch == '\\') {
            putchar('\\'); putchar(ch);
        } else if (ch < 32 || ch >= 127) {
            printf("\\u%04x", ch);
        } else {
            putchar(ch);
        }
    }
    putchar('"');
}

int main(int argc, char **argv)
{
    char *end;
    if (argc != 3) {
        fprintf(stderr, "Usage: %s PID EXPECTED_EXECUTABLE\n", argv[0]);
        return 2;
    }
    errno = 0;
    long value = strtol(argv[1], &end, 10);
    if (errno || *end || value <= 1 || value > INT_MAX) {
        fprintf(stderr, "Invalid PID\n"); return 2;
    }
    int pid = (int)value;
    char actual[PROC_PIDPATHINFO_MAXSIZE] = {0};
    if (proc_pidpath(pid, actual, sizeof(actual)) <= 0 || strcmp(actual, argv[2])) {
        fprintf(stderr, "Executable identity mismatch or process unavailable\n"); return 1;
    }
    uint64_t ids[1024];
    struct proc_threadinfo infos[1024];
    struct timespec before, after;
    clock_gettime(CLOCK_MONOTONIC, &before);
    int bytes = proc_pidinfo(pid, PROC_PIDLISTTHREADS, 0, ids, sizeof(ids));
    if (bytes <= 0 || bytes >= (int)sizeof(ids) || bytes % sizeof(ids[0])) {
        fprintf(stderr, "Invalid or oversized thread list\n"); return 1;
    }
    int count = bytes / sizeof(ids[0]);
    for (int i = 0; i < count; i++) {
        if (proc_pidinfo(pid, PROC_PIDTHREADINFO, ids[i], &infos[i], sizeof(infos[i])) != sizeof(infos[i])) {
            fprintf(stderr, "Thread disappeared or cannot be read\n"); return 1;
        }
    }
    clock_gettime(CLOCK_MONOTONIC, &after);
    printf("{\"pid\":%d,\"posix_before_ns\":%" PRIu64 ",\"posix_after_ns\":%" PRIu64 ",\"threads\":[", pid,
           (uint64_t)before.tv_sec * 1000000000 + before.tv_nsec,
           (uint64_t)after.tv_sec * 1000000000 + after.tv_nsec);
    for (int i = 0; i < count; i++) {
        struct proc_threadinfo *t = &infos[i];
        /* XNU fill_taskthreadinfo reports nanoseconds (microsecond precision). */
        printf("%s{\"thread_handle\":%" PRIu64 ",\"user_time_ns\":%" PRIu64 ",\"system_time_ns\":%" PRIu64
               ",\"priority\":%d,\"current_priority\":%d,\"name\":", i ? "," : "", ids[i],
               t->pth_user_time, t->pth_system_time, t->pth_priority, t->pth_curpri);
        string_json(t->pth_name, sizeof(t->pth_name));
        putchar('}');
    }
    puts("]}");
    return 0;
}
