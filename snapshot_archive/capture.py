"""Motion-triggered snapshot capture."""

import asyncio
import logging
import os
from homeassistant.util import dt as dt_util
from pathlib import Path

from homeassistant.components.camera import async_get_image
from homeassistant.const import STATE_ON
from .archive import snapshot_directory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

_LOGGER = logging.getLogger(__name__)

ARCHIVE_ROOT = Path("/media/snapshot_archive")
SNAPSHOT_TIMEOUT = 30
IMAGE_RETRY_DELAY = 1
IMAGE_RETRIES = 5


class SnapshotCapture:
    """Capture snapshots for one camera device."""

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        motion_entity: str,
        button_entity: str,
        camera_entity: str,
        archive: str,
    ) -> None:
        self.hass = hass
        self.name = name
        self.motion_entity = motion_entity
        self.button_entity = button_entity
        self.camera_entity = camera_entity
        self.archive = archive
        self.on_saved = None

        self._task = None
        self._unsubscribe = None

    def start(self):
        """Start listening for motion."""

        @callback
        def motion_changed(event):
            old = event.data.get("old_state")
            new = event.data.get("new_state")

            if new is None or new.state != STATE_ON:
                return

            if old is not None and old.state == STATE_ON:
                return

            if self._task is not None and not self._task.done():
                _LOGGER.debug(
                    "Capture already running for %s",
                    self.name,
                )
                return

            self.request_capture()

        self._unsubscribe = async_track_state_change_event(
            self.hass,
            [self.motion_entity],
            motion_changed,
        )

        _LOGGER.info(
            "Snapshot Archive monitoring %s (%s)",
            self.name,
            self.motion_entity,
        )

    @callback
    def request_capture(self):
        """Share one in-flight task between motion and manual capture."""
        if self._task is None or self._task.done():
            self._task = self.hass.async_create_task(self.capture())
        return self._task

    async def capture(self):
        """Request a snapshot and save the updated image."""

        loop = asyncio.get_running_loop()
        updated = loop.create_future()

        @callback
        def camera_changed(event):
            if not updated.done():
                updated.set_result(True)

        unsubscribe = async_track_state_change_event(
            self.hass,
            [self.camera_entity],
            camera_changed,
        )

        try:
            # Subscribe before requesting the snapshot so we
            # don't miss a fast camera update.
            async with asyncio.timeout(SNAPSHOT_TIMEOUT):
                await self.hass.services.async_call(
                    "button", "press", {"entity_id": self.button_entity}, blocking=True,
                )

            try:
                await asyncio.wait_for(
                    updated,
                    timeout=SNAPSHOT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                _LOGGER.warning(
                    "No snapshot camera update for %s "
                    "within %d seconds",
                    self.name,
                    SNAPSHOT_TIMEOUT,
                )
                return

            # Camera updates can precede image availability.
            image = None

            for attempt in range(IMAGE_RETRIES):
                try:
                    async with asyncio.timeout(SNAPSHOT_TIMEOUT):
                        image = await async_get_image(self.hass, self.camera_entity)
                    if image.content:
                        break
                except Exception:
                    _LOGGER.debug(
                        "Image retrieval attempt %d failed for %s",
                        attempt + 1,
                        self.name,
                        exc_info=True,
                    )

                await asyncio.sleep(IMAGE_RETRY_DELAY)

            if image is None or not image.content:
                _LOGGER.error(
                    "Could not retrieve snapshot for %s",
                    self.name,
                )
                return

            if not image.content.startswith(b"\xff\xd8"):
                raise ValueError("Camera returned a non-JPEG image")
            now = dt_util.now()
            day = now.strftime("%Y-%m-%d")
            filename = ARCHIVE_ROOT / self.archive / day / (now.strftime("%H-%M-%S-%f") + ".jpg")

            def write_image():
                directory = snapshot_directory({"archive": self.archive}, day)
                directory.mkdir(parents=True, exist_ok=True)
                temporary = filename.with_suffix(".tmp")
                try:
                    with temporary.open("xb") as stream:
                        stream.write(image.content)
                    os.replace(temporary, filename)
                finally:
                    temporary.unlink(missing_ok=True)

            write_task = asyncio.ensure_future(self.hass.async_add_executor_job(write_image))
            try:
                await asyncio.shield(write_task)
            except asyncio.CancelledError:
                await write_task
                raise

            _LOGGER.info(
                "Snapshot Archive saved %s",
                filename,
            )

            if self.on_saved is not None:
                await self.on_saved()
            return True

        except asyncio.CancelledError:
            raise

        except Exception:
            _LOGGER.exception(
                "Snapshot capture failed for %s",
                self.name,
            )

        finally:
            unsubscribe()

    async def stop(self):
        """Stop monitoring and cancel outstanding capture."""

        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

        if self._task is not None and not self._task.done():
            self._task.cancel()

            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._task = None