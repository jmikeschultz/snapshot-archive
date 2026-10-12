
"""Age-based and size-based snapshot retention."""

import logging
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

ARCHIVE_ROOT = Path("/media/snapshot_archive")

DEFAULT_RETENTION_DAYS = 365
DEFAULT_MAX_SIZE_GB = 10

BYTES_PER_GB = 1024 ** 3


def _cleanup(retention_days: int, max_size_gb: int) -> tuple[int, int]:
    """Delete expired snapshots, then oldest images over the size limit."""

    if not ARCHIVE_ROOT.is_dir():
        return 0, 0

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(days=retention_days)
    ).timestamp()

    limit_bytes = max_size_gb * BYTES_PER_GB

    images = []
    total_bytes = 0
    deleted = 0

    # Discover files only within the archive.
    for camera_dir in ARCHIVE_ROOT.iterdir():
        if not camera_dir.is_dir() or camera_dir.is_symlink():
            continue

        for day_dir in camera_dir.iterdir():
            if not day_dir.is_dir() or day_dir.is_symlink():
                continue

            for image in day_dir.iterdir():
                if (
                    image.is_symlink()
                    or not image.is_file()
                    or image.suffix.lower() not in (".jpg", ".jpeg")
                ):
                    continue

                try:
                    stat = image.stat()
                except OSError:
                    _LOGGER.exception(
                        "Cannot inspect snapshot %s", image
                    )
                    continue

                if stat.st_mtime < cutoff:
                    try:
                        image.unlink()
                        deleted += 1
                    except OSError:
                        _LOGGER.exception(
                            "Cannot delete expired snapshot %s",
                            image,
                        )
                        total_bytes += stat.st_size
                        images.append((stat.st_mtime, image, stat.st_size))
                    continue

                images.append(
                    (stat.st_mtime, image, stat.st_size)
                )
                total_bytes += stat.st_size

    # Remove oldest images first when over the storage budget.
    if total_bytes > limit_bytes:
        images.sort(key=lambda item: item[0])

        for _, image, size in images:
            if total_bytes <= limit_bytes:
                break

            try:
                image.unlink()
                total_bytes -= size
                deleted += 1
            except OSError:
                _LOGGER.exception(
                    "Cannot delete snapshot %s", image
                )

    # Remove empty date and camera directories.
    for camera_dir in ARCHIVE_ROOT.iterdir():
        if not camera_dir.is_dir() or camera_dir.is_symlink():
            continue

        for day_dir in camera_dir.iterdir():
            if not day_dir.is_dir() or day_dir.is_symlink():
                continue

            try:
                if not any(day_dir.iterdir()):
                    day_dir.rmdir()
            except OSError:
                pass

        try:
            if not any(camera_dir.iterdir()):
                camera_dir.rmdir()
        except OSError:
            pass

    return deleted, total_bytes


async def async_cleanup(
    hass: HomeAssistant,
    retention_days: int,
    max_size_gb: int,
) -> None:
    """Run archive cleanup in the executor."""

    try:
        job = asyncio.ensure_future(hass.async_add_executor_job(_cleanup, retention_days, max_size_gb))
        try:
            deleted, remaining = await asyncio.shield(job)
        except asyncio.CancelledError:
            await job
            raise

        _LOGGER.info(
            "Snapshot Archive cleanup: deleted %d images, "
            "%.2f GB remaining, limit %d GB, retention %d days",
            deleted,
            remaining / BYTES_PER_GB,
            max_size_gb,
            retention_days,
        )

    except Exception:
        _LOGGER.exception(
            "Snapshot Archive cleanup failed"
        )
