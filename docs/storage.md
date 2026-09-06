# Persistent user profiles

[简体中文](storage.zh-CN.md) · [Building](building.md) · [Networking](networking.md)

An explicit profile preserves the guest system partition, installed packages and saved home files across launches. The default source launcher still creates disposable snapshots. Rebuild the Cocoa interaction runtime before using profiles:

```sh
HARMATTAN_USER_PROFILE="$PWD/extracted/profiles/daily" sh scripts/harmattan-qemu/run-arm64-ui.sh

# Select the same directory next time. Networking can be enabled separately.
HARMATTAN_USER_PROFILE="$PWD/extracted/profiles/daily" HARMATTAN_UI_NETWORK=user sh scripts/harmattan-qemu/run-arm64-ui.sh

# Creates its own profile: two persistent boots plus snapshot isolation.
sh scripts/harmattan-qemu/run-arm64-ui.sh --storage-diagnostic
```

The first launch creates a read-only APFS clone of the prepared base disk and a private 32 GiB virtual qcow2 write layer. Later launches reuse that layer; changing the source-image environment variable does not replace an existing profile. The original input disk stays separate. Choose another directory for another profile. Do not select an existing unrelated folder or edit profile backing files.

A profile lock is held by both controller and QEMU, so a second launcher cannot write the same disk even if the first controller dies. Before a clean profile is opened again, its current write layer is APFS-cloned to `checkpoint.qcow2`. An unclean session retains that previous checkpoint and current disk for journal recovery; it does not silently roll back the user's newer data.

## Exit and recovery

Save changes inside the application, then close the Cocoa window or use Ctrl-C after `READY`. The controller runs guest `sync`, pauses the CPU, quits QEMU, checks the qcow2 structure and flushes the host file before recording a clean exit. A Cocoa close during startup waits for the startup checks to finish. A direct external QMP quit, force quit, crash or interruption before `READY` can leave the profile marked unclean. Filesystem journal recovery on the next boot is separate from an application recovering unsaved work.

`/tmp` and `/var/run` use fresh, size-limited guest tmpfs mounts in profile sessions, keeping old socket/PID files out of the next startup. Saved application data belongs in the guest's normal persistent locations, usually `/home/user`.

Back up the entire profile directory while it is closed; `disk.qcow2` depends on `base.raw`. The checkpoint is a disk recovery aid, not a CPU/RAM snapshot or an independent backup. Keep both layers together when moving the profile. Automated rollback, arbitrary VM save/restore, suspend/resume and power-loss durability are not established by this feature.

Diagnostics refuse `HARMATTAN_USER_PROFILE` and use their own disks. Newly rebuilt prebuilt apps also accept an explicit `run --profile <directory>` through their private runtime command; already downloaded previews must be rebuilt first. The ordinary app entry point retains its existing snapshot default. See the [validation record](storage-validation.json) for tested behavior.
