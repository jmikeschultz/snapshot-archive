
"""Authenticated HTTP API for Snapshot Archive."""

import logging
import re
import os
from datetime import date
from pathlib import Path

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, CONF_DEVICES
from .archive import ARCHIVE_ROOT, archive_name, snapshot_directory
from .discovery import discover_camera_entities

_LOGGER = logging.getLogger(__name__)

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
IMAGE_PATTERN = re.compile(
    r"^\d{2}-\d{2}-\d{2}-\d{6}\.jpe?g$",
    re.IGNORECASE,
)


def configured_cameras(hass):
    """Return selected cameras across configuration entries."""
    registry = dr.async_get(hass)
    cameras = {}

    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.disabled_by is not None:
            continue

        device_ids = entry.options.get(
            CONF_DEVICES,
            entry.data.get(CONF_DEVICES, []),
        )

        for device_id in device_ids:
            device = registry.async_get(device_id)
            if device is None:
                continue

            name = device.name_by_user or device.name or device_id

            cameras[device_id] = {
                "device_id": device_id,
                "name": name,
                "archive": hass.data.get(f"{DOMAIN}_directories", {}).get(device_id, archive_name(name)),
                **discover_camera_entities(hass, device_id),
            }

    return cameras


def validate_date(value):
    """Validate a calendar date."""
    if not DATE_PATTERN.fullmatch(value):
        raise web.HTTPBadRequest(text="Invalid date")

    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise web.HTTPBadRequest(text="Invalid date") from exc

    return value


def camera_for_request(hass, device_id):
    """Require a configured camera."""
    camera = configured_cameras(hass).get(device_id)

    if camera is None:
        raise web.HTTPNotFound(text="Camera not found")

    return camera


def list_snapshots(directory, device_id, day):
    """List JPEGs for a camera and day."""
    if not directory.is_dir():
        return []

    snapshots = []

    for path in directory.iterdir():
        if (
            not path.is_file()
            or path.is_symlink()
            or not IMAGE_PATTERN.fullmatch(path.name)
        ):
            continue

        try:
            stat = path.stat()
        except OSError:
            continue

        snapshots.append({
            "filename": path.name,
            "size_bytes": stat.st_size,
            "timestamp": stat.st_mtime,
            "url": (
                f"/api/snapshot_archive/image/"
                f"{device_id}/{day}/{path.name}"
            ),
        })

    snapshots.sort(
        key=lambda item: item["filename"], reverse=True
    )

    return snapshots


class SnapshotArchiveCamerasView(HomeAssistantView):
    """List configured cameras."""

    url = "/api/snapshot_archive/cameras"
    name = "api:snapshot_archive:cameras"
    requires_auth = True

    async def get(self, request):
        hass = request.app["hass"]
        cameras = configured_cameras(hass)

        return self.json({
            "cameras": list(cameras.values()),
        })


class SnapshotArchiveDayView(HomeAssistantView):
    """List snapshots for a selected day."""

    url = "/api/snapshot_archive/{device_id}/{day}"
    name = "api:snapshot_archive:day"
    requires_auth = True

    async def get(self, request, device_id, day):
        hass = request.app["hass"]

        camera = camera_for_request(hass, device_id)
        day = validate_date(day)
        def read_day():
            return list_snapshots(snapshot_directory(camera, day), device_id, day)

        try:
            snapshots = await hass.async_add_executor_job(read_day)
        except PermissionError as exc:
            raise web.HTTPForbidden(text="Invalid archive path") from exc
        except OSError as exc:
            _LOGGER.exception("Cannot list archive")
            raise web.HTTPInternalServerError(text="Cannot read archive") from exc

        return self.json({
            "device_id": device_id,
            "camera": camera["name"],
            "date": day,
            "count": len(snapshots),
            "snapshots": snapshots,
        })


class SnapshotArchiveImageView(HomeAssistantView):
    """Serve or delete an archived JPEG for authenticated clients."""

    url = (
        "/api/snapshot_archive/image/"
        "{device_id}/{day}/{filename}"
    )
    name = "api:snapshot_archive:image"
    requires_auth = True

    async def get(self, request, device_id, day, filename):
        hass = request.app["hass"]

        camera = camera_for_request(hass, device_id)
        day = validate_date(day)

        if not IMAGE_PATTERN.fullmatch(filename):
            raise web.HTTPBadRequest(
                text="Invalid image filename"
            )

        def read_image():
            directory = snapshot_directory(camera, day)
            image = directory / filename
            # O_NOFOLLOW closes the final-component symlink race.
            if image.is_symlink():
                raise PermissionError("Symlink snapshot")
            descriptor = os.open(image, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                import stat
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise PermissionError("Not a regular snapshot")
                return stream.read()

        try:
            content = await hass.async_add_executor_job(
                read_image
            )
        except FileNotFoundError as exc:
            raise web.HTTPNotFound(
                text="Snapshot not found"
            ) from exc

        except PermissionError as exc:
            raise web.HTTPForbidden(text="Invalid archive path") from exc
        except OSError as exc:
            _LOGGER.exception("Cannot read snapshot")
            raise web.HTTPInternalServerError(text="Cannot read snapshot") from exc

        return web.Response(
            body=content,
            content_type="image/jpeg",
            headers={
                "Cache-Control": "private, max-age=3600",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def delete(self, request, device_id, day, filename):
        """Delete only the requested regular JPEG in a configured archive."""
        hass = request.app["hass"]
        camera = camera_for_request(hass, device_id)
        day = validate_date(day)
        if not IMAGE_PATTERN.fullmatch(filename):
            raise web.HTTPBadRequest(text="Invalid image filename")

        def delete_image():
            import stat

            directory = snapshot_directory(camera, day)
            # Pin the directory while checking and unlinking the filename.
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                metadata = os.stat(filename, dir_fd=descriptor, follow_symlinks=False)
                if not stat.S_ISREG(metadata.st_mode):
                    raise PermissionError("Not a regular snapshot")
                os.unlink(filename, dir_fd=descriptor)
            finally:
                os.close(descriptor)

        try:
            await hass.async_add_executor_job(delete_image)
        except FileNotFoundError as exc:
            raise web.HTTPNotFound(text="Snapshot not found") from exc
        except PermissionError as exc:
            raise web.HTTPForbidden(text="Invalid archive path") from exc
        except OSError as exc:
            _LOGGER.exception("Cannot delete snapshot")
            raise web.HTTPInternalServerError(text="Cannot delete snapshot") from exc

        _LOGGER.info("Snapshot Archive deleted %s/%s/%s", device_id, day, filename)
        return web.Response(status=204, headers={"Cache-Control": "no-store"})


def register_api(hass):
    """Register the HTTP endpoints once."""
    if hass.data.get(f"{DOMAIN}_api_registered"):
        return
    hass.http.register_view(SnapshotArchiveCamerasView())
    hass.http.register_view(SnapshotArchiveDayView())
    hass.http.register_view(SnapshotArchiveImageView())

    hass.data[f"{DOMAIN}_api_registered"] = True
    _LOGGER.info("Snapshot Archive HTTP API registered")
