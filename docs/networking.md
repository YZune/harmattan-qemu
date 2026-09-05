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

## Application boundaries

This restores SDK Ethernet and IP access. Retail Wi-Fi scanning, cellular, the original connection-manager service graph and the statusbar's connected indication are still separate work. An application that waits on those services can still appear offline even when direct sockets work. No invented Wi-Fi or mobile signal is displayed.

Old TLS libraries, expired certificates, retired endpoints and modern website requirements can independently prevent an old browser or application from working. This change does not disable certificate verification or establish arbitrary third-party application compatibility. See the [validation record](networking-validation.json) for the tested build and scope.
