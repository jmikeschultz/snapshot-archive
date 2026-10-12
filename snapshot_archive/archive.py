"""Stable archive directories, shared by capture and API."""

import re
from pathlib import Path

from homeassistant.helpers.storage import Store

from .const import DOMAIN

ARCHIVE_ROOT = Path("/media/snapshot_archive")


def archive_name(name):
    return re.sub(r"[^a-z0-9_-]+", "_", name.lower()).strip("_")


async def async_prepare_archives(hass, devices):
    """Preserve existing directories and persist identity across renames."""
    store = Store(hass, 1, f"{DOMAIN}.directories")
    mapping = await store.async_load() or {}

    def prepare():
        for device_id, name in devices.items():
            if device_id in mapping:
                continue
            legacy = archive_name(name)
            unique = sum(archive_name(n) == legacy for n in devices.values()) == 1
            mapping[device_id] = (
                legacy if legacy and unique and legacy not in mapping.values()
                and (ARCHIVE_ROOT / legacy).is_dir() else device_id
            )

    await hass.async_add_executor_job(prepare)
    await store.async_save(mapping)
    hass.data[f"{DOMAIN}_directories"] = mapping
    return mapping


def snapshot_directory(camera, day):
    """Reject symlinks in every archive path component (executor only)."""
    name = camera["archive"]
    if not name or not re.fullmatch(r"[a-z0-9_-]+", name):
        raise PermissionError("Invalid camera archive")
    directory = ARCHIVE_ROOT / name / day
    if any(path.is_symlink() for path in (ARCHIVE_ROOT, directory.parent, directory)):
        raise PermissionError("Symlink archive paths are forbidden")
    return directory
