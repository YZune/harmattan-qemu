/* Shared public-library and raw-wire FBO checks. The includer supplies FBO_CALL,
 * FBO_PTR, FBO_COLOR and require. Raw-wire tests do not need SDK headers.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
enum {
    FB_TARGET = 0x8d40, FB_RENDERBUFFER = 0x8d41, FB_COLOR = 0x8ce0,
    FB_DEPTH = 0x8d00, FB_COMPLETE = 0x8cd5, FB_MISSING = 0x8cd7,
    FB_TEXTURE_2D = 0x0de1, FB_RGBA = 0x1908, FB_UNSIGNED_BYTE = 0x1401,
    FB_WIDTH = 4, FB_HEIGHT = 3, FB_BYTES = FB_WIDTH * FB_HEIGHT * 4
};

static void fbo_query(unsigned kind, unsigned pname, unsigned attachment, int expected)
{
    int values[3] = {0x11223344, -1, 0x55667788};
    if (kind == FB_TARGET) {
        FBO_CALL(glGetFramebufferAttachmentParameteriv, FB_TARGET, attachment,
                 pname, FBO_PTR(values + 1));
    } else if (kind == FB_RENDERBUFFER) {
        FBO_CALL(glGetRenderbufferParameteriv, FB_RENDERBUFFER, pname,
                 FBO_PTR(values + 1));
    } else {
        FBO_CALL(glGetIntegerv, pname, FBO_PTR(values + 1));
    }
    require(values[0] == 0x11223344 && values[1] == expected &&
                values[2] == 0x55667788, "FBO query value and output guards");
}

static void fbo_pixels(unsigned char red, unsigned char green, unsigned char blue)
{
    unsigned char rgba[FB_BYTES + 16];
    for (unsigned i = 0; i < sizeof(rgba); i++) {
        rgba[i] = 0xa5;
    }
    FBO_CALL(glReadPixels, 0, 0, FB_WIDTH, FB_HEIGHT, FB_RGBA,
             FB_UNSIGNED_BYTE, FBO_PTR(rgba));
    for (unsigned i = 0; i < FB_BYTES; i += 4) {
        require(rgba[i] == red && rgba[i + 1] == green && rgba[i + 2] == blue &&
                    rgba[i + 3] == 255, "FBO RGBA pixels");
    }
    for (unsigned i = FB_BYTES; i < sizeof(rgba); i++) {
        require(rgba[i] == 0xa5, "FBO readback guard");
    }
}

static void verify_fbo_api(void)
{
    fbo_query(0, 0x8ca6, 0, 0); /* GL_FRAMEBUFFER_BINDING */
    fbo_query(0, 0x8ca7, 0, 0); /* GL_RENDERBUFFER_BINDING */
    int maximum[3] = {0x11223344, 0, 0x55667788};
    FBO_CALL(glGetIntegerv, 0x84e8, FBO_PTR(maximum + 1)); /* MAX_RENDERBUFFER_SIZE */
    require(maximum[0] == 0x11223344 && maximum[1] >= FB_WIDTH &&
                maximum[1] <= 4096 && maximum[2] == 0x55667788,
            "bounded maximum renderbuffer size and query guards");
    unsigned frames[3] = {0x11223344, 0, 0x55667788};
    unsigned renders[4] = {0x11223344, 0, 0, 0x55667788};
    FBO_CALL(glGenFramebuffers, 1, FBO_PTR(frames + 1));
    FBO_CALL(glGenRenderbuffers, 2, FBO_PTR(renders + 1));
    require(frames[1] && renders[1] && renders[2] && renders[1] != renders[2] &&
                frames[0] == 0x11223344 && frames[2] == 0x55667788 &&
                renders[0] == 0x11223344 && renders[3] == 0x55667788,
            "generated FBO/RBO names and output guards");
    require(!FBO_CALL(glIsFramebuffer, frames[1]), "generated FBO is not yet bound");
    require(!FBO_CALL(glIsRenderbuffer, renders[1]), "generated RBO is not yet bound");
    FBO_CALL(glBindFramebuffer, FB_TARGET, frames[1]);
    FBO_CALL(glBindRenderbuffer, FB_RENDERBUFFER, renders[1]);
    require(FBO_CALL(glIsFramebuffer, frames[1]), "bound FBO exists");
    require(FBO_CALL(glIsRenderbuffer, renders[1]), "bound RBO exists");
    fbo_query(0, 0x8ca6, 0, frames[1]);
    fbo_query(0, 0x8ca7, 0, renders[1]);
    require(FBO_CALL(glCheckFramebufferStatus, FB_TARGET) == FB_MISSING,
            "unattached FBO reports missing attachment");
    unsigned texture = 0;
    FBO_CALL(glGenTextures, 1, FBO_PTR(&texture));
    FBO_CALL(glBindTexture, FB_TEXTURE_2D, texture);
    FBO_CALL(glTexParameteri, FB_TEXTURE_2D, 0x2801, 0x2600);
    FBO_CALL(glTexParameteri, FB_TEXTURE_2D, 0x2800, 0x2600);
    FBO_CALL(glTexImage2D, FB_TEXTURE_2D, 0, FB_RGBA, FB_WIDTH, FB_HEIGHT, 0,
             FB_RGBA, FB_UNSIGNED_BYTE, 0);
    FBO_CALL(glFramebufferTexture2D, FB_TARGET, FB_COLOR, FB_TEXTURE_2D, texture, 0);
    FBO_CALL(glRenderbufferStorage, FB_RENDERBUFFER, 0x81a5, FB_WIDTH, FB_HEIGHT);
    FBO_CALL(glFramebufferRenderbuffer, FB_TARGET, FB_DEPTH, FB_RENDERBUFFER, renders[1]);
    require(FBO_CALL(glCheckFramebufferStatus, FB_TARGET) == FB_COMPLETE,
            "texture plus depth-renderbuffer FBO complete");
    fbo_query(FB_TARGET, 0x8cd0, FB_COLOR, 0x1702); /* OBJECT_TYPE = GL_TEXTURE */
    fbo_query(FB_TARGET, 0x8cd1, FB_COLOR, texture); /* OBJECT_NAME */
    fbo_query(FB_TARGET, 0x8cd2, FB_COLOR, 0); /* TEXTURE_LEVEL */
    fbo_query(FB_TARGET, 0x8cd3, FB_COLOR, 0); /* TEXTURE_CUBE_MAP_FACE */
    fbo_query(FB_TARGET, 0x8cd0, FB_DEPTH, FB_RENDERBUFFER);
    fbo_query(FB_TARGET, 0x8cd1, FB_DEPTH, renders[1]);
    fbo_query(FB_RENDERBUFFER, 0x8d42, 0, FB_WIDTH);
    fbo_query(FB_RENDERBUFFER, 0x8d43, 0, FB_HEIGHT);
    fbo_query(FB_RENDERBUFFER, 0x8d44, 0, 0x81a5); /* INTERNAL_FORMAT = DEPTH_COMPONENT16 */
    fbo_query(FB_RENDERBUFFER, 0x8d54, 0, 16); /* DEPTH_SIZE */
    FBO_COLOR(1.0f, 0.0f, 1.0f, 1.0f);
    FBO_CALL(glClear, 0x4100); /* COLOR_BUFFER_BIT | DEPTH_BUFFER_BIT */
    fbo_pixels(255, 0, 255);
    require(!FBO_CALL(glGetError), "texture FBO operations have no GL error");

    /* GLES2 ignores object-specific arguments when object zero detaches. */
    FBO_CALL(glFramebufferTexture2D, FB_TARGET, FB_COLOR, 0, 0, 123);
    fbo_query(FB_TARGET, 0x8cd0, FB_COLOR, 0); /* OBJECT_TYPE = GL_NONE */
    require(!FBO_CALL(glGetError), "zero texture detaches despite unused arguments");
    FBO_CALL(glFramebufferRenderbuffer, FB_TARGET, FB_DEPTH, 0, 0);
    fbo_query(FB_TARGET, 0x8cd0, FB_DEPTH, 0);
    require(!FBO_CALL(glGetError), "zero renderbuffer detaches despite unused target");
    require(FBO_CALL(glCheckFramebufferStatus, FB_TARGET) == FB_MISSING,
            "detached FBO reports missing attachment");
    FBO_CALL(glFramebufferRenderbuffer, FB_TARGET, FB_DEPTH, FB_RENDERBUFFER, renders[1]);

    FBO_CALL(glBindRenderbuffer, FB_RENDERBUFFER, renders[2]);
    FBO_CALL(glRenderbufferStorage, FB_RENDERBUFFER, 0x8056, FB_WIDTH, FB_HEIGHT); /* RGBA4 */
    FBO_CALL(glFramebufferRenderbuffer, FB_TARGET, FB_COLOR, FB_RENDERBUFFER, renders[2]);
    require(FBO_CALL(glCheckFramebufferStatus, FB_TARGET) == FB_COMPLETE,
            "color-renderbuffer plus depth-renderbuffer FBO complete");
    fbo_query(FB_TARGET, 0x8cd0, FB_COLOR, FB_RENDERBUFFER);
    fbo_query(FB_TARGET, 0x8cd1, FB_COLOR, renders[2]);
    fbo_query(FB_RENDERBUFFER, 0x8d44, 0, 0x8056);
    for (unsigned pname = 0x8d50; pname <= 0x8d53; pname++) {
        fbo_query(FB_RENDERBUFFER, pname, 0, 4); /* RED/GREEN/BLUE/ALPHA_SIZE */
    }
    FBO_COLOR(0.0f, 1.0f, 1.0f, 1.0f);
    FBO_CALL(glClear, 0x4000);
    fbo_pixels(0, 255, 255);
    require(!FBO_CALL(glGetError), "renderbuffer FBO operations have no GL error");

    FBO_CALL(glBindFramebuffer, FB_TARGET, 0);
    fbo_query(0, 0x8ca6, 0, 0);
    FBO_CALL(glBindFramebuffer, FB_TARGET, frames[1]);
    FBO_CALL(glDeleteFramebuffers, 1, FBO_PTR(frames + 1));
    fbo_query(0, 0x8ca6, 0, 0); /* Deleting a bound FBO also restores virtual zero. */
    FBO_CALL(glDeleteRenderbuffers, 2, FBO_PTR(renders + 1));
    fbo_query(0, 0x8ca7, 0, 0);
    require(!FBO_CALL(glIsFramebuffer, frames[1]), "deleted FBO no longer exists");
    require(!FBO_CALL(glIsRenderbuffer, renders[1]), "deleted depth RBO no longer exists");
    require(!FBO_CALL(glIsRenderbuffer, renders[2]), "deleted color RBO no longer exists");
    FBO_CALL(glDeleteTextures, 1, FBO_PTR(&texture));
    require(FBO_CALL(glCheckFramebufferStatus, FB_TARGET) == FB_COMPLETE,
            "restored default framebuffer complete");
    require(!FBO_CALL(glGetError), "FBO cleanup has no GL error");
}
