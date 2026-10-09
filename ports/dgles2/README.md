# DGLES host backends

[简体中文](README.zh-CN.md) · [Build guide](../../docs/building.md)

Apply `gles-libs-1.4.2-cocoa-fbo.patch` to `gles-libs-1.4.2/` from the pinned PR1.3 source archive. It is a host graphics library patch, not a stage of the QEMU device patch sequence.

The build script is `scripts/harmattan-qemu/build-dgles2-host.sh`. It builds locally without global installation. `smoke-dgles-host.py` exercises GLES1/GLES2 offscreen rendering through the native libraries in a macOS graphics session.

The opt-in path uses `DGLES2_COCOA_FBO=1`, `DGLES2_FRONTEND=offscreen`, and `DGLES2_BACKEND=cocoa`. Other variants, general concurrency, cross-context surfaces and complete GLES conformance are unverified. Preserve individual source licenses; the whole archive does not have a single MIT license. See [sources](../../docs/sources.md).

On Linux x86_64 the builder applies `gles-libs-1.4.2-linux-osmesa.patch` after the Cocoa patch and selects `DGLES2_BACKEND=osmesa`, with Cocoa/X11/GLX/WGL disabled. It uses the archive's ABI headers and `libOSMesa.so.8`; see the [Linux guide](../../docs/linux.md). Both backends remain opt-in local builds.

The Linux smoke checks GLES1/GLES2 pixels, resize and ownership failures, native unbind, both destruction orders, protected retired pixel memory and worker cleanup before process exit. QEMU's separate early-cleanup patch stops graphics workers before Mesa's `atexit` teardown. These checks do not establish general cross-context sharing or complete GLES conformance.
