/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "../../../ports/qemu-n00/n00-lockscreen-control.h"
int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    if (!strcmp(argv[1], "ready")) printf("%d\n", n00_lockscreen_ready());
    else if (!strcmp(argv[1], "press")) printf("%d\n", n00_lockscreen_request());
    else return 2;
    return 0;
}
