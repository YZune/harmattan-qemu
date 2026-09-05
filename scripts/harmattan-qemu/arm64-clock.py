"""Synchronize the RTC-less rescue guest with the host clock and timezone."""
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import time


GUEST_TIMEZONE = "/tmp/n00-host-localtime"
REPORT_PHASES = ("bootstrap", "theme", "compositor", "home", "settled", "final")
MAX_TIMEZONE_BYTES = 1024 * 1024
PPM_HEADER = b"P6\n864 480\n255\n"
FRAME_WIDTH = 864
FRAME_HEIGHT = 480
STATUSBAR_THICKNESS = 72
HEARTBEAT_MD5 = {
    "/sbin/dsme": "a00ca1ff8a6ca38f189e288b17c2c11e",
    "/sbin/dsme-server": "87cac7bd773955d8f293894660a314ae",
    "/lib/dsme/heartbeat.so": "d08eef15c3226700a4299fdecbbd5951",
    "/lib/dsme/iphb.so": "d87a519165b291e1d379a2ec75affde9",
    "/usr/lib/libiphb.so.0.0.0": "c4ed4fd3c3c9566fade0270a25029610",
}


def enabled(mode):
    if mode not in ("host", "off"):
        raise ValueError("invalid clock mode")
    return mode == "host"


def prepare(path=None):
    source = Path(path or os.environ.get("HARMATTAN_UI_TIMEZONE_FILE", "/etc/localtime"))
    payload = source.read_bytes()
    if not 44 <= len(payload) <= MAX_TIMEZONE_BYTES or payload[:4] != b"TZif":
        raise ValueError("host timezone file is not bounded TZif data")
    return payload, {
        "enabled": True,
        "mode": "host",
        "host_timezone_file": str(source.resolve(strict=True)),
        "timezone_sha256": hashlib.sha256(payload).hexdigest(),
        "timezone_md5": hashlib.md5(payload).hexdigest(),
        "guest_timezone_file": GUEST_TIMEZONE,
        "scope": "host UTC plus host TZif in this disposable snapshot; no RTC persistence or network time",
    }


def snapshot(now=None):
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("clock snapshot must be timezone-aware")
    value = value.astimezone(timezone.utc).replace(microsecond=0)
    return {
        "epoch": int(value.timestamp()),
        "utc": value.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date_argument": value.strftime("%m%d%H%M%Y.%S"),
    }


def guest_sync_command(value, timezone_md5):
    date_argument = value.get("date_argument", "")
    if not re.fullmatch(r"\d{12}\.\d{2}", date_argument):
        raise ValueError("invalid BusyBox date argument")
    if not re.fullmatch(r"[0-9a-f]{32}", timezone_md5):
        raise ValueError("invalid timezone digest")
    return (
        f"chmod 0444 {GUEST_TIMEZONE} && "
        f"test \"$(md5sum {GUEST_TIMEZONE} | cut -d ' ' -f 1)\" = {timezone_md5} && "
        f"date -u {date_argument} >/dev/null 2>&1\n"
        "clock_status=$?\n"
        "if [ \"$clock_status\" = 0 ]; then\n"
        f"  export N00_UI_CLOCK_SYNC=1 N00_UI_TZFILE={GUEST_TIMEZONE}\n"
        "  clock_rtc=absent\n"
        "  [ -e /sys/class/rtc/rtc0 ] && clock_rtc=present\n"
        "  clock_sample=$(TZ=:\"$N00_UI_TZFILE\" date '+utc_epoch=%s local=%Y-%m-%dT%H:%M:%S%z offset=%z')\n"
        "  printf '\\nN00_CLOCK_SYNC source=host %s zone_md5=%s rtc=%s\\n' \"$clock_sample\" "
        f"\"$(md5sum {GUEST_TIMEZONE} | cut -d ' ' -f 1)\" \"$clock_rtc\"\n"
        "fi\n"
        "printf '\\nN00_CLOCK_SYNC_EXIT_%s\\nN00_CLOCK_SYNC_FINISHED\\n' \"$clock_status\"\n"
    ).encode()


def _local_epoch(value):
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError as error:
        raise ValueError("invalid guest local timestamp") from error
    return int(parsed.timestamp())


def validate_heartbeat(data, require_runtime=False):
    data = data.replace(b"\r", b"")
    records = re.findall(
        rb"(?:^|\n)N00_HEARTBEAT_REPORT_BEGIN\n(.*?)\nN00_HEARTBEAT_REPORT_END\n", data, re.S)
    if len(records) != 1:
        raise ValueError("missing or ambiguous original heartbeat service evidence")
    record = records[0]
    pids = {}
    for name, path in (("dsme", "/sbin/dsme"), ("dsme-server", "/sbin/dsme-server")):
        found = re.findall(
            rb"^N00_HEARTBEAT_PROCESS " + name.encode() + rb" (\d+)\n"
            rb"Name:\s*" + name.encode() + rb"\nState:\s*([RS])[^\n]*\nTgid:\s*(\d+)\nPid:\s*(\d+)"
            rb"\nPPid:[^\n]*\nTracerPid:\s*0\nUid:\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\n", record, re.M)
        if len(found) != 1:
            raise ValueError("original heartbeat process is missing, stopped or ambiguous")
        pid, _, tgid, actual_pid, *uids = found[0]
        if (pid, pid) != (tgid, actual_pid) or uids != [b"0"] * 4:
            raise ValueError("original heartbeat process identity mismatch")
        pids[name] = int(pid)
        proc_path = f"/proc/{pid.decode()}/exe"
        if record.splitlines().count(path.encode()) != 1:
            raise ValueError("heartbeat executable link target mismatch")
        matches = re.findall(rb"^([0-9a-f]{32})  " + re.escape(proc_path.encode()) + rb"$", record, re.M)
        if matches != [HEARTBEAT_MD5[path].encode()]:
            raise ValueError("running heartbeat executable identity mismatch")
    for path, digest in HEARTBEAT_MD5.items():
        if re.findall(rb"^([0-9a-f]{32})  " + re.escape(path.encode()) + rb"$", record, re.M) != [digest.encode()]:
            raise ValueError("original heartbeat file identity mismatch")
    for marker in (b"N00_HEARTBEAT_SOCKET_READY /dev/shm/iphb",
                   b"N00_HEARTBEAT_KERNEL_DEVICE_READY /dev/iphb"):
        if record.splitlines().count(marker) != 1:
            raise ValueError("heartbeat socket or kernel device is unavailable")
    result = {"dsme_pid": pids["dsme"], "server_pid": pids["dsme-server"],
              "socket": "/dev/shm/iphb", "kernel_device": "/dev/iphb",
              "original_binaries": True}
    if require_runtime:
        traces = re.findall(
            rb"(?:^|\n)N00_HEARTBEAT_RUNTIME_BEGIN\n(.*?)\nN00_HEARTBEAT_RUNTIME_END\n", data, re.S)
        if len(traces) != 1:
            raise ValueError("missing or ambiguous original heartbeat runtime trace")
        trace = traces[0]
        for marker in (b"DSME debug: heartbeat.so loaded", b"DSME debug: iphb.so loaded"):
            if trace.splitlines().count(marker) != 1:
                raise ValueError("original heartbeat module load evidence is missing")
        if any(marker in trace for marker in (b"dsme-server nonresponsive", b"Exited main loop, quitting")):
            raise ValueError("original heartbeat service stopped during the UI run")
        hwwd = trace.splitlines().count(b"DSME debug: HEARTBEAT from HWWD")
        waits = [(match.start(), int(match.group(1)), int(match.group(2)), int(match.group(3)))
                 for match in re.finditer(
                     rb"DSME debug: client with PID (\d+) \(sysuid\) signaled interest of waiting "
                     rb"\(min=(\d+)/max=(\d+)\)", trace)]
        wakes = [match.start() for match in re.finditer(
            rb"DSME debug: waking up clients because somebody was woken up", trace)]
        sysuid_pids = {wait[1] for wait in waits}
        rearmed = any(first[0] < wake < second[0] for first in waits for wake in wakes for second in waits)
        if hwwd < 2 or len(sysuid_pids) != 1 or len(waits) < 2 or not wakes or not rearmed:
            raise ValueError("System UI did not re-arm its original IP heartbeat after a wakeup")
        result["runtime_trace"] = {"sysuid_pid": sysuid_pids.pop(), "waits": len(waits),
                                   "wakeups": len(wakes), "hwwd_heartbeats": hwwd,
                                   "rearmed_after_wakeup": True}
    return result


def validate_sync(data, expected_epoch, timezone_md5, maximum_skew=3):
    data = data.replace(b"\r", b"")
    exits = re.findall(rb"^N00_CLOCK_SYNC_EXIT_(\d+)$", data, re.M)
    if exits != [b"0"] or data.splitlines().count(b"N00_CLOCK_SYNC_FINISHED") != 1:
        raise ValueError("host clock synchronization did not complete exactly once")
    records = re.findall(
        rb"^N00_CLOCK_SYNC source=host utc_epoch=(\d+) local=([^ ]+) offset=([+-]\d{4}) "
        rb"zone_md5=([0-9a-f]{32}) rtc=(absent|present)$", data, re.M)
    if len(records) != 1:
        raise ValueError("missing or ambiguous synchronized clock observation")
    epoch, local, offset, digest, rtc = records[0]
    epoch = int(epoch)
    if digest.decode() != timezone_md5 or abs(epoch - expected_epoch) > maximum_skew:
        raise ValueError("initial guest clock or timezone identity differs from the host snapshot")
    if _local_epoch(local.decode()) != epoch or not local.endswith(offset):
        raise ValueError("guest local time does not map to its UTC epoch")
    return {
        "source": "host",
        "sync_epoch": epoch,
        "local_at_sync": local.decode(),
        "utc_offset_at_sync": offset.decode(),
        "rtc": rtc.decode(),
    }


def validate_serial(data, expected_epoch, timezone_md5, now_epoch=None, maximum_skew=10,
                    additional_phases=()):
    result = validate_sync(data, expected_epoch, timezone_md5)
    heartbeat = validate_heartbeat(data, require_runtime=bool(additional_phases))
    records = re.findall(
        rb"^N00_CLOCK_REPORT phase=([a-z-]+) utc_epoch=(\d+) local=([^ ]+) offset=([+-]\d{4}) "
        rb"zone_md5=([0-9a-f]{32}) heartbeat=(\d+),(\d+)$", data.replace(b"\r", b""), re.M)
    phases = [record[0].decode() for record in records]
    expected_phases = list(REPORT_PHASES) + list(additional_phases)
    if phases != expected_phases:
        raise ValueError("clock reports are missing, duplicated or out of phase order")
    epochs = []
    local_values = []
    for _, raw_epoch, local, offset, digest, dsme_pid, server_pid in records:
        epoch = int(raw_epoch)
        if digest.decode() != timezone_md5 or _local_epoch(local.decode()) != epoch or not local.endswith(offset):
            raise ValueError("guest phase clock or timezone is inconsistent")
        if (int(dsme_pid), int(server_pid)) != (heartbeat["dsme_pid"], heartbeat["server_pid"]):
            raise ValueError("heartbeat service restarted during clock observation")
        epochs.append(epoch)
        local_values.append(local.decode())
    if epochs != sorted(epochs) or epochs[0] < result["sync_epoch"]:
        raise ValueError("guest wall clock moved backwards")
    current = int(time.time()) if now_epoch is None else int(now_epoch)
    if abs(current - epochs[-1]) > maximum_skew:
        raise ValueError("guest clock stopped or drifted from the host")
    result.update({
        "reports": len(records),
        "phases": phases,
        "first_epoch": epochs[0],
        "final_epoch": epochs[-1],
        "elapsed_seconds": epochs[-1] - epochs[0],
        "local_at_final": local_values[-1],
        "local_minutes": {phase: local[:16] for phase, local in zip(phases, local_values)},
        "minute_changed_after_home": any(local[:16] != local_values[REPORT_PHASES.index("settled")][:16]
                                         for local in local_values[len(REPORT_PHASES):]),
        "maximum_final_skew_seconds": maximum_skew,
        "monotonic_wall_clock": True,
        "heartbeat": heartbeat,
    })
    return result


def compare_home_frames(first, second, allow_statusbar_change=False):
    expected = len(PPM_HEADER) + FRAME_WIDTH * FRAME_HEIGHT * 3
    if (not first.startswith(PPM_HEADER) or not second.startswith(PPM_HEADER)
            or len(first) != expected or len(second) != expected):
        raise ValueError("invalid normalized Home framebuffer")
    if not allow_statusbar_change:
        return {"content_equal": first == second, "statusbar_changed_pixels": 0,
                "statusbar_dynamic": False}
    # The native PPM is normalized back to the 864x480 guest framebuffer.
    # Original portrait Home is rotated 270 degrees there, so its 864x72
    # statusbar pixmap occupies the leftmost 72 columns after composition.
    start = len(PPM_HEADER)
    row_bytes = FRAME_WIDTH * 3
    bar_bytes = STATUSBAR_THICKNESS * 3
    changed = 0
    content_equal = True
    for row in range(FRAME_HEIGHT):
        offset = start + row * row_bytes
        changed += sum(first[index:index + 3] != second[index:index + 3]
                       for index in range(offset, offset + bar_bytes, 3))
        if first[offset + bar_bytes:offset + row_bytes] != second[offset + bar_bytes:offset + row_bytes]:
            content_equal = False
    return {"content_equal": content_equal, "statusbar_changed_pixels": changed,
            "statusbar_dynamic": True, "statusbar_region": "left 72 pixels of native 864x480 Home"}
