# Snapshot Archive 0.2.2

Motion requests a fresh snapshot from each selected device's snapshot button,
waits for the snapshot camera update, retrieves a JPEG, and writes it atomically
under `/media/snapshot_archive/<camera-directory>/<HA-local-date>/`.
Defaults: 365 days and 10 GiB across the whole archive. Cleanup runs on startup,
daily, and after successful captures. Files are removed oldest first by mtime.

Selected devices need enabled motion, snapshot button, and snapshot camera
entities. Configure additional devices in the integration options.

## Gallery

The integration automatically registers its frontend module as a Lovelace
resource in storage mode, so it loads after Home Assistant initializes its
custom-element registry. In YAML resource mode, register
`/snapshot_archive_static/snapshot-archive-gallery.js?v=0.2.2&resource` as a
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
Each image has a small trash-can button beside its timestamp that permanently removes that JPEG. After a
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
- `GET /api/snapshot_archive/<device_id>/<YYYY-MM-DD>`: newest-first JPEG metadata.
- `GET /api/snapshot_archive/image/<device_id>/<date>/<filename>`: authenticated JPEG.
- `DELETE /api/snapshot_archive/image/<device_id>/<date>/<filename>`: authenticated
  permanent deletion; 204 on success, 404 if already missing.

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
share one capture task. Failed captures report an action error and log details.
Entry unload cancels captures, unsubscribes timers/listeners, and drains cleanup
jobs; executor writes/cleanup finish before cancellation releases their owners.
