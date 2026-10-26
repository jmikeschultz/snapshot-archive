"""Bounded on-demand RTSP recording; no stream URL is logged or exposed."""

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path

from homeassistant.components.ffmpeg import get_ffmpeg_manager

from .archive import snapshot_directory
from .discovery import discover_stream_source

_LOGGER = logging.getLogger(__name__)
MAX_CLIP_BYTES = 128 * 1024 * 1024
MAX_RECORDERS = 2
STARTUP_ALLOWANCE = 35


async def executor_job(hass, function, *args):
    """Drain filesystem work before allowing cancellation to release ownership."""
    task = asyncio.ensure_future(hass.async_add_executor_job(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def valid_mp4(path: Path) -> bool:
    """Require an MP4 header and a finalized movie atom without reading the file."""
    size = path.stat().st_size
    if not 24 <= size <= MAX_CLIP_BYTES:
        return False
    with path.open("rb") as stream:
        offset = 0
        found = set()
        while offset + 8 <= size:
            stream.seek(offset)
            header = stream.read(8)
            length = int.from_bytes(header[:4], "big")
            atom = header[4:8]
            header_size = 8
            if length == 1:
                length = int.from_bytes(stream.read(8), "big")
                header_size = 16
            elif length == 0:
                length = size - offset
            if length < header_size or offset + length > size:
                return False
            found.add(atom)
            offset += length
        return offset == size and {b"ftyp", b"moov", b"mdat"} <= found


async def stop_process(process):
    """Terminate and reap the RTSP client, escalating to kill if necessary."""
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), 5)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()


async def decodable_mp4(binary, path: Path, timeout: float) -> bool:
    """Decode the entire staged clip, requiring nonempty video and no errors.

    Use the configured FFmpeg, without an additional ffprobe dependency. All
    output is discarded; neither credentials nor decoder diagnostics are logged.
    One decoder thread limits CPU pressure on HA while the recorder slot remains
    occupied. Cancellation during launch still owns and reaps the child.
    """
    process = None
    try:
        async with asyncio.timeout(timeout):
            launching = asyncio.create_task(asyncio.create_subprocess_exec(
                binary, "-nostdin", "-hide_banner", "-loglevel", "error",
                "-xerror", "-abort_on", "empty_output_stream",
                "-err_detect", "explode", "-threads", "1", "-i", str(path),
                "-map", "0:v:0", "-map", "0:a:0?",
                "-threads", "1", "-filter_threads", "1", "-f", "null", "-",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            ))
            try:
                process = await asyncio.shield(launching)
            except asyncio.CancelledError:
                process = await launching
                raise
            return await process.wait() == 0
    except (OSError, ValueError, asyncio.TimeoutError):
        return False
    finally:
        if process is not None:
            await stop_process(process)


class VideoRecorder:
    """Share a small recorder limit across all selected devices."""

    def __init__(self, hass, seconds: int, min_free_gb: int):
        self.hass = hass
        self.seconds = seconds
        self.min_free_bytes = min_free_gb * 1024 ** 3
        self.running = 0

    async def record(self, device_id: str, archive: str, day: str, stem: str) -> bool:
        source = discover_stream_source(self.hass, device_id)
        if source is None:
            _LOGGER.warning("Video skipped for %s: no Ring-MQTT live source", device_id)
            return False
        # Never queue a stale motion recording behind other cameras.
        if self.running >= MAX_RECORDERS:
            _LOGGER.warning("Video skipped for %s: recorder capacity reached", device_id)
            return False
        self.running += 1
        stage = None
        process = None
        try:
            def prepare():
                directory = snapshot_directory({"archive": archive}, day)
                directory.mkdir(parents=True, exist_ok=True)
                if shutil.disk_usage(directory).free < self.min_free_bytes + MAX_CLIP_BYTES:
                    return None
                return Path(tempfile.mkdtemp(prefix=".video-", dir=directory))

            # Keep stage ownership even if cancellation arrives during preparation.
            preparing = asyncio.ensure_future(self.hass.async_add_executor_job(prepare))
            try:
                stage = await asyncio.shield(preparing)
            except asyncio.CancelledError:
                stage = await preparing
                raise
            if stage is None:
                _LOGGER.warning("Video skipped for %s: free-space reserve reached", device_id)
                return False
            directory = stage.parent
            pending = stage / "clip.mp4"
            binary = get_ffmpeg_manager(self.hass).binary
            command = (
                binary, "-nostdin", "-hide_banner", "-loglevel", "error",
                "-rtsp_transport", "tcp", "-timeout", "30000000", "-i", source,
                "-t", str(self.seconds), "-map", "0:v:0", "-map", "0:a:0?",
                "-c", "copy", "-movflags", "+faststart", "-fs", str(MAX_CLIP_BYTES),
                "-n", str(pending),
            )
            # Reap even if unload happens while subprocess creation is in flight.
            launching = asyncio.create_task(asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            ))
            try:
                process = await asyncio.shield(launching)
            except asyncio.CancelledError:
                process = await launching
                raise
            async with asyncio.timeout(self.seconds + STARTUP_ALLOWANCE):
                while process.returncode is None:
                    try:
                        await asyncio.wait_for(process.wait(), 1)
                    except asyncio.TimeoutError:
                        free = await executor_job(self.hass, lambda: shutil.disk_usage(directory).free)
                        if free < self.min_free_bytes:
                            raise OSError("Free-space reserve reached")
            if process.returncode != 0:
                _LOGGER.warning("Video recording failed for %s (exit %s)", device_id, process.returncode)
                return False

            if not await executor_job(self.hass, valid_mp4, pending):
                _LOGGER.warning("Video discarded for %s: invalid MP4 container", device_id)
                return False
            if not await decodable_mp4(binary, pending, max(30, self.seconds * 2)):
                _LOGGER.warning("Video discarded for %s: decode validation failed or timed out", device_id)
                return False

            def publish():
                if not valid_mp4(pending) or pending.stat().st_size >= MAX_CLIP_BYTES:
                    return False
                # Revalidate archive directories before publishing.
                destination = snapshot_directory({"archive": archive}, day) / f"{stem}.mp4"
                if destination.exists() or destination.is_symlink():
                    return False
                os.replace(pending, destination)
                return True

            saved = await executor_job(self.hass, publish)
            if saved:
                _LOGGER.info("Video saved for %s: %s/%s.mp4", device_id, day, stem)
            else:
                _LOGGER.warning("Video recording invalid or oversized for %s", device_id)
            return saved
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, asyncio.TimeoutError):
            # Exceptions may include RTSP credentials, so do not log their text.
            _LOGGER.warning("Video recording failed or timed out for %s", device_id)
            return False
        finally:
            try:
                if process is not None:
                    await stop_process(process)
                if stage is not None:
                    await executor_job(self.hass, shutil.rmtree, stage)
            finally:
                self.running -= 1
