# Native macOS DGLES backend

[简体中文](README.zh-CN.md) · [Build guide](../../docs/building.md)

Apply `gles-libs-1.4.2-cocoa-fbo.patch` to `gles-libs-1.4.2/` from the pinned PR1.3 source archive. It is a host graphics library patch, not a stage of the QEMU device patch sequence.

The build script is `scripts/harmattan-qemu/build-dgles2-host.sh`. It builds locally without global installation. `smoke-dgles-host.py` exercises GLES1/GLES2 offscreen rendering through the native libraries in a macOS graphics session.

The opt-in path uses `DGLES2_COCOA_FBO=1`, `DGLES2_FRONTEND=offscreen`, and `DGLES2_BACKEND=cocoa`. Other variants, general concurrency, cross-context surfaces and complete GLES conformance are unverified. Preserve individual source licenses; the whole archive does not have a single MIT license. See [sources](../../docs/sources.md).
