/* Synthetic ABI/geometry checks; original guest pixels are tested separately. */
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "../call-border-pixmap-guest.c"

static const Rect target = {0, 0, 479, 149}, source = {0, 0, 7, 7};
static const Margins margins = {1, 10, 1, 1};
static int mode, draws;
static void original(void *p, const Rect *t, const Margins *tm, const void *pm,
                     const Rect *s, const Margins *sm, const void *rules, const void *hints)
{
    assert(p == (void *)1 && pm == (void *)2 && rules == (void *)3 && hints == (void *)4);
    assert(t == &target && tm == &margins && s == &source);
    /* Preserve 10 target rows, sampling only the 8 actual source rows. */
    assert(tm->top == 10 && sm->top == 8);
    assert(sm->left == 1 && sm->right == 1 && sm->bottom == 1);
    ++draws;
}
void *dlsym(void *handle, const char *name)
{
    assert(handle == (void *)-1 && strstr(name, "qDrawBorderPixmap"));
    return mode ? 0 : original;
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    mode = atoi(argv[1]);
    n00_draw_border((void *)1, &target, &margins, (void *)2, &source, &margins,
                    (void *)3, (void *)4);
    assert(draws == 1 && margins.top == 10);
    const Margins valid = {1, 8, 1, 1};
    n00_draw_border((void *)1, &target, &margins, (void *)2, &source, &valid,
                    (void *)3, (void *)4);
    assert(draws == 2);
    return 0;
}
