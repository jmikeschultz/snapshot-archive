"""Independent image/video budgets with active-event protection."""

import asyncio
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DEFAULT_VIDEO_RETENTION_DAYS, DEFAULT_VIDEO_MAX_SIZE_GB

_LOGGER = logging.getLogger(__name__)
ARCHIVE_ROOT = Path("/media/snapshot_archive")
DEFAULT_RETENTION_DAYS = 365
DEFAULT_MAX_SIZE_GB = 10
BYTES_PER_GB = 1024 ** 3


def _cleanup(retention_days, max_size_gb, video_days=DEFAULT_VIDEO_RETENTION_DAYS,
             video_gb=DEFAULT_VIDEO_MAX_SIZE_GB, active_events=frozenset()):
    """Remove oldest completed files within each budget, retaining active events."""
    if not ARCHIVE_ROOT.is_dir() or ARCHIVE_ROOT.is_symlink():
        return 0, 0
    now = datetime.now(timezone.utc).timestamp()
    policies = {"image": (retention_days, max_size_gb), "video": (video_days, video_gb)}
    files = {kind: [] for kind in policies}
    totals = {kind: 0 for kind in policies}
    deleted = 0

    def remove(path):
        nonlocal deleted
        try:
            path.unlink()
            deleted += 1
            return True
        except OSError:
            _LOGGER.warning("Cannot remove archive file %s", path)
            return False

    for camera in ARCHIVE_ROOT.iterdir():
        if camera.is_symlink() or not camera.is_dir():
            continue
        for day in camera.iterdir():
            if day.is_symlink() or not day.is_dir():
                continue
            for path in day.iterdir():
                if path.is_symlink():
                    continue
                try:
                    metadata = path.stat()
                    # Stage directories are private, and abandoned ones are only
                    # removed after a day (well beyond the recorder's deadline).
                    if path.is_dir() and path.name.startswith(".video-"):
                        if metadata.st_mtime < now - 86400:
                            shutil.rmtree(path)
                        continue
                    if not path.is_file():
                        continue
                    kind = "image" if path.suffix.lower() in (".jpg", ".jpeg") else "video" if path.suffix.lower() == ".mp4" else None
                    if kind is None:
                        continue
                    active = (camera.name, day.name, path.stem) in active_events
                    age, _ = policies[kind]
                    if not active and metadata.st_mtime < now - age * 86400 and remove(path):
                        continue
                    totals[kind] += metadata.st_size
                    if not active:
                        files[kind].append((metadata.st_mtime, path, metadata.st_size))
                except OSError:
                    _LOGGER.warning("Cannot inspect archive file %s", path)

    for kind, (_, budget) in policies.items():
        for _, path, size in sorted(files[kind]):
            if totals[kind] <= budget * BYTES_PER_GB:
                break
            if remove(path):
                totals[kind] -= size

    for camera in ARCHIVE_ROOT.iterdir():
        if camera.is_symlink() or not camera.is_dir():
            continue
        for day in camera.iterdir():
            if day.is_symlink() or not day.is_dir():
                continue
            try:
                day.rmdir()
            except OSError:
                pass
        try:
            camera.rmdir()
        except OSError:
            pass
    return deleted, sum(totals.values())


async def async_cleanup(hass: HomeAssistant, retention_days, max_size_gb,
                        video_days=DEFAULT_VIDEO_RETENTION_DAYS,
                        video_gb=DEFAULT_VIDEO_MAX_SIZE_GB, active_events=frozenset()):
    """Drain executor cleanup on cancellation so reload cannot overlap it."""
    try:
        task = asyncio.ensure_future(hass.async_add_executor_job(
            _cleanup, retention_days, max_size_gb, video_days, video_gb, active_events))
        try:
            deleted, remaining = await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise
        _LOGGER.info("Archive cleanup: removed %d files; %.2f GiB remaining", deleted, remaining / BYTES_PER_GB)
    except Exception:
        _LOGGER.exception("Archive cleanup failed")
