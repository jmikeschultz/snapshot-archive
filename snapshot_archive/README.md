# Snapshot Archive 0.4.1

Motion requests a fresh snapshot from each selected device's snapshot button,
waits for the snapshot camera update, retrieves a JPEG, and writes it atomically
under `/media/snapshot_archive/<camera-directory>/<HA-local-date>/`.
Defaults: 365 days and 10 GiB across the whole archive. Cleanup runs on startup,
daily, and after successful captures. Files are removed oldest first by mtime.

Selected devices need enabled motion, snapshot button, and snapshot camera
entities. Configure additional devices in the integration options.

## Optional live clips

Under Settings → Devices & services → Snapshot Archive → Configure, select
video devices from the same devices already selected for snapshot archiving.
Leave the video selection empty to retain snapshot-only behavior. Existing
entries default to video disabled; no migration or dashboard changes are needed.

Video support currently targets Ring-MQTT devices. At capture time, the integration
reads the enabled Info sensor's `stream_Source` RTSP attribute ending in `_live`.
It does not expose the URL through its API or logs, and does not require Generic
Camera entities, helper templates, separate motion automations, or Ring stored-video
playback. Live video still passes through Ring's cloud. There is no pre-event buffer.

Settings:

| Option | Default | Scope |
| --- | --- | --- |
| Video devices | None | Subset of selected snapshot devices |
| Clip duration | 10 seconds | 5–60 seconds; recorded duration may vary |
| Video retention | 7 days | Across the video archive |
| Video size limit | 2 GiB | Independent of the snapshot budget |
| Minimum free space | 5 GiB | Video starts only with an additional 128 MiB headroom |

Snapshot and video jobs start concurrently and share a trigger-time filename.
A failed clip does not discard the snapshot; a failed snapshot does not discard
a successful clip. Each camera shares one in-flight event task, and at most two
recorders run simultaneously across the entry. Additional recording requests are
skipped rather than queued for stale footage. Manual capture uses the same policy.

The recorder uses Home Assistant's configured FFmpeg binary with RTSP-over-TCP,
copies H.264/AAC streams without re-encoding, and saves MP4s under the existing
camera/date directory. Each clip has a 128 MiB hard ceiling and a duration-plus-35-second
wall-clock deadline. Free space is checked during recording. Pending clips live
in private `.video-*` staging directories and are published atomically only after
FFmpeg exits successfully and MP4 container finalization is verified. Validation
checks container structure, not every decoded frame. FFmpeg stderr is discarded
to prevent stream credentials from leaking into logs.

Entry unload/shutdown terminates and reaps recording processes and removes staging
files. Abandoned staging directories older than one day are cleaned up during
retention. Completed MP4s are deleted oldest first when either their age or size
budget is exceeded. Active events are protected; concurrent clips may briefly
exceed a size budget until finalization and cleanup. Snapshot and video budgets
are independent: account for both plus database, apps, and local backups.

Ring live streaming can interrupt motion notifications while active. Before
broadly enabling video, verify startup delay, stream shutdown, and subsequent
motion notifications on the actual camera. For background see
[Ring-MQTT streaming](https://github.com/tsightler/ring-mqtt/wiki/Video-Streaming).

## Gallery

The integration automatically registers its frontend module as a Lovelace
resource in storage mode, so it loads after Home Assistant initializes its
custom-element registry. In YAML resource mode, register
`/snapshot_archive_static/snapshot-archive-gallery.js?v=0.4.1&resource` as a
module explicitly if the wrapper is unavailable. HACS Zen UI 1.3.0
and its gzip bundle are unchanged. Replace only the camera heatmap's type and
add an explicit camera mapping; preserve all other existing Zen UI settings:

```yaml
type: custom:snapshot-archive-heatmap
card: heatmap
entity: sensor.camera_motion_activity
title: Camera Motion
days: 90
snapshot_archive:
  camera: camera.example_snapshot
```

`snapshot_archive.camera` accepts a configured camera entity ID or device ID.
It never guesses a camera from an activity sensor's name. Every camera heatmap
needs its own mapping. Unrelated heatmaps continue to use `custom:zen-ui`.

The gallery displays newest images first, loads up to 48 at a time with four
concurrent authenticated requests, and opens full-resolution images on click.
Date cells support Enter/Space; Escape closes dialogs. Closing aborts pending
requests and releases image object URLs. Requests time out after 30 seconds.
Events with a finalized MP4 have a play button. Clips are fetched with HA
authentication only when clicked and played through a temporary browser blob URL.
Closing the player aborts pending loading, stops playback, and releases that URL.
Video-only events show a playable placeholder if their image failed or expired.

Each event has a small trash-can button beside its timestamp that permanently removes
its JPEG and associated MP4. Confirmation explicitly mentions the clip when present.
Deleting a currently capturing event returns 409; try again after it finishes. After a
successful deletion, the selected date is fetched again and the gallery and
count refresh automatically. Failed deletions preserve the image and show an
error. A concurrently removed image also triggers a refresh.

Empty dates, unavailable cameras, authentication failures, and server/image
errors are displayed in the dialog. Image URLs never contain tokens, and JPEGs
remain outside the public `/local` directory.

Zen UI 1.3.0 has no public date-click event. The wrapper's isolated `openCell`
adapter uses the existing cell hover handler to read the exact rendered date,
then restores the hover state. After a Zen UI upgrade, validate rolling/year
ranges and date clicks; an incompatible adapter reports an error. The wrapper
does not patch Zen UI's prototype or modify its files.

## Authenticated API

- `GET /api/snapshot_archive/cameras`: configured devices and discovered entities.
- `GET /api/snapshot_archive/<device_id>/<YYYY-MM-DD>`: newest-first event metadata, with optional image and video URLs.
- `GET /api/snapshot_archive/image/<device_id>/<date>/<filename>`: authenticated JPEG.
- `GET /api/snapshot_archive/video/<device_id>/<date>/<filename>`: authenticated MP4,
  limited to 128 MiB. The player fetches the whole short clip before playback.
- `DELETE /api/snapshot_archive/image/<device_id>/<date>/<filename>`: authenticated
  event deletion (JPEG plus associated MP4); 204 on success, 404 if both missing,
  409 while capture is active. Video-only events use their synthesized JPEG name.

Calendar dates and filenames are validated. Unconfigured devices return 404;
empty dates return a successful empty list. Symlink directories/images are
rejected. Disk operations run in the executor.

Directory identity is persisted in `.storage/snapshot_archive.directories`.
Existing name-based directories are retained; new devices use their stable
device IDs. This preserves existing snapshots across camera renames and avoids
new name collisions. Preserve this metadata alongside the archive in backups.

## Manual verification

The `snapshot_archive.capture` action takes `camera_entity` and uses the same
capture pipeline as motion without changing sensor states. Concurrent requests
share one capture task. Events for which both capture jobs fail report an action error and log details.
Entry unload cancels captures, unsubscribes timers/listeners, and drains cleanup
jobs; executor writes/cleanup finish before cancellation releases their owners.

## Last Activity card

After installing 0.4.1 and restarting Home Assistant, refresh the browser and choose
**Snapshot Archive: Last Activity** in **Add card**. Its visual editor selects an
activity sensor and customizes the label, camera icon, text size, alignment,
padding, and spacing. The sensor's `last_activity_display` is displayed verbatim;
the card does not generate relative times or change the sensor.

For contact sensors or other activity without pictures, leave the archive camera
empty. No camera button is displayed, and Zen UI is not required for this card.
For camera activity, optionally configure an archive camera entity or device ID
and select the sensor attribute containing the actual last activity timestamp.
The camera button opens the same date gallery as the heatmap, including image
popups, clips, and deletion. It does not promise an image exists for that event.

```yaml
type: custom:snapshot-archive-last-activity
entity: sensor.lakehouse_closet_cam_activity
label: "Last :"
font_size: 14px
alignment: left
padding: 16px
gap: 8px
icon: mdi:camera
# Optional: omit these for activity without an archive camera.
snapshot_archive:
  camera: camera.example_snapshot
timestamp_attribute: last_activity
```

`timestamp_attribute` defaults to `last_activity`; choose the actual attribute
from your sensor in the editor. Supported values are an ISO date (`YYYY-MM-DD`),
an ISO timestamp, or numeric Unix seconds. Timestamps are converted to Home
Assistant's configured time zone to match archive dates. The formatted display
and entity `last_changed` are never used to guess an activity date. A missing or
invalid timestamp produces an explanatory message when the camera is clicked.
An empty `label` hides the prefix. Sizes accept px, rem, or em.

The editor and picker use Home Assistant's standard custom-card interfaces:
https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card

### Optional daily duration

Enable **Show today’s duration** in the visual editor for internet, purifier, or
other Daily Activity sensors with duration tracking. Select off/outage time,
on/running time, or unknown time, and optionally customize the row label.

Internet example:

```yaml
type: custom:snapshot-archive-last-activity
entity: sensor.lakehouse_internet_activity
label: "Last:"
show_duration: true
duration_field: off_seconds
duration_label: "Outage today:"
```

For a purifier, select its activity sensor and choose `on_seconds` with a label
such as `Running today:` (or `off_seconds` for time off). The card reads today's
row in the sensor's `data` attribute, using the sensor's `time_zone` when supplied,
then HA's configured zone. It displays whole seconds as `1h 2m 3s`, updating when
Home Assistant supplies state updates; it does not estimate unreported time.
A missing date/field counts as zero, matching the previous Markdown template.
Missing/unavailable sensors or missing duration data display `Unavailable`.
Existing cards keep the duration row hidden unless `show_duration: true`.
