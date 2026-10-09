/* GPL-2.0-or-later. Test-only glibc interposer; never loaded in normal runs.
 * Emit a marker after QEMU's main returns, before libc starts atexit handlers.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <unistd.h>

typedef int (*MainFunction)(int, char **, char **);
typedef int (*StartFunction)(MainFunction, int, char **, void (*)(void),
                             void (*)(void), void (*)(void), void *);
static MainFunction original_main;

static int marked_main(int argc, char **argv, char **envp)
{
    int result = original_main(argc, argv, envp);
    static const char marker[] = "QEMU_MAIN_RETURN_BEFORE_ATEXIT\n";
    if (write(STDERR_FILENO, marker, sizeof(marker) - 1) != sizeof(marker) - 1)
        _exit(125);
    return result;
}

int __libc_start_main(MainFunction main_function, int argc, char **argv,
                      void (*init)(void), void (*fini)(void),
                      void (*rtld_fini)(void), void *stack_end)
{
    StartFunction start = (StartFunction)dlsym(RTLD_NEXT, "__libc_start_main");
    if (!start) _exit(125);
    original_main = main_function;
    return start(marked_main, argc, argv, init, fini, rtld_fini, stack_end);
}
