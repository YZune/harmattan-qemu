/* Read-only original Notes evidence; no UI hooks or database writes.
 * SPDX-License-Identifier: GPL-2.0-or-later */
typedef struct sqlite3 sqlite3;
extern int sqlite3_open_v2(const char *, sqlite3 **, int, const char *);
extern int sqlite3_exec(sqlite3 *, const char *, int (*)(void *, int, char **, char **), void *, char **);
extern int sqlite3_close(sqlite3 *);
extern int printf(const char *, ...);

static int note(void *data, int count, char **values, char **names)
{
    (void)names;
    if (count != 1 || !values[0]) return 1;
    (*(unsigned *)data)++;
    printf("N00_NOTES_TEXT_HEX %s\n", values[0]);
    return 0;
}

int main(void)
{
    sqlite3 *db = 0;
    unsigned count = 0;
    if (sqlite3_open_v2("/home/user/.calendar/db", &db, 1, 0)) return 1;
    int result = sqlite3_exec(db,
        "SELECT hex(Description) FROM Components WHERE Type='Journal' AND DateDeleted=0 ORDER BY ComponentId",
        note, &count, 0);
    if (sqlite3_close(db) || result) return 2;
    printf("N00_NOTES_COUNT %u\n", count);
    return 0;
}
