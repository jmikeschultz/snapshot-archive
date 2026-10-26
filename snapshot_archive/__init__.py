
"""Snapshot Archive integration."""

import asyncio
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError
import logging
from datetime import timedelta
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from .archive import async_prepare_archives

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_time_interval

from .api import register_api
from .capture import SnapshotCapture
from .const import (
    CONF_CLIP_SECONDS,
    CONF_DEVICES,
    CONF_MIN_FREE_GB,
    CONF_VIDEO_DEVICES,
    CONF_VIDEO_MAX_SIZE_GB,
    CONF_VIDEO_RETENTION_DAYS,
    DEFAULT_CLIP_SECONDS,
    DEFAULT_MIN_FREE_GB,
    DEFAULT_VIDEO_MAX_SIZE_GB,
    DEFAULT_VIDEO_RETENTION_DAYS,
    DOMAIN,
)
from .discovery import discover_camera_entities
from .retention import (
    async_cleanup,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_MAX_SIZE_GB,
)
from .video import VideoRecorder

_LOGGER = logging.getLogger(__name__)

CONF_RETENTION_DAYS = "retention_days"
CONF_MAX_SIZE_GB = "max_size_gb"


def get_setting(entry, key, default=None):
    """Read options with fallback to initial configuration."""
    return entry.options.get(
        key,
        entry.data.get(key, default),
    )


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the HTTP API once per Home Assistant startup."""
    register_api(hass)
    url = "/snapshot_archive_static/snapshot-archive-gallery.js"
    await hass.http.async_register_static_paths([
        StaticPathConfig(url, str(Path(__file__).parent / "frontend" / "snapshot-archive-gallery.js"), False)
    ])
    # Lovelace resources load after HA's scoped custom-element registry.
    # Early extra modules can otherwise lose their element registration.
    resources = hass.data[LOVELACE_DATA].resources
    versioned_url = url + "?v=0.5.0&resource"
    if hasattr(resources, "async_create_item"):
        await resources.async_get_info()
        existing = next((item for item in resources.async_items()
                         if item["url"].split("?")[0] == url), None)
        if existing is None:
            await resources.async_create_item({"url": versioned_url, "res_type": "module"})
        elif existing["url"] != versioned_url:
            await resources.async_update_item(existing["id"], {"url": versioned_url, "res_type": "module"})
    else:
        add_extra_js_url(hass, versioned_url)
        _LOGGER.info("YAML resources: register %s as a module if the wrapper is unavailable", versioned_url)

    async def manual_capture(call):
        camera_entity = call.data["camera_entity"]
        for data in hass.data.get(DOMAIN, {}).values():
            for capture in data["captures"]:
                if capture.camera_entity == camera_entity:
                    if not await asyncio.shield(capture.request_capture()):
                        raise HomeAssistantError("Archive capture failed; check Snapshot Archive logs")
                    return
        raise HomeAssistantError("Camera is not monitored by Snapshot Archive")

    hass.services.async_register(
        DOMAIN, "capture", manual_capture,
        schema=vol.Schema({vol.Required("camera_entity"): str}),
    )
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up Snapshot Archive."""

    register_api(hass)

    device_ids = get_setting(entry, CONF_DEVICES, [])

    retention_days = int(
        get_setting(
            entry,
            CONF_RETENTION_DAYS,
            DEFAULT_RETENTION_DAYS,
        )
    )

    max_size_gb = int(
        get_setting(
            entry,
            CONF_MAX_SIZE_GB,
            DEFAULT_MAX_SIZE_GB,
        )
    )

    video_devices = set(get_setting(entry, CONF_VIDEO_DEVICES, [])) & set(device_ids)
    video_days = int(get_setting(entry, CONF_VIDEO_RETENTION_DAYS, DEFAULT_VIDEO_RETENTION_DAYS))
    video_gb = int(get_setting(entry, CONF_VIDEO_MAX_SIZE_GB, DEFAULT_VIDEO_MAX_SIZE_GB))
    recorder = VideoRecorder(
        hass,
        int(get_setting(entry, CONF_CLIP_SECONDS, DEFAULT_CLIP_SECONDS)),
        int(get_setting(entry, CONF_MIN_FREE_GB, DEFAULT_MIN_FREE_GB)),
    )
    active_events = hass.data.setdefault(f"{DOMAIN}_active_events", set())
    registry = dr.async_get(hass)
    captures = []

    devices = {
        device_id: device.name_by_user or device.name or device_id
        for device_id in device_ids
        if (device := registry.async_get(device_id)) is not None
    }
    directories = await async_prepare_archives(hass, devices)
    cleanup_lock = hass.data.setdefault(f"{DOMAIN}_cleanup_lock", asyncio.Lock())
    cleanup_tasks = set()
    stopping = False

    async def run_cleanup():
        """Prevent overlapping cleanup runs."""
        async with cleanup_lock:
            if stopping:
                return
            await async_cleanup(
                hass,
                retention_days,
                max_size_gb,
                video_days,
                video_gb,
                active_events,
            )

    @callback
    def scheduled_cleanup(_now):
        if not stopping:
            task = hass.async_create_task(run_cleanup())
            cleanup_tasks.add(task)
            task.add_done_callback(cleanup_tasks.discard)

    scheduled_cleanup(None)

    unsubscribe_timer = async_track_time_interval(
        hass,
        scheduled_cleanup,
        timedelta(days=1),
    )

    for device_id in device_ids:
        device = registry.async_get(device_id)

        if device is None:
            _LOGGER.warning(
                "Selected device no longer exists: %s",
                device_id,
            )
            continue

        name = device.name_by_user or device.name or device_id
        entities = discover_camera_entities(hass, device_id)

        missing = [
            key for key, value in entities.items()
            if value is None
        ]

        if missing:
            _LOGGER.warning(
                "Skipping %s: missing %s",
                name,
                ", ".join(missing),
            )
            continue

        capture = SnapshotCapture(
            hass=hass,
            name=name,
            motion_entity=entities["motion"],
            button_entity=entities["snapshot_button"],
            camera_entity=entities["camera"],
            archive=directories[device_id],
            device_id=device_id,
            video_recorder=recorder if device_id in video_devices else None,
        )

        capture.on_saved = run_cleanup
        capture.start()
        captures.append(capture)

    async def stop(_event=None):
        nonlocal stopping
        if stopping:
            return
        stopping = True
        unsubscribe_timer()
        await asyncio.gather(*(capture.stop() for capture in captures))
        if cleanup_tasks:
            await asyncio.gather(*list(cleanup_tasks), return_exceptions=True)

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop))
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "captures": captures,
        "unsubscribe_timer": unsubscribe_timer,
        "stop": stop,
    }

    entry.async_on_unload(
        entry.add_update_listener(async_options_updated)
    )

    _LOGGER.info(
        "Snapshot Archive ready: %d cameras, "
        "%d-day retention, %d GB maximum",
        len(captures),
        retention_days,
        max_size_gb,
    )

    return True


async def async_options_updated(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Reload after configuration changes."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload Snapshot Archive."""

    data = hass.data.get(DOMAIN, {}).pop(
        entry.entry_id, None
    )

    if data is None:
        return True

    await data["stop"]()

    return True
