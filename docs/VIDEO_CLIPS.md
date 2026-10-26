# Video clips — 0.3.0 feature branch

Implemented optional Ring-MQTT on-demand live clips using the existing selected
snapshot devices and each device's Info sensor stream source. No new Generic
Camera entities or YAML automations are required. Existing configurations remain
snapshot-only until video devices are selected through integration options.

## Validation performed locally

- 32 backend checks pass. Existing archive, image API, and setup checks are retained.
- Real child processes exercise publication, failure, timeout, cancellation,
  termination/reaping, and cleanup; controlled HA boundary substitutes exercise
  concurrent snapshot/video failure isolation and event protection.
- Covers configured-device selection, disabled/malformed stream sources, finalized
  MP4 structure, free-space reserve, recorder capacity, independent retention,
  staging cleanup, video-only events, paired deletion, active capture conflicts,
  bounded API reads, symlink/nonfile rejection, and cancelled HA executor futures.
- Chromium gallery checks pass using the installed Zen UI fixture: unchanged
  heatmap pixels; existing image/deletion behavior; lazy MP4 fetch and actual decode;
  video-only playback; authentication errors; aborted loads and object URL cleanup.
- The tiny MP4 fixture is a generated one-second green frame, with no camera footage.

## Previous camera feasibility test

The actual Ambler doorbell's live RTSP source was recorded by FFmpeg on beefy through
an SSH tunnel. It produced a 10.03-second, 5,740,533-byte H.264/AAC clip at 1920×1920.
Ring-MQTT logged automatic stream deactivation immediately after disconnection.
The user judged playback quality acceptable despite decoder/timestamp warnings.
This does not establish operation of the new integration inside HA.

## HA deployment — 2026-10-14

- Installed 0.3.0 after preserving the previous integration, config entries,
  and Lovelace resources under `/config/snapshot_archive_backups/pre-video-20261014/`.
- `ha core check` passed before the requested restart.
- The user subsequently confirmed that video works on HA. They observed that
  footage starts about three seconds late; that delay has not been instrumented.
- After this live test, all 15 installed integration files matched the feature
  branch byte-for-byte, including the frontend, translations, and README.
- This confirmation does not establish all-camera operation, subsequent motion
  notifications, or cancellation/retention behavior on the actual HA device.

## Detailed live checks / follow-up checklist

1. Back up the installed integration, frontend resources, config entry, and archive.
2. Install the 0.3.0 integration and restart HA to register the new API/dependency.
3. Check startup logs and options UI; initially enable video only for Ambler.
4. Run `snapshot_archive.capture` targeting `camera.ambler_doorbell_snapshot`.
5. Verify paired files on HA, measured size/duration, gallery authenticated playback,
   automatic stream shutdown, and preservation of the existing archive.
6. Verify a real Ambler motion event and a subsequent event after stream shutdown.
7. Reload during a disposable capture to verify process/staging cleanup on HA.

Do not describe local tests or the beefy recording as live integration validation.
For rollback, restore the backed-up integration/resource configuration and restart.
Keep video disabled until the live recording check succeeds.

## Decode validation — 0.4.2, 2026-10-26

New captures must pass both MP4 structure checks and a full FFmpeg decode before
atomic publication. Validation requires a nonempty video stream, decodes optional
audio too, and fails on decode errors. It uses one decoder thread and a wall-clock
deadline of max(30 seconds, twice the configured recording duration), with the
existing recorder slot held until validation/cleanup completes. Timeout and unload
terminate/reap the decoder. A rejected clip is removed with its staging directory;
the independently captured JPEG remains. Gallery metadata then has no video and
renders no video play button. The Last Activity card's archive camera button is
independent and remains visible when configured.

- 39 backend checks passed, including actual FFmpeg decoding of the valid fixture,
  damaged frame payloads, structurally plausible but unplayable containers, and
  audio-only MP4s; decode timeout/cancellation; successful publication; and a real
  rejected-clip capture retaining its JPEG and image-only API metadata.
- Existing recordings are not scanned or removed. Validation proves FFmpeg can
  decode a new clip on HA, not that every browser/device supports its codecs.
- Deployed after backing up 0.4.1 and Lovelace resources under
  `/config/snapshot_archive_backups/pre-video-validation-20261026/`.
  Installed code checksums match local; `ha core check` and restart succeeded;
  frontend resource registered as 0.4.2. Post-restart filtered logs showed a
  skipped video for a device without a Ring-MQTT live source, with no setup errors.
- New real-camera decode validation and hardware CPU cost remain for user testing;
  no manual camera capture or existing-archive cleanup was performed.
