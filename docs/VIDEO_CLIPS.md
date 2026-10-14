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

## Live deployment checks still required

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
