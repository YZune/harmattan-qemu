/* Additional public-API pixel checks for the commands used by Qt/Home.
 * Included only with N00_SHELL_API_PROBE; the prior public probe is unchanged.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
static unsigned shell_pixel_checks;

static void shell_expect(unsigned r, unsigned g, unsigned b)
{
    unsigned char value[4] = {0};
    glReadPixels(0, 0, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, value);
    require(glGetError() == GL_NO_ERROR, "shell API GL error");
    require(value[0] == r && value[1] == g && value[2] == b, "shell API state pixel");
    shell_pixel_checks++;
}

static void shell_color(GLint location, float r, float g, float b, float a)
{
    const GLfloat value[] = {r, g, b, a};
    glUniform4fv(location, 1, value);
}

static void verify_shell_api(void)
{
    const char *vertex =
        "attribute vec2 pos; attribute vec2 uv; varying vec2 tc;"
        "uniform float z; void main(){tc=uv;gl_Position=vec4(pos,z,1.);}";
    const char *fragment =
        "precision mediump float; varying vec2 tc; uniform sampler2D tex;"
        "uniform vec4 color; uniform float textured;"
        "void main(){gl_FragColor=mix(color,texture2D(tex,tc),textured);}";
    GLuint vs = make_shader(GL_VERTEX_SHADER, &vertex, NULL, 1);
    GLuint fs = make_shader(GL_FRAGMENT_SHADER, &fragment, NULL, 1);
    GLuint program = glCreateProgram();
    glAttachShader(program, vs);
    glAttachShader(program, fs);
    glBindAttribLocation(program, 0, "pos");
    glBindAttribLocation(program, 1, "uv");
    glLinkProgram(program);
    GLint linked = 0;
    glGetProgramiv(program, GL_LINK_STATUS, &linked);
    require(linked == 1, "shell API shader link");
    glUseProgram(program);
    GLint z = glGetUniformLocation(program, "z");
    GLint color = glGetUniformLocation(program, "color");
    GLint textured = glGetUniformLocation(program, "textured");
    glUniform1i(glGetUniformLocation(program, "tex"), 0);
    const GLfloat vertices[] = {-1, -1, 0, 0, 1, -1, 1, 0, -1, 1, 0, 1, 1, 1, 1, 1};
    glEnableVertexAttribArray(0);
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, vertices);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, vertices + 2);
    GLuint texture;
    glGenTextures(1, &texture);
    glBindTexture(GL_TEXTURE_2D, texture);
    /* Three RGB565 pixels = 6 bytes, but UNPACK_ALIGNMENT=4 gives an 8-byte row. */
    const unsigned short packed[] = {0xf800, 0x07e0, 0x001f, 0xdead,
                                     0x001f, 0xffff, 0x07ff, 0xbeef};
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, 3, 2, 0, GL_RGB, GL_UNSIGNED_SHORT_5_6_5,
                 packed);
    glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, (GLfloat)GL_NEAREST);
    glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, (GLfloat)GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    GLfloat value = 1;
    glUniform1fv(textured, 1, &value);
    glViewport(0, 0, 6, 4);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    unsigned char readback[6 * 4 * 4 + 16];
    for (unsigned i = 0; i < sizeof(readback); i++)
        readback[i] = 0xa5;
    glReadPixels(0, 0, 6, 4, GL_RGBA, GL_UNSIGNED_BYTE, readback);
    const unsigned expected[] = {0xff0000, 0x00ff00, 0x0000ff,
                                 0x0000ff, 0xffffff, 0x00ffff};
    for (unsigned y = 0; y < 4; y++) {
        for (unsigned x = 0; x < 6; x++) {
            unsigned at = (y * 6 + x) * 4;
            unsigned rgb =
                (readback[at] << 16) | (readback[at + 1] << 8) | readback[at + 2];
            require(rgb == expected[(y / 2) * 3 + x / 2],
                    "RGB565 row padding and mixed-float nearest filter");
            shell_pixel_checks++;
        }
    }
    for (unsigned i = 96; i < sizeof(readback); i++)
        require(readback[i] == 0xa5, "RGB565 readback guard");
    require(glGetError() == GL_NO_ERROR, "RGB565 upload and scalar uniform");
    /* Bounded rejection must preserve the existing texture and program. */
    glUniform1fv(textured, 4097, &value);
    require(glGetError() == GL_INVALID_VALUE, "oversized scalar uniform rejected");
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 3, 2, 0, GL_RGBA, GL_UNSIGNED_SHORT_5_6_5,
                 packed);
    require(glGetError() == GL_INVALID_VALUE, "RGB565 with RGBA rejected");
    value = 0;
    glUniform1fv(textured, 1, &value);
    glUniform1fv(z, 1, &value);
    glViewport(0, 0, 1, 1);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glClearDepthf(0.25f);
    glClearColor(0, 0, 1, 1);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    shell_color(color, 1, 0, 0, 1);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    shell_expect(0, 0, 255); /* z=.5 fails against the clear value .25 */
    glDepthFunc(GL_GREATER);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    shell_expect(255, 0, 0);
    glDepthMask(GL_FALSE);
    value = 0.5f;
    glUniform1fv(z, 1, &value);
    shell_color(color, 0, 1, 0, 1);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    shell_expect(0, 255, 0);
    value = 0.2f;
    glUniform1fv(z, 1, &value);
    shell_color(color, 1, 0, 0, 1);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    shell_expect(255, 0, 0); /* .6 > .5 proves the .75 draw did not write depth */
    glDisable(GL_DEPTH_TEST);
    glEnable(GL_STENCIL_TEST);
    glStencilMask(0xff);
    glClear(GL_STENCIL_BUFFER_BIT);
    glStencilFunc(GL_ALWAYS, 3, 0xff);
    glStencilOp(GL_KEEP, GL_KEEP, GL_REPLACE);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    glStencilMask(0);
    glStencilFunc(GL_ALWAYS, 5, 0xff);
    shell_color(color, 0, 1, 0, 1);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    glStencilFunc(GL_EQUAL, 3, 0xff);
    glStencilOp(GL_KEEP, GL_KEEP, GL_KEEP);
    shell_color(color, 0, 0, 1, 1);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    shell_expect(0, 0, 255); /* replace/ref/write-mask were all effective */
    glDisable(GL_STENCIL_TEST);
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE);
    shell_color(color, 1, 0, 0, 1);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    shell_expect(255, 0, 255);
    glDisable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ZERO);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glClearDepthf(1);
    glStencilMask(0xff);
    glStencilFunc(GL_ALWAYS, 0, 0xff);
    glDisableVertexAttribArray(0);
    glDisableVertexAttribArray(1);
    glDeleteTextures(1, &texture);
    glUseProgram(0);
    glDeleteProgram(program);
    glDeleteShader(vs);
    glDeleteShader(fs);
    require(glGetError() == GL_NO_ERROR, "shell API cleanup and recovery");
    require(shell_pixel_checks == 30, "shell API exact check count");
    printf("\nN00_SHELL_API_OK pixels=30 rejects=2\n");
    fflush(NULL);
}
