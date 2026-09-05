/* SPDX-License-Identifier: GPL-2.0-or-later
 * Process-local adaptation for the pinned PR1.3 libmcompositor.so.1.1.3.
 * Source: mcompositor 1.1.35, mtexturepixmapitem_p.cpp. Custom shader programs
 * omit matProj; the matWorld cache incorrectly spans multiple programs.
 * Keep the original shaders, transforms, easing and application binaries.
 * No Qt object layout is assumed: only verified exported functions/symbols.
 */
typedef unsigned int GLuint;
typedef int GLint;
extern void *dlsym(void *, const char *);
extern void glGetIntegerv(unsigned int, GLint *);
extern GLint glGetUniformLocation(GLuint, const char *);
extern void glUseProgram(GLuint);
extern void glUniformMatrix4fv(GLint, int, unsigned char, const float *);
extern int write(int, const void *, unsigned int);
extern void _exit(int);

static void fail(void)
{
    const char error[] = "N00_COMPOSITOR_MATRICES_ERROR unsupported ABI or viewport\n";
    write(2, error, sizeof(error) - 1);
    _exit(122);
}

_Bool _ZN16QGLShaderProgram4bindEv(void *self)
{
    typedef _Bool (*Bind)(void *);
    static Bind original;
    static unsigned char *init;
    if (!original) {
        original = (Bind)dlsym((void *)-1, "_ZN16QGLShaderProgram4bindEv");
        init = dlsym((void *)-1, "_ZZN14MShaderProgram14setWorldMatrixEPA4_fE4init");
        if (!original || !init) fail();
        const char marker[] = "N00_COMPOSITOR_WORLD_CACHE_ACTIVE\n";
        write(1, marker, sizeof(marker) - 1);
    }
    _Bool result = original(self);
    /* Let the original setter upload its actual transform, even if equal to
     * the preceding program's matrix. Do not inject an identity transform. */
    if (result) *init = 1;
    return result;
}

/* This is a STATIC C++ member: only QByteArray const&, no this argument. */
GLuint _ZN21MTexturePixmapPrivate18installPixelShaderERK10QByteArray(const void *code)
{
    typedef GLuint (*Install)(const void *);
    Install original = (Install)dlsym((void *)-1,
        "_ZN21MTexturePixmapPrivate18installPixelShaderERK10QByteArray");
    if (!original) fail();
    GLuint program = original(code);
    if (program) {
        GLint old = 0, viewport[4] = {0};
        glGetIntegerv(0x8b8d, &old); /* GL_CURRENT_PROGRAM */
        glGetIntegerv(0x0ba2, viewport); /* GL_VIEWPORT */
        GLint location = glGetUniformLocation(program, "matProj");
        if (location < 0 || viewport[0] || viewport[1] ||
            viewport[2] != 864 || viewport[3] != 480) fail();
        /* The same orthographic projection as original initVertices(),
         * derived from the actual viewport. Other viewports fail closed. */
        const float projection[16] = {
            2.0f / viewport[2], 0, 0, 0,
            0, -2.0f / viewport[3], 0, 0,
            0, 0, -1, 0, -1, 1, 0, 1
        };
        glUseProgram(program);
        glUniformMatrix4fv(location, 1, 0, projection);
        glUseProgram((GLuint)old);
        const char marker[] = "N00_COMPOSITOR_PROJECTION_APPLIED\n";
        write(1, marker, sizeof(marker) - 1);
    }
    return program;
}
