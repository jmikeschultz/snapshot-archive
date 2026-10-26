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
        # Last activity works independently of Zen UI and shares the gallery.
        await page.evaluate("""() => {
          hass.config={time_zone:'America/New_York'};
          hass.states['sensor.contact']={attributes:{last_activity_display:'Lake West Side Motion — Oct 18, 8:00 AM',occurred:'2026-10-10T02:00:00Z'}};
          window.activity=document.createElement('snapshot-archive-last-activity');
          activity.setConfig({entity:'sensor.contact'});activity.hass=hass;document.body.append(activity);
        }""")
        activity=page.locator('snapshot-archive-last-activity')
        assert await activity.locator('.value').text_content()==' Lake West Side Motion — Oct 18, 8:00 AM'
        assert await activity.locator('.camera').is_hidden()
        assert await page.evaluate("customCards.some(c=>c.type==='snapshot-archive-last-activity')")
        await page.evaluate("activity.setConfig({entity:'sensor.contact',label:'Recent:',alignment:'center',font_size:'18px',timestamp_attribute:'occurred',snapshot_archive:{camera:'camera.two'}})")
        assert await activity.locator('.label').text_content()=='Recent:'
        await activity.locator('.camera').click()
        await page.wait_for_function("activity.status.textContent.includes('newest first')")
        assert await activity.locator('#gallery-title').text_content()=='Camera Two · 2026-10-09'
        await activity.locator('.gallery .close').click()
        await page.evaluate("hass.states['sensor.contact'].attributes.occurred='invalid';activity.hass=hass")
        await activity.locator('.camera').click()
        assert await activity.locator('.hint').is_visible()
        assert not await activity.locator('.gallery').evaluate('node=>node.open')
        await page.evaluate("""() => {
          window.editor=activity.constructor.getConfigElement();
          editor.setConfig(activity.config);editor.hass=hass;
          editor.addEventListener('config-changed',event=>window.edited=event.detail.config);
          document.body.append(editor);
        }""")
        editor=page.locator('snapshot-archive-last-activity-editor')
        await editor.locator('[data-key="label"]').fill('Latest:')
        await editor.locator('[data-key="label"]').dispatch_event('change')
        assert await page.evaluate('edited.label')=='Latest:'
        assert await page.evaluate('edited.snapshot_archive.camera')=='camera.two'
        await editor.locator('[data-key="camera"]').fill('')
        await editor.locator('[data-key="camera"]').dispatch_event('change')
        assert await page.evaluate('edited.snapshot_archive === undefined')
        assert await activity.locator('.duration').is_hidden()
        await editor.locator('[data-key="show_duration"]').check()
        await editor.locator('[data-key="duration_field"]').select_option('on_seconds')
        await editor.locator('[data-key="duration_label"]').fill('Running today:')
        await editor.locator('[data-key="duration_label"]').dispatch_event('change')
        assert await page.evaluate('edited.show_duration && edited.duration_field === "on_seconds" && edited.duration_label === "Running today:"')
        await page.evaluate("""() => {
          hass.states['sensor.contact'].attributes.time_zone='Pacific/Auckland';
          hass.states['sensor.contact'].attributes.data=[{date:'2026-10-11',off_seconds:3661.9,on_seconds:7322},{date:'2026-10-10',off_seconds:999}];
          activity.setConfig({entity:'sensor.contact',show_duration:true});activity.hass=hass;
        }""")
        assert await activity.locator('.duration-label').text_content()=='Outage today:'
        assert await activity.locator('.duration-value').text_content()==' 1h 1m 1s'
        await page.evaluate("activity.setConfig({...activity.config,duration_field:'on_seconds',duration_label:'Running today:'})")
        assert await activity.locator('.duration-label').text_content()=='Running today:'
        assert await activity.locator('.duration-value').text_content()==' 2h 2m 2s'
        await page.evaluate("hass.states['sensor.contact'].attributes.data=[];activity.hass=hass")
        assert await activity.locator('.duration-value').text_content()==' 0h 0m 0s'
        await page.evaluate("hass.states['sensor.contact'].state='unavailable';activity.hass=hass")
        assert await activity.locator('.duration-value').text_content()==' Unavailable'
        await page.evaluate("delete hass.states['sensor.contact'];activity.hass=hass")
        assert await activity.locator('.duration-value').text_content()==' Unavailable'
        # Last-outage mode uses individual records, never a day's accumulated total.
        await page.evaluate("""() => {
          hass.states['sensor.contact']={state:'0',attributes:{time_zone:'America/New_York',last_activity_display:'Old activity',data:[{date:'2026-10-10',off_seconds:999}]}};
          activity.setConfig({entity:'sensor.contact',duration_mode:'last_outage'});activity.hass=hass;
        }""")
        assert await activity.locator('.value').text_content()==' Not recorded'
        assert await activity.locator('.duration-value').text_content()==' Not recorded'
        await page.evaluate("hass.states['sensor.contact'].attributes.last_outage={start:'2026-10-10T03:58:00Z',end:null,seconds:125,status:'ongoing'};activity.hass=hass")
        assert await activity.locator('.value').text_content()==' Oct 9, 11:58 PM'
        assert await activity.locator('.duration-label').text_content()=='Outage ongoing:'
        assert await activity.locator('.duration-value').text_content()==' 0h 2m 5s'
        await page.evaluate("hass.states['sensor.contact'].attributes.last_outage={start:'2026-10-10T03:58:00Z',end:'2026-10-10T04:03:00Z',seconds:300,status:'completed'};activity.hass=hass")
        assert await activity.locator('.value').text_content()==' Oct 9, 11:58 PM'
        assert await activity.locator('.duration-label').text_content()=='Last outage duration:'
        assert await activity.locator('.duration-value').text_content()==' 0h 5m 0s'
        await page.evaluate("hass.states['sensor.contact'].attributes.last_outage.status='interrupted';hass.states['sensor.contact'].attributes.last_outage.seconds=null;activity.hass=hass")
        assert await activity.locator('.duration-value').text_content()==' Unknown (tracking interrupted)'
        await page.evaluate("hass.states['sensor.contact'].attributes.last_outage.status='awaiting_report';activity.hass=hass")
        assert await activity.locator('.duration-value').text_content()==' Awaiting recovery report'
        await editor.locator('[data-key="duration_mode"]').select_option('last_outage')
        assert await page.evaluate("edited.duration_mode === 'last_outage'")
        await page.evaluate("activity.remove();editor.remove()")
        await page.evaluate("card.remove()")
        assert not errors,errors
        await browser.close()
    await runner.cleanup()
    print("PASS: unchanged heatmap pixels; date/gallery/full-size/keyboard/errors/multiple cameras; successful deletion refresh; delete failure preserves images; already-missing deletion; last-image empty state; object URL cleanup; real lazy MP4 playback, video-only events, authentication errors, and aborted player loads")

if __name__=="__main__":asyncio.run(run())
