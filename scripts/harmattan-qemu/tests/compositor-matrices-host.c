/* Synthetic ABI/control-flow test; not guest/GPU or visual acceptance. */
#include <assert.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

extern _Bool _ZN16QGLShaderProgram4bindEv(void *);
extern unsigned _ZN21MTexturePixmapPrivate18installPixelShaderERK10QByteArray(const void *);
static unsigned char initialized;
static int mode, current = 77, binds, uniforms, installs;
static const int token = 1;
static _Bool original_bind(void *self) { assert(self == &token); return mode != 1; }
static unsigned original_install(const void *code) {
    assert(code == &token); ++installs; return mode == 2 ? 0 : 88;
}
void *dlsym(void *handle, const char *name) {
    assert(handle == (void *)-1);
    if (mode == 6) return 0;
    if (!strcmp(name, "_ZN16QGLShaderProgram4bindEv")) return original_bind;
    if (!strcmp(name, "_ZZN14MShaderProgram14setWorldMatrixEPA4_fE4init")) return &initialized;
    if (!strcmp(name, "_ZN21MTexturePixmapPrivate18installPixelShaderERK10QByteArray")) return original_install;
    assert(0); return 0;
}
void glGetIntegerv(unsigned name, int *values) {
    if (name == 0x8b8d) *values = current;
    else { assert(name == 0x0ba2); values[0] = mode == 5; values[1] = 0; values[2] = mode == 3 ? 480 : 864; values[3] = 480; }
}
int glGetUniformLocation(unsigned program, const char *name) {
    assert(program == 88 && !strcmp(name, "matProj")); return mode == 4 ? -1 : 5;
}
void glUseProgram(unsigned program) {
    assert(program == (binds == 0 ? 88u : 77u)); current = program; ++binds;
}
void glUniformMatrix4fv(int location, int count, unsigned char transpose, const float *value) {
    assert(current == 88 && location == 5 && count == 1 && !transpose);
    float expected[16] = {2.0f/864,0,0,0, 0,-2.0f/480,0,0, 0,0,-1,0, -1,1,0,1};
    for (int i = 0; i < 16; ++i) assert(fabsf(expected[i] - value[i]) < 0.000001f);
    ++uniforms;
}
int write(int fd, const void *buffer, unsigned int length) {
    assert(fd == 1 || fd == 2); assert(buffer && length); return (int)length;
}
void _exit(int status) { exit(status); }
int main(int argc, char **argv) {
    assert(argc == 2); mode = atoi(argv[1]);
    _Bool bound = _ZN16QGLShaderProgram4bindEv((void *)&token);
    assert(bound == (mode != 1));
    assert(initialized == (mode != 1));
    unsigned program = _ZN21MTexturePixmapPrivate18installPixelShaderERK10QByteArray(&token);
    assert(installs == 1 && program == (mode == 2 ? 0u : 88u));
    assert(current == 77 && binds == (mode == 2 ? 0 : 2) && uniforms == (mode == 2 ? 0 : 1));
    return 0;
}
