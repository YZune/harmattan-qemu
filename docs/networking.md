# Guest networking

[简体中文](networking.zh-CN.md) · [Building](building.md) · [Status](status.md)

Native builds support the SDK kernel's original SMC91x Ethernet driver through a QEMU SMC91C111 device and libslirp. The guest gets real IP connectivity through the host's connection. No TAP interface, administrator access or host port forwarding is required. The launcher keeps networking off unless explicitly enabled:

```sh
HARMATTAN_UI_NETWORK=user sh scripts/harmattan-qemu/run-arm64-ui.sh

# A fresh snapshot: DHCP, public DNS/HTTP and verified bidirectional host HTTP.
sh scripts/harmattan-qemu/run-arm64-ui.sh --network-diagnostic

# Enable networking during the existing desktop/application regression.
HARMATTAN_UI_NETWORK=user sh scripts/harmattan-qemu/run-arm64-ui.sh --usability-headless-diagnostic
```

Install libslirp and rebuild QEMU following the build guide. An existing downloaded preview app does not gain this capability from a source update. The launcher rejects a stale binary before cloning its disk.

## Data path

The board follows the original SDK `kernel-qemu` SMC patch: GPMC chip select 1 and GPIO54. The kernel programs the GPMC mapping and accesses the SMC registers at offset `0x300`. Direct boot disables the unused CS0 boot-chip mapping so it cannot overlap the kernel's reserved first MiB. QEMU's existing SMC91C111/GPMC/GPIO models carry real packets to SLIRP.

At startup, the guest's original `udhcpc` obtains `10.0.2.15/24`, gateway `10.0.2.2` and DNS `10.0.2.3`. A scoped callback checks the expected interface, MAC and lease before installing the route and resolver. Changes stay in the private guest disk used by that run. The current client takes one lease and exits; automatic renewal and sessions beyond the initial 24-hour lease are not validated.

The bounded diagnostic starts a loopback-only host HTTP server, checks a random 64 KiB download and upload by digest, resolves `example.com` inside the guest, and requires a nonempty HTTP 200 response from `http://example.com/`. It records failure if guest commands, DHCP, DNS, Internet access, content integrity or QEMU exit validation fails. Public connectivity is required for this diagnostic; an offline host is not a pass. Local artifacts contain serial output, QEMU stderr and `network-result.json`.

## HTTPS trust store

The prepared guest lacks the standard CA directory used by its original Qt/OpenSSL browser. UI launches can explicitly use the selected host Python's current TLS CA store:

```sh
HARMATTAN_UI_NETWORK=user HARMATTAN_UI_CA_CERTIFICATES=host \
  sh scripts/harmattan-qemu/run-arm64-ui.sh
```

The controller exports only that store's public trust anchors, validates the PEM, transfers bounded chunks, and checks the guest bytes/count and a temporary memory-backed mount over `/etc/ssl/certs`. The original on-disk certificate store stays intact, including with a persistent profile. The temporary CA contents disappear when QEMU exits. No roots are bundled or downloaded by this feature, and no host trust settings, private keys or client credentials are changed or copied. Which CAs are trusted follows the configured Python store; this is not necessarily the macOS Keychain.

The option defaults to `off`. Add `--ca-certificates host` when generating a local launcher to retain the selection. Certificate, hostname and validity checks remain enabled. Original OpenSSL protocol support and WebKit rendering limits still apply; an accepted TLS certificate does not establish that a modern page renders or works.

The [certificate validation record](certificates-validation.json) covers the generated shortcut UI regression, a valid HTTPS page rendered by the original browser, and rejection of a self-signed site. Baidu rendering is covered separately below.

## Original browser rendering

UI launches with `HARMATTAN_UI_NETWORK=user` now prepare a scoped software compositing adapter for the original Grob 0.73.2 / libgrob-qtwebkit 0.73.0. The browser's accelerated page compositor can enter the SDK GLES wrapper without a current context and crash while loading Baidu. The adapter uses the original WebKit preference setter and checks its getter to disable page acceleration. The default `original` browser mode preserves JavaScript settings. TLS verification and GLES error handling are preserved in both modes.

Only the pinned browser's desktop and D-Bus entries receive a wrapper, through temporary memory mounts. Their original on-disk contents remain intact, including in a persistent profile. Each launch checks Grob, QtWebProcess, the actual WebKit library link and helper identities. Other applications do not inherit this browser preload. Unknown versions fail explicitly instead of using the pinned ABI. The builder and release helper manifest include the ARM helper; an already downloaded preview app is unchanged.

The earlier [browser validation record](browser-validation.json) covers Web-icon/D-Bus startup, the Baidu HTTPS homepage, original keyboard text entry, a valid HTTPS page, rejection of a self-signed certificate and the combined UI regression. Its search probe remained on a loading page.

## Optional basic web mode

In a subsequent isolated run, Baidu search with JavaScript enabled kept the separate `QtWebProcess` renderer busy, and later navigation also stopped loading. The Grob UI process itself was sleeping, so inspecting that process alone missed the problem. Disabling webpage JavaScript through the original WebKit preference setter/getter allowed Baidu's own basic search results to render. The exact script or engine defect has not been isolated.

Select this workaround explicitly for text, links and ordinary HTML forms:

```sh
HARMATTAN_UI_NETWORK=user HARMATTAN_UI_CA_CERTIFICATES=host \
  HARMATTAN_UI_BROWSER_MODE=basic sh scripts/harmattan-qemu/run-arm64-ui.sh
```

For a separate Finder shortcut, append `--browser-mode basic --name 'Run N9 Basic Web.command'` to the [local launcher generator](building.md) command. This creates a second entry while retaining `Run N9.command` and its settings. New generators and the source launcher default to `original`; an explicit environment override still takes precedence. Basic mode requires user networking and reports that webpage JavaScript is disabled at launch.

The [basic mode validation record](browser-basic-validation.json) separates search, subsequent navigation, certificate rejection and UI regression. Basic mode does not support pages that require JavaScript, repair the JavaScript engine, or establish broad modern CSS compatibility. A site may send its basic form or redirect to HTTP, as Baidu did in the search probe; the adapter does not rewrite URLs or waive certificate errors. The HTTPS homepage and the complete search route are separate checks.

## Application boundaries

This restores SDK Ethernet and IP access. Retail Wi-Fi scanning, cellular, the original connection-manager service graph and the statusbar's connected indication are still separate work. An application that waits on those services can still appear offline even when direct sockets work. No invented Wi-Fi or mobile signal is displayed.

Old TLS libraries, expired certificates, retired endpoints and modern website requirements can independently prevent an old browser or application from working. This change does not disable certificate verification or establish arbitrary third-party application compatibility. See the [validation record](networking-validation.json) for the tested build and scope.
