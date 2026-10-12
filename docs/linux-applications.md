# Original applications on Linux

[简体中文](linux-applications.zh-CN.md) · [Native window](linux-native.md) · [Validation record](linux-applications-validation.json)

The original Calendar can save a local event across a normal guest restart, and the original task cards can resume Notes and Calculator and close one card independently. Clock has a smaller verified scope; Gallery photo browsing remains blocked. These checks used the Linux native window on 2026-10-11, with the source tree at [`3537ae9`](https://github.com/YZune/harmattan-qemu/commit/3537ae96371b8ba2f550bbd54aee91eedc65502b).

| Original application or view | Observed result | Important limit |
| --- | --- | --- |
| Calendar (`organiser`) | Create an all-day local event, edit its title/date, reopen the UI and recover the edited event in a new guest process | Screen keyboard required; one reminder-free event tested |
| Clock | Open from Home, observe advancing local time, open the alarm editor and cancel | No saved alarm or multi-city workflow verified |
| Gallery | Opens, but both inspected views show **No items** despite two imported synthetic images | Tracker service-name ownership is denied; discovery, thumbnails and browsing did not pass |
| Home task cards | Resume saved Notes and Calculator `5`, close only Calculator, continue editing Notes, reopen Calculator at `0` | One temporary session; a dimmed Notes thumbnail appeared after card editing |

These are actual guest applications controlled through desktop mouse/keyboard events in Godot, not recreated screens. The host was Linux x86_64 with QEMU 9.1.3, Godot 4.6.3 and DGLES/OSMesa software rendering. Guest networking and audio were off. Application identities and the input hashes are in the validation record. Linked libraries being present does not establish that every original service works.

## Prepare a bounded offline session

Complete the [Linux build and guest preparation](linux.md), DGLES smoke check and [native-window prerequisites](linux-native.md#build-and-launch) first. Keep the exact renderer string reported by your smoke test. Run from a graphical desktop terminal at the repository root, retaining the build variables from that guide. For the Calendar restart check, choose a **new dedicated profile** and a fresh output directory:

```sh
python3 -B scripts/harmattan-qemu/run-linux-ui.py \
  --build-root "$HARMATTAN_LINUX_BUILD" \
  --dgles-runtime "$HARMATTAN_DGLES_ROOT/objs-x86_64" \
  --prepared-root extracted/guest-from-original-media-linux \
  --renderer 'llvmpipe (LLVM 19.1.7, 256 bits)' \
  --compositor-fbo-fix --mode live --frontend "$(command -v godot)" \
  --profile "$PWD/extracted/profiles/linux-app-check" \
  --output "$PWD/extracted/linux-app-check-01" --timeout 1800
```

The renderer above is the recorded value; replace it with your exact smoke result if different. The [compositor correction](gles-framebuffers.md) is already a supported opt-in flag, with its existing identity and call-site checks. The 1–1800 second live budget includes startup. Wait for **Live** before interacting, save in the application and use the frontend **Quit** before the budget ends.

For the second launch, reuse the same profile and change the output to a fresh path such as `extracted/linux-app-check-02`. Check `launch-result.json`, `ui/startup-result.json` and `ui/interactive-exit.json`: successful profile acceptance requires normal process exits, `storage.guest_synced=true` and `storage.state=clean`, followed by visibly retained data. A successful launch alone does not prove that an application saved its data.

Profile creation needs space for a sparse base copy, writable disk and checkpoint. Follow [persistent-file guidance](linux-native.md#optional-persistent-files); keep base inputs quiescent and back up the complete profile only while closed. Files surviving normal shutdown do not establish power-loss durability or CPU/RAM save-state. For a disposable task-card check, omit `--profile` and choose another fresh output directory. That mode discards saved guest changes and does not run the profile sync/checkpoint path.

## Calendar local event

1. Open Calendar from Home and choose **No Thanks** if account setup is offered.
2. Select a date and add an event. Enter a synthetic title using the original **on-screen keyboard**. Select **All day**, **Personal**, **Not repeated** and **Reminder None**, then save.
3. Open the event, choose the pencil/edit control, change its title and date, and save again. Check the settled detail view before continuing.
4. Use the original top-edge close gesture and reopen Calendar from Home. Check the new date and the old date.
5. Quit the complete native session normally. Start a new launcher process with the same profile and fresh output directory, then inspect the event again.

The recorded event changed from **Calendar alpha**, 15 October 2026, to **Calendar alpha revised**, 16 October 2026. After UI reopening, the old date showed **No events** and the new date showed one matching all-day event. After a new QEMU process, the exact edited title/date remained visible. This checks those UI views, not database-wide event enumeration. Application-level process destruction was not measured separately from closing/reopening its UI.

Calendar's keyboard has a **Done** action. Its layout is not recognised by the merged host keyboard guard, so host letter entry was not used for this acceptance. Tap the original screen keys in small groups and verify the resulting text. Rapid batches of screen-key clicks lost letters even when pointer requests were acknowledged; their cause remains unresolved. No Backspace was used. The known rapid-backspace/case issue is not fixed by this result. A later local Done-layout experiment is unmerged and is not part of this guide.

Recurring events, reminders, sound, lock-screen wakeup, accounts and calendar synchronisation were not tested.

## Clock inspection

Open Clock from Home. The recorded analog face and status time advanced from 14:49 to 14:51 on 11 October. The original **+** control opened an alarm title/time editor; **Cancel** returned to the empty alarm list. No alarm was saved and no system date/time/timezone setting was changed.

No multi-city management entry was found in this version during the bounded inspection, so the planned city add/delete/restart check was not completed. This is not an established emulator fault or a claim about every N9 application/version. The launcher's existing host-clock synchronisation does not establish the original `timed` service, alarm delivery, sound or wakeup. No second guest was started to test Clock persistence because no persistent city/alarm state had been created.

## Task cards with Notes and Calculator

1. In Notes, save a synthetic note. Return to Home, open Calculator and calculate `2+3=5`.
2. Return to Home and swipe horizontally to the original task-card page. Select each card in turn and check its restored view.
3. Hold the Calculator card until the original **X**, **Done** and **Close all** controls appear. Press only Calculator's **X**, then **Done**.
4. Restore Notes, edit and save it. Return to Home and open Calculator from its icon. Observe its value rather than assuming closed-app state is retained.

The test resumed **Multitask alpha** and Calculator **5** through their cards. After closing Calculator's card, Notes remained editable and saved **Multitask alpha saved**. Reopening Calculator from Home displayed **0**. This proves the observed UI close/reopen flow; application PIDs were not tracked.

After leaving card-edit mode, the remaining Notes thumbnail was dim with a bright upper-right rectangle. Restoring Notes showed a normal full application, and editing/saving then returning produced a normal updated thumbnail. This visual defect remains unresolved. This test used one disposable session and makes no restart or unsaved-text-retention claim.

## Gallery remains blocked

The original Gallery opened after two clearly labelled synthetic PNGs were imported into a dedicated profile. Face recognition was cancelled. Both inspected main views remained at **No items**. The original Tracker log reported `org.freedesktop.DBus.Error.AccessDenied` when trying to own `org.freedesktop.Tracker1`; the rescue session could not resolve the required original Aegis credentials. Image discovery, two thumbnails, opening either image, previous/next navigation and access after a guest restart did not pass. No restart was performed after that first gate failed.

The Gallery run also recorded five XServer `BadValue` messages and an initially corrupted native window. A normal title-bar resize restored the visible window; the cause was not isolated or fixed. Zero counted guest graphics faults does not mean the frontend had no errors.

Separate, **unmerged security research** later stopped at an original `aegisSessionOpen()` platsec-device warning before issuing a Tracker activation. That diagnostic issued **zero Tracker activation requests** and established no Tracker credentials or accepted bus ownership. The warning itself is not proof that the complete original login chain must fail: static inspection shows its warning branch continuing. This later diagnostic neither replaces the earlier Gallery rejection nor supplies a working Gallery fix. It is outside the normal reproduction steps above; no security-loader, permission or policy workaround is provided here.

## What the evidence establishes

Calendar's two sessions, Clock, Gallery and the task-card session all ended with QEMU, controller and frontend exit code 0 and joined graphics workers; counted renderer faults/rejections were zero. The logs separately retain the known original repeated `eglTerminate(NULL)` rejection. Calendar, Clock and Gallery profiles synced and reported clean; the disposable task-card run explicitly reported `guest_synced=false`.

Original media and prepared-input SHA-256 checks matched after the runs. Existing profiles were preserved; the validation record distinguishes full hashes from metadata-only checks. Private logs, screenshots and synthetic profiles remain outside this source distribution. The record contains identities and bounded outcomes without guest binaries, disks, personal data or private host paths.

No production changes were required for these application checks. No new macOS guest run or full host regression suite was performed for them. These results do not establish all applications, full retail security/device services, long-term stability or physical input latency.
