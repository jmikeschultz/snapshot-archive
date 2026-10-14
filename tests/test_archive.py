"""Isolated tests against installed integration code, with HA boundary doubles."""
import asyncio
import importlib
import json
import os
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def module(name, **attributes):
    value = types.ModuleType(name)
    value.__dict__.update(attributes)
    sys.modules[name] = value
    return value

module("homeassistant")
module("homeassistant.components")
class View:
    def json(self, data):
        return web.json_response(data)
module("homeassistant.components.http", HomeAssistantView=View, StaticPathConfig=lambda *args: args)
module("homeassistant.components.ffmpeg", get_ffmpeg_manager=lambda hass: SimpleNamespace(binary="/usr/bin/ffmpeg"))
module("homeassistant.components.frontend", add_extra_js_url=lambda *args: None)
module("homeassistant.components.lovelace")
module("homeassistant.components.lovelace.const", LOVELACE_DATA="lovelace")
module("homeassistant.config_entries", ConfigEntry=object)
module("homeassistant.core", HomeAssistant=object, callback=lambda fn: fn)
module("homeassistant.const", STATE_ON="on", EVENT_HOMEASSISTANT_STOP="stop")
module("homeassistant.exceptions", HomeAssistantError=RuntimeError)
module("homeassistant.helpers")
module("homeassistant.helpers.device_registry", async_get=lambda hass: hass.devices)
module("homeassistant.helpers.entity_registry", async_get=lambda hass: hass.entities, async_entries_for_device=lambda registry,device: registry.get(device, []))
class Store:
    data = {}
    def __init__(self, hass, version, key): self.key = key
    async def async_load(self): return self.data.get(self.key)
    async def async_save(self, data): self.data[self.key] = data.copy()
module("homeassistant.helpers.storage", Store=Store)
def track(hass, entities, fn):
    hass.listeners.append(fn)
    return lambda: hass.listeners.remove(fn)
def interval(hass, fn, delta):
    hass.timer = fn
    return lambda: setattr(hass, "timer", None)
module("homeassistant.helpers.event", async_track_state_change_event=track, async_track_time_interval=interval)
async def get_image(hass, entity): return SimpleNamespace(content=b"\xff\xd8test\xff\xd9")
camera = module("homeassistant.components.camera", async_get_image=get_image)
module("homeassistant.util")
from datetime import datetime, timezone
module("homeassistant.util.dt", now=lambda: datetime(2026,10,10,12,0,tzinfo=timezone.utc))

integration = importlib.import_module("snapshot_archive")
from snapshot_archive import api, archive, capture, retention, discovery

class Hass:
    def __init__(self):
        self.data = {}
        self.http = SimpleNamespace(register_view=lambda view: None)
        self.listeners = []
        self.entities = {}
        self.devices = SimpleNamespace(async_get=lambda device: SimpleNamespace(name="Camera",name_by_user=None))
        self.config_entries = SimpleNamespace(async_entries=lambda domain: [])
        self.services = SimpleNamespace(async_call=self.press)
        self.bus = SimpleNamespace(async_listen_once=lambda *args: lambda: None)
    async def press(self, *args, **kwargs):
        for fn in self.listeners[1:]: fn(SimpleNamespace(data={}))
    def async_create_task(self, coroutine): return asyncio.create_task(coroutine)
    async def async_add_executor_job(self, fn, *args): return await asyncio.to_thread(fn,*args)

@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(archive,"ARCHIVE_ROOT",tmp_path)
    monkeypatch.setattr(retention,"ARCHIVE_ROOT",tmp_path)
    monkeypatch.setattr(capture,"ARCHIVE_ROOT",tmp_path)
    Store.data.clear()
    return tmp_path

def put(root, name, content=b"jpeg"):
    path = root / "camera" / "2026-10-10" / name
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(content)
    return path

def test_dates():
    assert api.validate_date("2024-02-29") == "2024-02-29"
    for day in ["2025-02-29","2026-13-01","../etc","2026-1-1"]:
        with pytest.raises(web.HTTPBadRequest): api.validate_date(day)

def test_order_and_filter(root):
    put(root,"10-00-00-000001.jpg")
    put(root,"12-00-00-000001.jpg")
    put(root,"partial.tmp")
    link=put(root,"11-00-00-000001.jpg");link.unlink();link.symlink_to(root/"outside")
    assert [i["filename"] for i in api.list_snapshots(root/"camera"/"2026-10-10","one","2026-10-10")] == ["12-00-00-000001.jpg","10-00-00-000001.jpg"]
    assert api.list_snapshots(root/"missing","one","2026-10-09") == []

def test_path_symlinks(root):
    outside=root.parent/"outside";outside.mkdir()
    (root/"camera").symlink_to(outside,target_is_directory=True)
    with pytest.raises(PermissionError): archive.snapshot_directory({"archive":"camera"},"2026-10-10")
    with pytest.raises(PermissionError): archive.snapshot_directory({"archive":"../outside"},"2026-10-10")

@pytest.mark.asyncio
async def test_stable_identity_and_collision(root):
    (root/"camera").mkdir()
    hass=Hass()
    assert (await archive.async_prepare_archives(hass,{"one":"Camera"}))["one"] == "camera"
    assert (await archive.async_prepare_archives(hass,{"one":"Renamed","two":"Camera"})) == {"one":"camera","two":"two"}
    Store.data.clear()
    assert await archive.async_prepare_archives(Hass(),{"one":"Camera","two":"Camera"}) == {"one":"one","two":"two"}

def test_retention_age_size_and_symlinks(root):
    old=put(root,"10-00-00-000001.jpg");os.utime(old,(0,0))
    first=put(root,"11-00-00-000001.jpg"); second=put(root,"12-00-00-000001.jpg")
    os.utime(first,(datetime.now().timestamp()-5,)*2)
    outside=root.parent/"keep.jpg";outside.write_bytes(b"keep")
    (first.parent/"13-00-00-000001.jpg").symlink_to(outside)
    deleted, remaining = retention._cleanup(365,4/retention.BYTES_PER_GB)
    assert deleted == 2 and remaining == 4
    assert not old.exists() and not first.exists() and second.exists() and outside.exists()

def test_registration_once():
    hass=Hass(); views=[];hass.http=SimpleNamespace(register_view=views.append)
    api.register_api(hass);api.register_api(hass)
    assert len(views)==4 and all(v.requires_auth for v in views)

@pytest.mark.asyncio
async def test_image_symlink_and_missing(root,monkeypatch):
    monkeypatch.setattr(api,"camera_for_request",lambda *args:{"archive":"camera","name":"Camera"})
    request=SimpleNamespace(app={"hass":Hass()})
    path=put(root,"10-00-00-000001.jpg");path.unlink();path.symlink_to(root.parent/"secret")
    with pytest.raises(web.HTTPForbidden): await api.SnapshotArchiveImageView().get(request,"one","2026-10-10",path.name)
    with pytest.raises(web.HTTPNotFound): await api.SnapshotArchiveImageView().get(request,"one","2026-10-10","11-00-00-000001.jpg")

@pytest.mark.asyncio
async def test_motion_capture_stop_and_atomic_write(root):
    hass=Hass(); item=capture.SnapshotCapture(hass,"Camera","motion","button","camera","camera")
    item.start()
    event=SimpleNamespace(data={"old_state":SimpleNamespace(state="off"),"new_state":SimpleNamespace(state="on")})
    hass.listeners[0](event); task=item._task
    hass.listeners[0](event);assert item._task is task
    await task
    assert len(list(root.rglob("*.jpg")))==1 and not list(root.rglob("*.tmp"))
    await item.stop();assert not hass.listeners

@pytest.mark.asyncio
async def test_capture_cancellation_cleans_subscriptions(root):
    hass=Hass()
    async def press(*args,**kwargs): await asyncio.Event().wait()
    hass.services.async_call=press
    item=capture.SnapshotCapture(hass,"Camera","motion","button","camera","camera");item.start();item.request_capture()
    await asyncio.sleep(0);await item.stop()
    assert not hass.listeners and item._task is None

@pytest.mark.asyncio
async def test_unload_waits_scheduled_cleanup(root,monkeypatch):
    hass=Hass(); started=asyncio.Event(); finish=asyncio.Event()
    async def cleanup(*args):started.set();await finish.wait()
    monkeypatch.setattr(integration,"async_cleanup",cleanup)
    entry=SimpleNamespace(entry_id="one",data={"devices":[]},options={},async_on_unload=lambda fn:None,add_update_listener=lambda fn:lambda:None)
    await integration.async_setup_entry(hass,entry);await started.wait()
    hass.timer(None)
    task=asyncio.create_task(integration.async_unload_entry(hass,entry));await asyncio.sleep(0)
    assert not task.done();finish.set();await task
    assert hass.timer is None and hass.data[integration.DOMAIN] == {}

@pytest.mark.asyncio
async def test_cancel_cleanup_waits_executor(root,monkeypatch):
    started=threading.Event();finish=threading.Event()
    def cleanup(*args):started.set();finish.wait(5);return 0,0
    monkeypatch.setattr(retention,"_cleanup",cleanup)
    task=asyncio.create_task(retention.async_cleanup(Hass(),365,10))
    await asyncio.to_thread(started.wait,2);task.cancel();await asyncio.sleep(.01)
    assert not task.done();finish.set()
    with pytest.raises(asyncio.CancelledError): await task

def test_disabled_entities():
    hass=Hass();hass.entities={"one":[SimpleNamespace(disabled_by="user",entity_id="camera.disabled",original_name="Snapshot",unique_id="snapshot",domain="camera")]}
    assert discovery.discover_camera_entities(hass,"one")["camera"] is None

@pytest.mark.asyncio
async def test_delete_exact_snapshot_and_updated_listing(root, monkeypatch):
    monkeypatch.setattr(api,"camera_for_request",lambda *args:{"archive":"camera","name":"Camera"})
    remove=put(root,"12-00-00-000001.jpg")
    keep=put(root,"10-00-00-000001.jpg")
    other=root/"other-camera"/"2026-10-10"/remove.name
    other.parent.mkdir(parents=True);other.write_bytes(b"keep")
    request=SimpleNamespace(app={"hass":Hass()})
    view=api.SnapshotArchiveImageView()
    response=await view.delete(request,"one","2026-10-10",remove.name)
    assert response.status==204 and not remove.exists()
    assert keep.exists() and other.exists()
    listing=await api.SnapshotArchiveDayView().get(request,"one","2026-10-10")
    assert json.loads(listing.text)["count"]==1
    with pytest.raises(web.HTTPNotFound):await view.delete(request,"one","2026-10-10",remove.name)
    await view.delete(request,"one","2026-10-10",keep.name)
    listing=await api.SnapshotArchiveDayView().get(request,"one","2026-10-10")
    assert json.loads(listing.text)["snapshots"]==[]

@pytest.mark.asyncio
async def test_delete_rejects_invalid_paths_and_nonfiles(root, monkeypatch):
    monkeypatch.setattr(api,"camera_for_request",lambda *args:{"archive":"camera","name":"Camera"})
    request=SimpleNamespace(app={"hass":Hass()});view=api.SnapshotArchiveImageView()
    for day,name in [("2026-02-30","12-00-00-000001.jpg"),("2026-10-10","../secret.jpg"),("2026-10-10","unrelated.txt")]:
        with pytest.raises(web.HTTPBadRequest):await view.delete(request,"one",day,name)
    outside=root.parent/"delete-protected";outside.write_bytes(b"keep")
    link=put(root,"12-00-00-000001.jpg");link.unlink();link.symlink_to(outside)
    with pytest.raises(web.HTTPForbidden):await view.delete(request,"one","2026-10-10",link.name)
    assert outside.exists() and link.is_symlink()
    directory=link.parent/"13-00-00-000001.jpg";directory.mkdir()
    with pytest.raises(web.HTTPForbidden):await view.delete(request,"one","2026-10-10",directory.name)
    linked=root/"linked";linked.symlink_to(link.parent,target_is_directory=True)
    monkeypatch.setattr(api,"camera_for_request",lambda *args:{"archive":"linked"})
    with pytest.raises(web.HTTPForbidden):await view.delete(request,"one","2026-10-10",link.name)

@pytest.mark.asyncio
async def test_delete_unknown_camera_and_disk_error(root, monkeypatch):
    request=SimpleNamespace(app={"hass":Hass()});view=api.SnapshotArchiveImageView()
    with pytest.raises(web.HTTPNotFound):await view.delete(request,"unknown","2026-10-10","12-00-00-000001.jpg")
    monkeypatch.setattr(api,"camera_for_request",lambda *args:{"archive":"camera","name":"Camera"})
    keep=put(root,"12-00-00-000001.jpg")
    def fail(*args,**kwargs):raise OSError("Disk failure")
    monkeypatch.setattr(api.os,"unlink",fail)
    with pytest.raises(web.HTTPInternalServerError):await view.delete(request,"one","2026-10-10",keep.name)
    assert keep.exists()

@pytest.mark.asyncio
@pytest.mark.parametrize("existing_url",[None,"/snapshot_archive_static/snapshot-archive-gallery.js?v=old","/snapshot_archive_static/snapshot-archive-gallery.js?v=0.2.2&resource"])
async def test_frontend_resource_registration(existing_url):
    hass=Hass()
    async def static_paths(paths):pass
    hass.http.async_register_static_paths=static_paths
    hass.services.async_register=lambda *args,**kwargs:None
    class Resources:
        def __init__(self):self.items=[] if existing_url is None else [{"id":"one","url":existing_url}]
        async def async_get_info(self):return {"resources":len(self.items)}
        def async_items(self):return self.items
        async def async_create_item(self,data):self.items.append({"id":"one",**data})
        async def async_update_item(self,identifier,data):self.items[0].update(data)
    resources=Resources()
    hass.data["lovelace"]=SimpleNamespace(resources=resources)
    await integration.async_setup(hass,{})
    assert len(resources.items)==1
    assert resources.items[0]["url"]=="/snapshot_archive_static/snapshot-archive-gallery.js?v=0.3.0&resource"
