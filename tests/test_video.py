"""Video lifecycle, archive isolation, and independent image/video retention."""
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web

from test_archive import Hass, put
from snapshot_archive import api, capture, discovery, retention, video


def mp4_bytes():
    def atom(kind, content=b"test"):
        return (8 + len(content)).to_bytes(4, "big") + kind + content
    return atom(b"ftyp") + atom(b"mdat") + atom(b"moov")


@pytest.fixture
def root(tmp_path, monkeypatch):
    from snapshot_archive import archive
    for component in (archive, capture, retention):
        monkeypatch.setattr(component, "ARCHIVE_ROOT", tmp_path)
    return tmp_path


def stream_hass():
    hass = Hass()
    hass.entities = {"one": [SimpleNamespace(domain="sensor", disabled_by=None, entity_id="sensor.info")]}
    hass.states = SimpleNamespace(get=lambda entity: SimpleNamespace(attributes={"stream_Source": "rtsp://bridge:8554/camera_live"}))
    return hass


def test_stream_source_validation():
    hass = stream_hass()
    assert discovery.discover_stream_source(hass, "one") == "rtsp://bridge:8554/camera_live"
    for source in [None, "http://bridge/camera_live", "rtsp://bridge/camera_event", "rtsp://bridge/camera_live\n", "rtsp://[bad/camera_live", "rtsp://bridge/camera_live?token=test"]:
        hass.states.get = lambda entity: SimpleNamespace(attributes={"stream_Source": source})
        assert discovery.discover_stream_source(hass, "one") is None
    hass = stream_hass(); hass.entities["one"][0].disabled_by = "user"
    assert discovery.discover_stream_source(hass, "one") is None


def test_mp4_finalization(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(mp4_bytes()); assert video.valid_mp4(clip)
    clip.write_bytes(mp4_bytes()[:-2]); assert not video.valid_mp4(clip)
    clip.write_bytes(b"not an MP4"); assert not video.valid_mp4(clip)


@pytest.mark.asyncio
async def test_real_subprocess_publish_and_cleanup(root, monkeypatch):
    """A real child process exercises exec, wait, private staging, and publish."""
    hass = stream_hass()
    binary = root / "recorder"
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "Video validation tests require FFmpeg"
    fixture = Path(__file__).parent / "fixtures/clip.mp4"
    binary.write_text(
        f"#!{sys.executable}\nimport os,shutil,sys\n"
        f"if '-rtsp_transport' in sys.argv: shutil.copyfile({str(fixture)!r},sys.argv[-1])\n"
        f"else: os.execv({ffmpeg!r}, [{ffmpeg!r}]+sys.argv[1:])\n"
    )
    binary.chmod(0o700)
    monkeypatch.setattr(video, "get_ffmpeg_manager", lambda hass: SimpleNamespace(binary=str(binary)))
    recorder = video.VideoRecorder(hass, 10, 0)
    assert await recorder.record("one", "camera", "2026-10-10", "12-00-00-000001")
    path = root / "camera/2026-10-10/12-00-00-000001.mp4"
    assert path.read_bytes() == fixture.read_bytes()
    assert not list(root.rglob(".video-*")) and recorder.running == 0


@pytest.mark.asyncio
async def test_failed_process_and_low_space_leave_no_clip(root, monkeypatch):
    hass = stream_hass()
    monkeypatch.setattr(video, "get_ffmpeg_manager", lambda hass: SimpleNamespace(binary="/bin/false"))
    recorder = video.VideoRecorder(hass, 10, 0)
    assert not await recorder.record("one", "camera", "2026-10-10", "12-00-00-000001")
    assert not list(root.rglob("*.mp4")) and not list(root.rglob(".video-*"))
    monkeypatch.setattr(video.shutil, "disk_usage", lambda path: SimpleNamespace(free=1))
    assert not await recorder.record("one", "camera", "2026-10-10", "12-00-00-000001")
    assert recorder.running == 0
    recorder.running = video.MAX_RECORDERS
    assert not await recorder.record("one", "camera", "2026-10-10", "12-00-00-000001")
    assert recorder.running == video.MAX_RECORDERS


@pytest.mark.asyncio
async def test_cancel_reaps_real_child_and_cleans_stage(root, monkeypatch):
    hass = stream_hass()
    binary = root / "recorder"
    binary.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n"); binary.chmod(0o700)
    monkeypatch.setattr(video, "get_ffmpeg_manager", lambda hass: SimpleNamespace(binary=str(binary)))
    original = asyncio.create_subprocess_exec
    launched = asyncio.Event(); processes = []
    async def launch(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process); launched.set()
        return process
    monkeypatch.setattr(video.asyncio, "create_subprocess_exec", launch)
    recorder = video.VideoRecorder(hass, 10, 0)
    task = asyncio.create_task(recorder.record("one", "camera", "2026-10-10", "12-00-00-000001"))
    await launched.wait(); task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert processes[0].returncode is not None
    assert not list(root.rglob(".video-*")) and recorder.running == 0


@pytest.mark.asyncio
async def test_snapshot_survives_video_failure_and_pair_timestamp(root):
    hass = Hass()
    class Recorder:
        async def record(self, device, archive, day, stem):
            assert day == "2026-10-10" and stem == "12-00-00-000000"
            assert (archive, day, stem) in hass.data["snapshot_archive_active_events"]
            raise RuntimeError("Failed recording")
    item = capture.SnapshotCapture(hass, "Camera", "motion", "button", "camera", "camera", "one", Recorder())
    item.start()
    assert await item.request_capture()
    assert list(root.rglob("*.jpg")) and not hass.data["snapshot_archive_active_events"]
    await item.stop()


def test_independent_budgets_active_protection_and_abandoned_stage(root):
    image = put(root, "12-00-00-000001.jpg")
    old_video = put(root, "10-00-00-000001.mp4", mp4_bytes()); os.utime(old_video, (0,0))
    active_video = put(root, "11-00-00-000001.mp4", mp4_bytes()); os.utime(active_video, (0,0))
    stage = image.parent / ".video-abandoned"; stage.mkdir(); (stage / "clip.mp4").write_bytes(b"partial"); os.utime(stage, (0,0))
    outside = root.parent / "outside-stage"; outside.mkdir(); (outside / "keep").write_bytes(b"keep")
    (image.parent / ".video-link").symlink_to(outside, target_is_directory=True)
    retention._cleanup(365, 10, 1, 0, {("camera", "2026-10-10", active_video.stem)})
    assert image.exists() and active_video.exists() and not old_video.exists()
    assert not stage.exists() and (outside / "keep").exists()


@pytest.mark.asyncio
async def test_video_api_pairs_video_only_and_delete(root, monkeypatch):
    monkeypatch.setattr(api, "camera_for_request", lambda *args: {"archive":"camera", "name":"Camera"})
    image = put(root, "12-00-00-000001.jpg")
    clip = put(root, "12-00-00-000001.mp4", mp4_bytes())
    lone = put(root, "11-00-00-000001.mp4", mp4_bytes())
    events = api.list_snapshots(image.parent, "one", "2026-10-10")
    assert len(events) == 2 and events[0]["video"]["size_bytes"] == len(mp4_bytes())
    assert events[1]["url"] is None and events[1]["delete_url"].endswith("11-00-00-000001.jpg")
    hass = Hass(); request = SimpleNamespace(app={"hass":hass})
    response = await api.SnapshotArchiveVideoView().get(request, "one", "2026-10-10", clip.name)
    assert response.body == mp4_bytes() and response.content_type == "video/mp4"
    hass.data["snapshot_archive_active_events"] = {("camera", "2026-10-10", image.stem)}
    with pytest.raises(web.HTTPConflict): await api.SnapshotArchiveImageView().delete(request, "one", "2026-10-10", image.name)
    assert image.exists() and clip.exists()
    hass.data["snapshot_archive_active_events"].clear()
    await api.SnapshotArchiveImageView().delete(request, "one", "2026-10-10", image.name)
    assert not image.exists() and not clip.exists() and lone.exists()
    await api.SnapshotArchiveImageView().delete(request, "one", "2026-10-10", lone.with_suffix(".jpg").name)
    assert not lone.exists()


@pytest.mark.asyncio
async def test_video_api_rejects_paths_symlinks_nonfiles_and_oversize(root, monkeypatch):
    monkeypatch.setattr(api, "camera_for_request", lambda *args: {"archive":"camera", "name":"Camera"})
    request = SimpleNamespace(app={"hass":Hass()}); view = api.SnapshotArchiveVideoView()
    with pytest.raises(web.HTTPBadRequest): await view.get(request, "one", "2026-10-10", "../clip.mp4")
    with pytest.raises(web.HTTPBadRequest): await view.get(request, "one", "2026-02-30", "12-00-00-000001.mp4")
    path = put(root, "12-00-00-000001.mp4"); path.unlink(); path.symlink_to(root.parent / "secret")
    with pytest.raises(web.HTTPForbidden): await view.get(request, "one", "2026-10-10", path.name)
    path.unlink(); path.mkdir()
    with pytest.raises(web.HTTPForbidden): await view.get(request, "one", "2026-10-10", path.name)
    path.rmdir(); path.write_bytes(b"oversized")
    monkeypatch.setattr(api, "MAX_VIDEO_BYTES", 2)
    with pytest.raises(web.HTTPRequestEntityTooLarge): await view.get(request, "one", "2026-10-10", path.name)


@pytest.mark.asyncio
async def test_timeout_reaps_process(root, monkeypatch):
    hass = stream_hass()
    binary = root / "recorder"
    binary.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n"); binary.chmod(0o700)
    monkeypatch.setattr(video, "get_ffmpeg_manager", lambda hass: SimpleNamespace(binary=str(binary)))
    monkeypatch.setattr(video, "STARTUP_ALLOWANCE", 0.02)
    recorder = video.VideoRecorder(hass, 0, 0)
    assert not await recorder.record("one", "camera", "2026-10-10", "12-00-00-000001")
    assert recorder.running == 0 and not list(root.rglob(".video-*"))


@pytest.mark.asyncio
async def test_executor_accepts_ha_future_and_drains_cancel():
    """HA executor returns a Future, not a coroutine as in the original doubles."""
    started = asyncio.Event(); finish = asyncio.Event()
    async def work():
        started.set(); await finish.wait(); return "finished"
    hass = SimpleNamespace(async_add_executor_job=lambda *args: asyncio.create_task(work()))
    task = asyncio.create_task(video.executor_job(hass, lambda: None))
    await started.wait(); task.cancel(); await asyncio.sleep(0)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError): await task


@pytest.mark.asyncio
async def test_cancel_during_launch_still_reaps_process(root, monkeypatch):
    hass = stream_hass()
    launching = asyncio.Event(); finish_launch = asyncio.Event()
    class Process:
        returncode = None
        def terminate(self): self.returncode = -15
        async def wait(self): return self.returncode
    process = Process()
    async def launch(*args, **kwargs):
        launching.set(); await finish_launch.wait(); return process
    monkeypatch.setattr(video.asyncio, "create_subprocess_exec", launch)
    recorder = video.VideoRecorder(hass, 10, 0)
    task = asyncio.create_task(recorder.record("one", "camera", "2026-10-10", "12-00-00-000001"))
    await launching.wait(); task.cancel(); await asyncio.sleep(0)
    assert not task.done()
    finish_launch.set()
    with pytest.raises(asyncio.CancelledError): await task
    assert process.returncode == -15 and recorder.running == 0
    assert not list(root.rglob(".video-*"))


@pytest.mark.asyncio
async def test_snapshot_failure_still_publishes_clip(root, monkeypatch):
    hass = Hass()
    class Recorder:
        async def record(self, device, archive, day, stem):
            put(root, f"{stem}.mp4", mp4_bytes())
            return True
    item = capture.SnapshotCapture(hass, "Camera", "motion", "button", "camera", "camera", "one", Recorder())
    async def fail(*args): return False
    monkeypatch.setattr(item, "capture_snapshot", fail)
    assert await item.request_capture()
    assert len(list(root.rglob("*.mp4"))) == 1 and not list(root.rglob("*.jpg"))


def test_options_defaults_and_selection(monkeypatch):
    import importlib
    from test_archive import module
    class Flow:
        def __init_subclass__(cls, **kwargs): pass
    monkeypatch.setattr(sys.modules["homeassistant.config_entries"], "ConfigFlow", Flow, raising=False)
    monkeypatch.setattr(sys.modules["homeassistant.config_entries"], "OptionsFlow", Flow, raising=False)
    module("homeassistant.helpers.selector", DeviceSelector=lambda config: lambda value: value, DeviceSelectorConfig=lambda **kwargs: kwargs)
    flow = importlib.import_module("snapshot_archive.config_flow")
    values = flow.settings_schema()({"devices": ["one"]})
    assert values["video_devices"] == [] and values["clip_seconds"] == 10
    assert not flow.selection_errors(values)
    values["video_devices"] = ["two"]
    assert flow.selection_errors(values) == {"base": "video_not_selected"}
    values["video_devices"] = ["one"]
    assert not flow.selection_errors(values)
    values["clip_seconds"] = 61
    import voluptuous as vol
    with pytest.raises(vol.Invalid): flow.settings_schema()(values)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["valid", "container_only", "damaged_frames", "audio_only"])
async def test_decode_validation_real_ffmpeg(tmp_path, kind):
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "Video validation tests require FFmpeg"
    path = tmp_path / "clip.mp4"
    data = (Path(__file__).parent / "fixtures/clip.mp4").read_bytes()
    if kind == "container_only":
        data = mp4_bytes()
    elif kind == "damaged_frames":
        # Preserve the container/index but destroy the encoded video payload.
        start = data.index(b"mdat") + 4
        data = data[:start] + bytes(len(data) - start)
    if kind == "audio_only":
        process = await asyncio.create_subprocess_exec(
            ffmpeg, "-v", "error", "-f", "lavfi", "-i", "anullsrc",
            "-t", "0.2", "-c:a", "aac", str(path),
        )
        assert await process.wait() == 0
    else:
        path.write_bytes(data)
    assert video.valid_mp4(path)
    assert await video.decodable_mp4(ffmpeg, path, 10) == (kind == "valid")


@pytest.mark.asyncio
async def test_rejected_clip_keeps_snapshot_and_no_video_metadata(root, monkeypatch):
    hass = stream_hass()
    # Successful recorder exit plus a finalized but unplayable container.
    binary = root / "recorder"
    binary.write_text(
        f"#!{sys.executable}\nimport os,pathlib,sys\n"
        f"if '-rtsp_transport' in sys.argv: pathlib.Path(sys.argv[-1]).write_bytes({mp4_bytes()!r})\n"
        f"else: os.execv({shutil.which('ffmpeg')!r}, [{shutil.which('ffmpeg')!r}]+sys.argv[1:])\n"
    )
    binary.chmod(0o700)
    monkeypatch.setattr(video, "get_ffmpeg_manager", lambda hass: SimpleNamespace(binary=str(binary)))
    recorder = video.VideoRecorder(hass, 10, 0)
    item = capture.SnapshotCapture(hass, "Camera", "motion", "button", "camera", "camera", "one", recorder)
    item.start()
    assert await item.request_capture()
    images = list(root.rglob("*.jpg"))
    assert len(images) == 1 and not list(root.rglob("*.mp4"))
    assert not list(root.rglob(".video-*")) and recorder.running == 0
    events = api.list_snapshots(images[0].parent, "one", "2026-10-10")
    assert len(events) == 1 and events[0]["url"] and events[0]["video"] is None
    await item.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_decode_timeout_and_cancel_reap_child(tmp_path, monkeypatch, cancel):
    binary = tmp_path / "decoder"
    binary.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n")
    binary.chmod(0o700)
    original = asyncio.create_subprocess_exec
    launched = asyncio.Event()
    processes = []
    async def launch(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        launched.set()
        return process
    monkeypatch.setattr(video.asyncio, "create_subprocess_exec", launch)
    task = asyncio.create_task(video.decodable_mp4(str(binary), tmp_path / "clip.mp4", 10 if cancel else 0.1))
    await launched.wait()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    else:
        assert not await task
    assert processes[0].returncode is not None
