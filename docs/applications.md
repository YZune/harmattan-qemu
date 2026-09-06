# Third-party ARMEL applications

[简体中文](applications.zh-CN.md) · [Profiles](storage.md) · [Networking](networking.md)

The source launcher can install explicitly supplied Harmattan `.deb` files into a private user profile. Close that profile's running guest first. Supply dependencies before applications; the installer does not download packages or resolve an online repository.

```sh
# Inspect identity, dependencies and maintainer scripts on the host.
python3 scripts/harmattan-qemu/armel-packages.py downloads/applications/example_armel.deb

# Install inside the guest and preserve its real package database.
HARMATTAN_USER_PROFILE="$PWD/extracted/profiles/daily" \
  sh scripts/harmattan-qemu/run-arm64-ui.sh --install-packages \
  downloads/applications/dependency_armel.deb downloads/applications/example_armel.deb

# Open the same profile after installation.
HARMATTAN_USER_PROFILE="$PWD/extracted/profiles/daily" \
  HARMATTAN_UI_NETWORK=user sh scripts/harmattan-qemu/run-arm64-ui.sh
```

These filenames are placeholders for packages you have obtained and reviewed. Select **armel**, or architecture-independent **all**, for this ARM32 guest. ARM64 describes the Mac executable, not the guest package ABI. Modern Sailfish RPMs, Android APKs and arbitrary Debian ARM packages are not interchangeable with Harmattan packages.

The installer accepts 1–24 files, at most 64 MiB each and 96 MiB total, using the historical gzip Debian archive layout. It reads metadata without extracting package files or executing maintainer scripts on macOS. Original bytes are held for a private, randomly addressed loopback HTTP transfer through QEMU's SDK Ethernet. SHA-256 is recorded on the host and SHA-1 checks the exact guest transfer. These hashes establish content identity, not publisher trust. An optional historical `_x509sig` member is retained but its signature is **not verified**.

Inside this rescue/adaptation guest, installation uses `/usr/bin/dpkg.real`, because the retail Aegis wrapper requires the full product security service graph. Dependency checking and maintainer-script failures remain active; there is no forced-dependency success or global `dpkg --configure -a`. Before and after installation, the helper verifies the SDK EGL/GLES library identities and restores known links that standard `ldconfig` triggers can redirect to retail SGX drivers. Unknown libraries or links fail validation. A successful result requires each requested package's exact version to be `install ok installed`, then a guest sync and clean QEMU exit. A failed install can leave dpkg's partial state in the profile; logs and the profile checkpoint are retained. Use a separate profile when evaluating an unfamiliar package.

## Initial application set

The first set covers local notes, file management and reading. The upstream/archive entries are [ownNotes by Khertan](https://openrepos.net/content/khertan/ownnotes), [Filebox by CepiPerez](https://openrepos.net/content/cepiperez/filebox), and the [Harmattan FBReader backup](https://openrepos.net/content/hooddy/fbreader-harmattan). The FBReader page is an archive upload, not a claim that its uploader is the original developer.

| Application | Package | Dependency detail |
| --- | --- | --- |
| ownNotes | `ownnotes 1.2.3 armel` | Requires the matching Harmattan SDK Python 2.6 stack, including `libpython2.6` |
| Filebox | `filebox 0.1.0 armel` | Uses the guest's existing MeeGo Touch/Qt libraries |
| FBReader | `fbreader 0.99.5 armel` | Uses the guest's existing Qt, curl, SQLite and resource libraries |

For ownNotes, the validated dependency order is `libncurses5`, `readline-common`, `libreadline5`, `python2.6-minimal`, `python2.6`, `libpython2.6`, then `ownnotes`. The exact versions and hashes are recorded in [application validation](applications-validation.json). These historical packages remain user-supplied inputs and are not redistributed here.

Installing a package is separate from launching it, editing content, reopening saved work, and using online services. Compatibility results apply to the recorded versions and functions. Cloud accounts, modern TLS, unavailable Nokia services, DRM, hardware-dependent programs and broad application compatibility require separate work.

Current evidence confirms installation and the original desktop after a profile restart. Editing, file operations and EPUB navigation have **not yet been validated**: the Mac was locked during this milestone.
