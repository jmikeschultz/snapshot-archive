"""Exercise the gallery with the actual installed Zen UI bundle in Chromium."""
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
HTML = '''<!doctype html><html><body style="margin:0;width:700px"><script type="module" src="/zen-ui.js"></script><script src="/gallery.js"></script><script>
window.mode="normal"; window.requests=[];
window.snapshots=[{filename:"10-00-00-000001.jpg",url:"/api/snapshot_archive/image/one/2026-10-10/10-00-00-000001.jpg"},{filename:"12-00-00-000001.jpg",url:"/api/snapshot_archive/image/one/2026-10-10/12-00-00-000001.jpg"}];
window.hass={states:{"sensor.activity":{attributes:{data:[{date:"2026-10-10",count:3}]}}},locale:{language:"en"},themes:{darkMode:false},callWS:async()=>({}),fetchWithAuth:async(path,options)=>{
 requests.push(path);
 if(options.method==="DELETE") {
   window.deleteRequests=(window.deleteRequests||0)+1;
   if(mode==="delete-error")return new Response("failed",{status:500});
   if(mode==="delete-auth")return new Response("denied",{status:403});
   if(mode==="delete-delay")await new Promise((resolve,reject)=>{options.signal.addEventListener("abort",()=>reject(new DOMException("Aborted","AbortError")));setTimeout(resolve,5000)});
   snapshots=snapshots.filter(item=>item.url!==path);
   return new Response(null,{status:mode==="delete-missing"?404:204});
 }
 if(mode==="auth") return new Response("denied",{status:401});
 if(mode==="error") return new Response("failed",{status:500});
 if(mode==="delay") await new Promise((resolve,reject)=>{options.signal.addEventListener("abort",()=>reject(new DOMException("Aborted","AbortError")));setTimeout(resolve,5000)});
 if(path.endsWith("/cameras")) return Response.json({cameras:[{device_id:"one",name:"Camera One",camera:"camera.one"},{device_id:"two",name:"Camera Two",camera:"camera.two"}]});
 if(path.includes("/video/")) {
   if(mode==="video-auth")return new Response("denied",{status:403});
   if(mode==="video-delay")await new Promise((resolve,reject)=>{options.signal.addEventListener("abort",()=>reject(new DOMException("Aborted","AbortError")));setTimeout(resolve,5000)});
   return fetch("/clip.mp4");
 }
 if(path.includes("/image/")) return new Response(new Blob(['<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="green"/></svg>'],{type:"image/svg+xml"}));
 return Response.json({snapshots:mode==="empty"?[]:snapshots});
}};
window.config={type:"custom:snapshot-archive-heatmap",card:"heatmap",entity:"sensor.activity",title:"Camera activity",days:90,end_date:"2026-10-10",weekStartDay:"sunday",weekdayLabels:"letter",levelCount:8,maxValue:20,levelThresholds:[0,1,3,5,8,12,16],snapshot_archive:{camera:"camera.one"}};
customElements.whenDefined("snapshot-archive-heatmap").then(()=>{window.card=document.createElement("snapshot-archive-heatmap");card.setConfig(config);card.hass=hass;document.body.append(card)});
</script></body></html>'''

async def run():
    app=web.Application()
    app.router.add_get("/",lambda request:web.Response(text=HTML,content_type="text/html"))
    app.router.add_get("/zen-ui.js",lambda request:web.FileResponse(ROOT/"tests/fixtures/zen-ui.js"))
    app.router.add_get("/clip.mp4",lambda request:web.FileResponse(ROOT/"tests/fixtures/clip.mp4"))
    app.router.add_get("/gallery.js",lambda request:web.FileResponse(ROOT/"snapshot_archive/frontend/snapshot-archive-gallery.js"))
    runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,"127.0.0.1",0);await site.start()
    port=site._server.sockets[0].getsockname()[1]
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH", "/usr/bin/chromium"),headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        page=await browser.new_page(timezone_id="UTC");errors=[];page.on("pageerror",lambda error:errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())
        await page.clock.install(time=datetime(2026, 10, 10, 12, tzinfo=timezone.utc))
        await page.goto(f"http://127.0.0.1:{port}/")
        cells=page.locator("snapshot-archive-heatmap zen-ui .year-graph svg rect")
        await cells.last.wait_for();await page.wait_for_function("card.card._loading === false")
        # Wrapper heatmap screenshot should exactly match the unwrapped original.
        before=await page.locator("snapshot-archive-heatmap .heatmap").screenshot()
        await page.evaluate('''() => {const original=document.createElement("zen-ui");const {snapshot_archive,...originalConfig}=config;original.setConfig({...originalConfig,type:"custom:zen-ui"});original.hass=hass;original.id="original";document.body.append(original)}''')
        await page.locator("#original .year-graph svg rect").last.wait_for();await page.wait_for_function("document.querySelector('#original')._loading === false")
        original=await page.locator("#original").screenshot()
        assert before==original,"Heatmap appearance changed"
        await page.locator("#original").evaluate("node => node.remove()")
        await cells.last.click()
        await page.wait_for_function("card.grid.querySelectorAll('img').length === 2")
        assert await page.locator(".gallery .grid span").all_text_contents()==["12:00:00","10:00:00"]
        assert await page.evaluate("requests[1]")=="/api/snapshot_archive/one/2026-10-10"
        await page.locator(".gallery .grid button").first.click()
        assert await page.locator(".full").evaluate("node=>node.open")
        await page.locator(".full img").evaluate("img=>img.decode()")
        assert await page.locator(".full img").evaluate("img=>img.naturalWidth")==640
        await page.keyboard.press("Escape");assert not await page.locator(".full").evaluate("node=>node.open")
        await page.locator(".gallery .close").click();await page.wait_for_function("card.urls.size === 0")
        await page.evaluate("mode='empty'");await cells.first.focus();await page.keyboard.press("Enter")
        await page.wait_for_function("card.status.textContent.includes('No archived snapshots')")
        await page.locator(".gallery .close").click()
        for mode,text in [("auth","Authentication failed"),("error","Archive request failed")]:
            await page.evaluate("value=>window.mode=value",mode);await cells.last.click()
            await page.wait_for_function("text=>card.status.textContent.includes(text)",arg=text)
            await page.locator(".gallery .close").click()
        await page.evaluate("mode='normal';card.setConfig({...config,snapshot_archive:{camera:'camera.two'}})")
        await cells.last.click();await page.wait_for_function("card.status.textContent.includes('newest first')")
        assert await page.locator("#gallery-title").text_content()=="Camera Two · 2026-10-10"
        assert await page.evaluate("requests.some(path=>path==='/api/snapshot_archive/two/2026-10-10')")
        await page.locator(".gallery .close").click()
        await page.evaluate("mode='normal';card.setConfig(config)")
        await cells.last.click();await page.wait_for_function("card.grid.querySelectorAll('img').length === 2")
        for mode,text in [("delete-error","Could not delete snapshot"),("delete-auth","Authentication failed")]:
            await page.evaluate("value=>window.mode=value",mode)
            await page.locator(".gallery .delete").first.click()
            await page.wait_for_function("text=>card.status.textContent.includes(text)",arg=text)
            assert await page.locator(".gallery .tile").count()==2
            assert await page.locator(".gallery .delete").first.is_enabled()
        await page.evaluate("mode='normal'")
        await page.locator(".gallery .delete").first.click()
        await page.wait_for_function("card.status.textContent === '1 snapshot · newest first' && card.grid.querySelectorAll('img').length === 1")
        assert await page.locator(".gallery .grid span").all_text_contents()==["10:00:00"]
        assert await page.evaluate("card.urls.size")==1
        await page.evaluate("mode='delete-missing'")
        await page.locator(".gallery .delete").first.click()
        await page.wait_for_function("card.status.textContent.includes('No archived snapshots')")
        assert await page.locator(".gallery .tile").count()==0 and await page.evaluate("card.urls.size")==0
        await page.locator(".gallery .close").click()
        await page.evaluate("mode='delay'");await cells.last.click();await page.locator(".gallery .close").click()
        await page.wait_for_function("card.controller.signal.aborted && card.urls.size === 0")
        # Real MP4 decoding and lazy authenticated fetch; image preview stays separate.
        await page.evaluate("""mode='normal'; snapshots=[{filename:'12-00-00-000001.jpg',url:'/api/snapshot_archive/image/one/2026-10-10/12-00-00-000001.jpg',video:{url:'/api/snapshot_archive/video/one/2026-10-10/12-00-00-000001.mp4'}}]; requests=[]""")
        await cells.last.click()
        await page.wait_for_function("card.grid.querySelectorAll('img').length === 1")
        assert not await page.evaluate("requests.some(path=>path.includes('/video/'))")
        await page.locator(".gallery .play").click()
        await page.wait_for_function("card.video.readyState >= 2")
        assert await page.evaluate("card.video.videoWidth") == 160
        assert await page.evaluate("card.videoUrl.startsWith('blob:')")
        assert await page.locator(".full img").is_hidden()
        await page.locator(".full .close").click()
        await page.wait_for_function("card.videoUrl === null && !card.video.hasAttribute('src')")
        await page.locator(".gallery .preview").click()
        assert await page.locator(".full video").is_hidden()
        await page.locator(".full img").evaluate("img=>img.decode()")
        await page.locator(".full .close").click()
        await page.evaluate("mode='video-auth'")
        await page.locator(".gallery .play").click()
        await page.wait_for_function("card.videoStatus.textContent.includes('Authentication failed')")
        await page.locator(".full .close").click()
        await page.evaluate("mode='video-delay'")
        await page.locator(".gallery .play").click()
        await page.locator(".full .close").click()
        await page.wait_for_function("card.videoController.signal.aborted && card.videoUrl === null")
        await page.locator(".gallery .close").click()
        # A surviving clip remains accessible when its snapshot expired or failed.
        await page.evaluate("mode='normal'; snapshots[0].url=null")
        await cells.last.click()
        await page.wait_for_function("card.grid.querySelector('.preview')?.textContent === 'Video clip'")
        await page.locator(".gallery .preview").click()
        await page.wait_for_function("card.video.readyState >= 2")
        await page.locator(".full .close").click()
        await page.locator(".gallery .close").click()
        await page.evaluate("card.remove()")
        assert not errors,errors
        await browser.close()
    await runner.cleanup()
    print("PASS: unchanged heatmap pixels; date/gallery/full-size/keyboard/errors/multiple cameras; successful deletion refresh; delete failure preserves images; already-missing deletion; last-image empty state; object URL cleanup; real lazy MP4 playback, video-only events, authentication errors, and aborted player loads")

if __name__=="__main__":asyncio.run(run())
