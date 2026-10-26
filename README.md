# Snapshot Archive

A Home Assistant custom integration that captures camera snapshots and optional short live clips on motion,
retains them by age and size, and provides an authenticated gallery through
Zen UI heatmaps. Current integration version: **0.4.1**.

## Installation and configuration

Copy `snapshot_archive/` to `/config/custom_components/snapshot_archive/`,
restart Home Assistant, then add **Snapshot Archive** through Settings →
Devices & services. Select devices with enabled motion, snapshot button, and
snapshot camera entities.

See [integration documentation](snapshot_archive/README.md) for gallery setup,
retention, authenticated APIs, and capture behavior. Video uses the existing selected
Ring-MQTT devices; no Generic Camera entities or per-camera automations are required.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/test_archive.py tests/test_video.py
```

Backend tests use Home Assistant boundary doubles and do not connect to a live
server. The browser regression test uses a local mock server and an installed
Zen UI 1.3.0 bundle. Place that bundle at `tests/fixtures/zen-ui.js` (ignored by
Git), then run:

```sh
.venv/bin/python tests/browser_test.py
```

Chromium defaults to `/usr/bin/chromium`; set `CHROMIUM_PATH` for another path.
The browser test does not connect to Home Assistant.

[Deployment validation notes](docs/VALIDATION.md) record the checks performed
on October 10, 2026. These historical checks do not establish compatibility with later Home Assistant or Zen UI versions.
