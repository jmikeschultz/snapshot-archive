/* Snapshot Archive wrapper for Zen UI. HACS assets remain untouched. */
class SnapshotArchiveGallery extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>
      :host {display:block} dialog {color:var(--primary-text-color,#222);background:var(--card-background-color,#fff);border:0;border-radius:16px;padding:20px;width:min(960px,90vw);max-height:85vh;box-sizing:border-box}
      dialog::backdrop {background:rgba(0,0,0,.65)} header {display:flex;align-items:center;gap:16px} h2 {flex:1;font-size:20px} button {cursor:pointer;font:inherit;color:inherit;background:var(--secondary-background-color,#eee);border:0;border-radius:8px;padding:10px}
      .grid {display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px} .grid .tile {min-width:0} .grid .tile {overflow:hidden;border-radius:8px;background:var(--secondary-background-color,#eee)} .grid .preview {padding:0;overflow:hidden;text-align:center;width:100%;display:block;border-radius:0} .grid .caption {display:flex;align-items:center;justify-content:space-between;padding:4px 8px} .grid .caption span {padding:4px 0} .grid .delete {display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;padding:6px;background:transparent;color:var(--secondary-text-color,#666)} .grid .delete:hover {color:var(--error-color,#b00020);background:var(--card-background-color,#fff)} .grid .delete svg {width:18px;height:18px;fill:currentColor} .grid .delete[aria-busy="true"] {opacity:.4} button:disabled {cursor:default;opacity:.6} .grid img {width:100%;height:150px;object-fit:cover;display:block} .grid span {display:block;padding:8px} .full video {width:100%;max-height:70vh} .video-status {padding:8px 0} .full img {max-width:100%;max-height:70vh;object-fit:contain;display:block;margin:auto} .status {padding:12px 0} .more {margin-top:16px} [hidden] {display:none!important}
    </style><div class="heatmap"></div><dialog class="gallery" aria-labelledby="gallery-title"><header><h2 id="gallery-title">Snapshots</h2><button class="close" aria-label="Close gallery">Close</button></header><p class="status" role="status" aria-live="polite"></p><div class="grid"></div><button class="more" hidden>Load more</button></dialog><dialog class="full" aria-label="Full-size snapshot"><header><h2>Snapshot</h2><button class="close" aria-label="Close full-size image">Close</button></header><img alt="Archived camera snapshot"><p class="video-status" role="status" aria-live="polite" hidden></p><video controls playsinline preload="none" hidden></video></dialog>`;
    this.gallery = this.shadowRoot.querySelector(".gallery");
    this.full = this.shadowRoot.querySelector(".full");
    this.status = this.shadowRoot.querySelector(".status");
    this.grid = this.shadowRoot.querySelector(".grid");
    this.more = this.shadowRoot.querySelector(".more");
    this.video = this.full.querySelector("video");
    this.videoStatus = this.full.querySelector(".video-status");
    this.full.addEventListener("close", () => {if (!this.full.open) this.releaseVideo();});
    for (const dialog of [this.gallery, this.full]) {
      dialog.querySelector(".close").onclick = () => dialog.close();
      dialog.addEventListener("click", event => { if (event.target === dialog) {
        const bounds = dialog.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
      }});
    }
    this.gallery.addEventListener("close", () => {if (!this.gallery.open) this.release();});
    this.more.onclick = () => this.loadPage(this.generation);
    this.generation = 0;
    this.urls = new Set();
  }
  set hass(value) { this._hass = value; }
  get hass() { return this._hass; }
  disconnectedCallback() {this.gallery.close(); this.full.close(); this.release();}
  releaseVideo() {
    this.videoGeneration = (this.videoGeneration || 0) + 1;
    this.videoController?.abort();
    this.video.pause(); this.video.removeAttribute("src"); this.video.load(); this.video.hidden = true;
    this.videoStatus.hidden = true;
    if (this.videoUrl) {URL.revokeObjectURL(this.videoUrl); this.videoUrl = null;}
  }
  async playClip(snapshot, generation) {
    if (generation !== this.generation) return;
    this.releaseVideo();
    const videoGeneration = this.videoGeneration;
    this.videoController = new AbortController();
    this.full.querySelector("img").hidden = true;
    this.full.querySelector("h2").textContent = `Video · ${snapshot.filename.slice(0,8).replaceAll("-", ":")}`;
    this.videoStatus.hidden = false; this.videoStatus.textContent = "Loading clip…";
    if (!this.full.open) this.full.showModal();
    try {
      const signal = AbortSignal.any([this.controller.signal, this.videoController.signal]);
      const response = await this.request(snapshot.video.url, signal);
      const blob = await response.blob();
      if (generation !== this.generation || videoGeneration !== this.videoGeneration) return;
      if (!blob.type.startsWith("video/mp4")) throw new Error("Invalid video response");
      this.videoUrl = URL.createObjectURL(blob);
      this.video.src = this.videoUrl; this.video.hidden = false; this.videoStatus.hidden = true;
      this.video.onerror = () => {this.videoStatus.hidden = false; this.videoStatus.textContent = "This clip could not be played.";};
      // Keep native controls available if the browser blocks autoplay after fetch.
      this.video.play().catch(() => {});
    } catch (error) {
      if (generation === this.generation && videoGeneration === this.videoGeneration && error.name !== "AbortError") {
        this.videoStatus.hidden = false; this.videoStatus.textContent = `Could not load clip: ${error.message}`;
      }
    }
  }
  release() {
    this.generation++; this.controller?.abort();
    this.deleteOperation = null;
    for (const url of this.urls) URL.revokeObjectURL(url);
    this.urls.clear(); this.grid.replaceChildren(); this.more.hidden = true;
    this.full.close(); this.releaseVideo(); this.full.querySelector("img").removeAttribute("src");
  }
  async request(path, signal, options = {}) {
    if (!this.hass?.fetchWithAuth) throw new Error("Authenticated Home Assistant connection unavailable. Reload and sign in.");
    const response = await this.hass.fetchWithAuth(path, {...options, signal: AbortSignal.any([signal, AbortSignal.timeout(30000)])});
    if (!response.ok) {
      const error = new Error(response.status === 401 || response.status === 403 ? "Authentication failed. Sign in again or check permissions." : response.status === 409 ? "This event is still recording. Try again shortly." : `Archive request failed (${response.status}).`);
      error.status = response.status;
      throw error;
    }
    return response;
  }
  async openGallery(day) {
    this.release(); this.controller = new AbortController();
    this.day = day;
    const generation = this.generation, signal = this.controller.signal;
    if (!this.gallery.open) this.gallery.showModal();
    this.status.textContent = "Loading snapshots…";
    this.shadowRoot.querySelector("#gallery-title").textContent = `Snapshots · ${day}`;
    try {
      const {cameras} = await (await this.request("/api/snapshot_archive/cameras", signal)).json();
      const selected = this.config.snapshot_archive.camera;
      const camera = cameras.find(item => item.device_id === selected || item.camera === selected);
      if (!camera) throw new Error("This camera is not configured in Snapshot Archive.");
      const data = await (await this.request(`/api/snapshot_archive/${encodeURIComponent(camera.device_id)}/${day}`, signal)).json();
      if (generation !== this.generation) return;
      this.shadowRoot.querySelector("#gallery-title").textContent = `${camera.name} · ${day}`;
      this.snapshots = [...data.snapshots].sort((a,b) => b.filename.localeCompare(a.filename));
      this.offset = 0;
      this.status.textContent = this.snapshots.length ? `${this.snapshots.length} snapshot${this.snapshots.length === 1 ? "" : "s"} · newest first` : "No archived snapshots for this date.";
      await this.loadPage(generation);
    } catch (error) {if (generation === this.generation && error.name !== "AbortError") this.status.textContent = error.message;}
  }
  async deleteSnapshot(snapshot, button, generation) {
    if (this.deleteOperation || generation !== this.generation) return;
    if (!window.confirm(snapshot.video ? "Permanently delete this snapshot and its video clip? This cannot be undone." : "Permanently delete this archived snapshot? This cannot be undone.")) return;
    const operation = Symbol("delete");
    this.deleteOperation = operation;
    this.grid.querySelectorAll(".delete").forEach(item => {item.disabled = true;});
    button.setAttribute("aria-busy", "true");
    try {
      try {
        await this.request(snapshot.delete_url || snapshot.url, this.controller.signal, {method:"DELETE"});
      } catch (error) {
        // Retention or another client may already have removed this image.
        if (error.status !== 404) throw error;
      }
      if (generation === this.generation) await this.openGallery(this.day);
    } catch (error) {
      if (generation === this.generation && error.name !== "AbortError") this.status.textContent = `Could not delete snapshot: ${error.message}`;
    } finally {
      if (this.deleteOperation === operation) {
        this.deleteOperation = null;
        button.removeAttribute("aria-busy");
        this.grid.querySelectorAll(".delete").forEach(item => {item.disabled = false;});
      }
    }
  }
  async loadPage(generation) {
    this.more.hidden = true;
    const batch = this.snapshots.slice(this.offset, this.offset + 48);
    this.offset += batch.length;
    const jobs = batch.map(snapshot => {
      const tile = document.createElement("div"); tile.className = "tile";
      const button = document.createElement("button");
      button.className = "preview";
      const label = document.createElement("span");
      label.textContent = snapshot.filename.slice(0,8).replaceAll("-", ":");
      button.disabled = true;
      const caption = document.createElement("div"); caption.className = "caption";
      const remove = document.createElement("button"); remove.className = "delete";
      remove.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M9 3h6l1 2h4v2H4V5h4l1-2zm-3 6h12l-1 12H7L6 9zm4 2v8h1v-8h-1zm3 0v8h1v-8h-1z"/></svg>';
      remove.disabled = Boolean(this.deleteOperation);
      remove.title = "Permanently delete this archived snapshot";
      remove.setAttribute("aria-label", `Delete snapshot at ${label.textContent}`);
      remove.onclick = () => this.deleteSnapshot(snapshot, remove, generation);
      caption.append(label);
      if (snapshot.video) {
        const play = document.createElement("button"); play.className = "play";
        play.textContent = "▶"; play.title = "Play video clip";
        play.setAttribute("aria-label", `Play clip at ${label.textContent}`);
        play.onclick = () => this.playClip(snapshot, generation);
        caption.append(play);
      }
      caption.append(remove); tile.append(button, caption); this.grid.append(tile);
      return {snapshot,button,label};
    });
    let index = 0;
    await Promise.all(Array.from({length:Math.min(4,jobs.length)}, async () => {
      while (index < jobs.length && generation === this.generation) {
        const {snapshot,button,label} = jobs[index++];
        try {
          if (!snapshot.url) {
            button.textContent = "Video clip"; button.disabled = false;
            button.onclick = () => this.playClip(snapshot, generation);
            continue;
          }
          const response = await this.request(snapshot.url, this.controller.signal);
          const blob = await response.blob();
          if (generation !== this.generation) return;
          if (!blob.type.startsWith("image/")) throw new Error("Invalid image response");
          const url = URL.createObjectURL(blob); this.urls.add(url);
          const img = document.createElement("img"); img.src = url; img.alt = `Snapshot at ${label.textContent}`;
          img.onerror = () => {label.textContent = "Image could not be decoded"; button.disabled = true;};
          button.prepend(img); button.disabled = false;
          button.onclick = () => {this.releaseVideo(); this.full.querySelector("img").hidden = false; this.full.querySelector("img").src = url; this.full.querySelector("h2").textContent = label.textContent; this.full.showModal();};
        } catch (error) {if (generation === this.generation && error.name !== "AbortError") label.textContent = error.message;}
      }
    }));
    if (generation === this.generation) this.more.hidden = this.offset >= this.snapshots.length;
  }
}
class SnapshotArchiveHeatmap extends SnapshotArchiveGallery {
  set hass(value) { this._hass = value; if (this.card) this.card.hass = value; }
  get hass() { return this._hass; }
  setConfig(config) {
    if (config.card !== "heatmap" || !config.snapshot_archive?.camera) throw new Error("Set card: heatmap and snapshot_archive.camera to a camera entity or device ID");
    this.config = config;
    if (this.card) this.configureCard();
    else customElements.whenDefined("zen-ui").then(() => {
      if (this.card) return;
      this.card = document.createElement("zen-ui");
      this.configureCard();
      this.shadowRoot.querySelector(".heatmap").append(this.card);
      this.card.addEventListener("click", event => this.openCell(event));
      this.card.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {event.preventDefault(); this.openCell(event);}
      });
      this.observe();
    });
  }
  configureCard() {
    const {snapshot_archive, ...config} = this.config;
    this.card.setConfig({...config, type:"custom:zen-ui"});
    this.card.hass = this._hass;
  }
  connectedCallback() { if (this.card) this.observe(); }
  disconnectedCallback() {this.observer?.disconnect(); this.gallery.close(); this.full.close(); this.release();}
  getCardSize() {return this.card?.getCardSize() ?? 3;}
  getGridOptions() {return this.card?.getGridOptions() ?? {columns:"full",min_rows:2};}
  observe() {
    this.observer?.disconnect();
    this.observer = new MutationObserver(() => this.decorate());
    if (this.card.shadowRoot) this.observer.observe(this.card.shadowRoot, {childList:true,subtree:true});
    else this.card.updateComplete?.then(() => this.observe());
    this.decorate();
  }
  decorate() {
    this.card.shadowRoot?.querySelectorAll(".year-graph svg rect").forEach(rect => {
      rect.setAttribute("tabindex", "0"); rect.setAttribute("role", "button");
      rect.setAttribute("aria-label", "Open archived snapshots for this date");
    });
  }
  openCell(event) {
    const cell = event.composedPath().find(node => node?.matches?.(".year-graph svg rect"));
    if (!cell) return;
    // Installed Zen UI has no click event or date attribute. Its existing hover
    // handler holds the exact date, including rolling/year ranges and missing days.
    // Keep this version-specific adapter isolated and preserve the hover state.
    const previous = this.card._tooltip;
    cell.dispatchEvent(new MouseEvent("mouseenter"));
    const day = this.card._tooltip?.date;
    this.card._tooltip = previous;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day ?? "")) {
      this.release(); this.gallery.showModal();
      this.status.textContent = "Cannot read this date. The installed Zen UI version may need an updated Snapshot Archive adapter.";
      return;
    }
    this.openGallery(day);
  }
}
if (!customElements.get("snapshot-archive-heatmap")) customElements.define("snapshot-archive-heatmap", SnapshotArchiveHeatmap);

class SnapshotArchiveLastActivity extends SnapshotArchiveGallery {
  constructor() {
    super();
    this.shadowRoot.querySelector('.heatmap').innerHTML = `<style>
      ha-card {padding:var(--activity-padding,16px);color:var(--primary-text-color);font-size:var(--activity-font-size,14px)}
      .activity {display:flex;align-items:center;justify-content:var(--activity-alignment,flex-start);gap:var(--activity-gap,8px)}
      .text {min-width:0;overflow-wrap:anywhere;white-space:pre-wrap} .label {font-weight:bold}
      .camera {flex:none;padding:6px;background:transparent;color:var(--primary-color)}
      .duration {margin-top:8px;text-align:var(--activity-text-alignment,left)} .duration-label {font-weight:bold}
      .hint {font-size:12px;color:var(--secondary-text-color);margin-top:8px}
    </style><ha-card><div class="activity"><div class="text"><span class="label"></span><span class="value"></span></div><button class="camera" aria-label="Open archived camera snapshots" title="Open archived camera snapshots" hidden><ha-icon></ha-icon></button></div><div class="duration" hidden><span class="duration-label"></span><span class="duration-value"></span></div><div class="hint" role="status" hidden></div></ha-card>`;
    this.activityRoot = this.shadowRoot.querySelector('ha-card');
    this.cameraButton = this.activityRoot.querySelector('.camera');
    this.cameraButton.onclick = () => {
      const day = this.activityDay();
      const hint = this.activityRoot.querySelector('.hint');
      hint.hidden = Boolean(day);
      hint.textContent = 'No valid activity timestamp. Select the sensor attribute containing its activity date or timestamp in the card editor.';
      if (day) this.openGallery(day);
    };
  }
  static getConfigElement() { return document.createElement('snapshot-archive-last-activity-editor'); }
  static getStubConfig(hass) {
    return {entity: Object.keys(hass?.states ?? {}).find(id => hass.states[id].attributes?.last_activity_display !== undefined) ?? '', label:'Last :'};
  }
  setConfig(config) {
    if (typeof config.entity !== 'string') throw new Error('Select an activity sensor');
    if (config.alignment && !['left','center','right'].includes(config.alignment)) throw new Error('Alignment must be left, center, or right');
    for (const key of ['font_size','padding','gap']) {
      if (config[key] !== undefined && !/^\d+(\.\d+)?(px|rem|em)$/.test(String(config[key]))) throw new Error(`${key} must be a CSS size such as 14px`);
    }
    if (config.show_duration !== undefined && typeof config.show_duration !== 'boolean') throw new Error('show_duration must be true or false');
    if (config.duration_mode && !['today','last_outage'].includes(config.duration_mode)) throw new Error('Choose today or last_outage duration mode');
    if (config.duration_field && !['off_seconds','on_seconds','unknown_seconds'].includes(config.duration_field)) throw new Error('Choose off_seconds, on_seconds, or unknown_seconds');
    this.release();
    this.config = {...config};
    this.renderActivity();
  }
  set hass(value) { this._hass = value; this.renderActivity(); }
  get hass() { return this._hass; }
  getCardSize() { return 1; }
  getGridOptions() { return {columns:12,rows:(this.config?.show_duration ?? this.config?.duration_mode === 'last_outage') ? 2 : 1,min_rows:1}; }
  renderActivity() {
    if (!this.config) return;
    const state = this.hass?.states?.[this.config.entity];
    const lastOutage = this.config.duration_mode === 'last_outage';
    const outage = state?.attributes?.last_outage;
    let value = state?.attributes?.last_activity_display;
    if (lastOutage) {
      const start = outage?.start ? new Date(outage.start) : null;
      value = start && Number.isFinite(start.getTime()) ? new Intl.DateTimeFormat('en-US', {
        timeZone:state.attributes.time_zone || this.hass?.config?.time_zone || 'UTC',
        month:'short',day:'numeric',hour:'numeric',minute:'2-digit',hour12:true,
      }).format(start) : (state ? 'Not recorded' : 'Unavailable');
    }
    this.activityRoot.querySelector('.label').textContent = this.config.label ?? 'Last :';
    this.activityRoot.querySelector('.value').textContent = `${(this.config.label ?? 'Last :') ? ' ' : ''}${value ?? 'Unavailable'}`;
    this.cameraButton.hidden = !this.config.snapshot_archive?.camera;
    this.cameraButton.querySelector('ha-icon').setAttribute('icon', this.config.icon || 'mdi:camera');
    this.activityRoot.style.setProperty('--activity-alignment', {left:'flex-start',center:'center',right:'flex-end'}[this.config.alignment ?? 'left']);
    for (const [key, fallback] of [['font_size','14px'],['padding','16px'],['gap','8px']]) this.activityRoot.style.setProperty(`--activity-${key.replace('_','-')}`, this.config[key] ?? fallback);
    this.activityRoot.style.setProperty('--activity-text-alignment', this.config.alignment ?? 'left');
    const duration = this.activityRoot.querySelector('.duration');
    duration.hidden = !(this.config.show_duration ?? lastOutage);
    if (!duration.hidden) {
      const field = this.config.duration_field || 'off_seconds';
      const label = this.config.duration_label ?? (lastOutage ? (outage?.status === 'ongoing' ? 'Outage ongoing:' : 'Last outage duration:') : (field === 'on_seconds' ? 'On today:' : field === 'unknown_seconds' ? 'Unknown today:' : 'Outage today:'));
      duration.querySelector('.duration-label').textContent = label;
      const rows = state?.attributes?.data;
      let text = 'Unavailable';
      if (state && !['unknown','unavailable'].includes(state.state) && lastOutage) {
        text = !outage ? 'Not recorded' : outage.status === 'awaiting_report' ? 'Awaiting recovery report' : outage.status === 'interrupted' ? 'Unknown (tracking interrupted)' : this.formatDuration(outage.seconds);
      } else if (state && !['unknown','unavailable'].includes(state.state) && Array.isArray(rows)) {
        // Daily Activity buckets use the sensor's own zone, which can differ from HA.
        const parts = new Intl.DateTimeFormat('en-US', {timeZone:state.attributes.time_zone || this.hass?.config?.time_zone || 'UTC',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
        const part = type => parts.find(p => p.type === type).value;
        const today = `${part('year')}-${part('month')}-${part('day')}`;
        const raw = rows.find(row => row?.date === today)?.[field] ?? 0;
        text = this.formatDuration(raw);
      }
      duration.querySelector('.duration-value').textContent = `${label ? ' ' : ''}${text}`;
    }
    this.activityRoot.querySelector('.hint').hidden = true;
  }
  formatDuration(raw) {
    if (raw === null || raw === undefined) return 'Not recorded';
    const seconds = Math.max(0, Math.floor(Number(raw)));
    return Number.isFinite(seconds) ? `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m ${seconds % 60}s` : 'Unavailable';
  }
  activityDay() {
    const state = this.hass?.states?.[this.config.entity];
    const raw = this.config.duration_mode === 'last_outage' ? state?.attributes?.last_outage?.start : state?.attributes?.[this.config.timestamp_attribute || 'last_activity'];
    // Never infer an event date from last_changed or the human-readable display.
    if (typeof raw === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(raw)) {
      const parsed = new Date(`${raw}T00:00:00Z`);
      return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0,10) === raw ? raw : null;
    }
    if (!(typeof raw === 'number' || (typeof raw === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(raw)))) return null;
    const date = new Date(typeof raw === 'number' ? raw * 1000 : raw);
    if (!Number.isFinite(date.getTime())) return null;
    const parts = new Intl.DateTimeFormat('en-US', {timeZone:this.hass?.config?.time_zone || 'UTC',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date);
    const part = type => parts.find(p => p.type === type).value;
    return `${part('year')}-${part('month')}-${part('day')}`;
  }
}

class SnapshotArchiveLastActivityEditor extends HTMLElement {
  constructor() { super(); this.attachShadow({mode:'open'}); }
  setConfig(config) { this.config = {...config}; this.render(); }
  set hass(value) { this._hass = value; this.updateSuggestions(); }
  render() {
    if (!this.config) return;
    this.shadowRoot.innerHTML = `<style>label {display:block;margin:12px 0} input,select {display:block;box-sizing:border-box;width:100%;padding:8px;font:inherit} p {color:var(--secondary-text-color)}</style><p>Displays the sensor’s last_activity_display, or its outage start in last-outage mode. Leave the archive camera empty for activity without pictures. Last-outage mode requires Daily Activity 0.1.1.</p>`;
    const fields = [
      ['entity','Activity sensor',''], ['camera','Archive camera entity or device ID (optional)',''],
      ['timestamp_attribute','Activity timestamp attribute (used by camera button)','last_activity'],
      ['label','Label','Last :'], ['icon','Camera icon','mdi:camera'],
      ['font_size','Text size','14px'], ['alignment','Alignment','left'],
      ['padding','Padding','16px'], ['gap','Space before camera icon','8px'],
      ['show_duration','Show duration',false],
      ['duration_mode','Duration mode','today'],
      ['duration_field','Duration to display','off_seconds'],
      ['duration_label','Duration label (blank uses default)',''],
    ];
    for (const [key,title,fallback] of fields) {
      const label = document.createElement('label'); label.append(document.createTextNode(title));
      const input = document.createElement(['alignment','duration_field','duration_mode'].includes(key) ? 'select' : 'input');
      if (key === 'show_duration') input.type = 'checkbox';
      if (key === 'duration_mode') for (const [value,title] of [['today','Today’s total'],['last_outage','Last outage (start and full duration)']]) {const option = document.createElement('option'); option.value = value; option.textContent = title; input.append(option);}
      if (key === 'duration_field') for (const [value,title] of [['off_seconds','Off / outage time'],['on_seconds','On / running time'],['unknown_seconds','Unknown time']]) {const option = document.createElement('option'); option.value = value; option.textContent = title; input.append(option);}
      if (key === 'alignment') for (const value of ['left','center','right']) { const option = document.createElement('option'); option.value = value; option.textContent = value; input.append(option); }
      input.dataset.key = key;
      input.value = (key === 'camera' ? this.config.snapshot_archive?.camera : this.config[key]) ?? fallback;
      if (key === 'show_duration') input.checked = this.config.show_duration ?? this.config.duration_mode === 'last_outage';
      if (['entity','camera','timestamp_attribute'].includes(key)) {input.setAttribute('list', `${key}-options`); const list = document.createElement('datalist'); list.id = `${key}-options`; label.append(list);}
      input.addEventListener('change', () => {
        const config = {...this.config};
        if (key === 'camera') {const archive = {...config.snapshot_archive}; if (input.value.trim()) archive.camera = input.value.trim(); else delete archive.camera; if (Object.keys(archive).length) config.snapshot_archive = archive; else delete config.snapshot_archive;}
        else if (key === 'show_duration') config[key] = input.checked;
        else if (key === 'duration_label' && !input.value) delete config.duration_label;
        else config[key] = input.value;
        this.config = config;
        this.updateSuggestions();
        this.dispatchEvent(new CustomEvent('config-changed', {detail:{config},bubbles:true,composed:true}));
      });
      label.append(input); this.shadowRoot.append(label);
    }
    this.updateSuggestions();
  }
  updateSuggestions() {
    if (!this.config) return;
    const states = this._hass?.states ?? {};
    const suggestions = {
      entity:Object.keys(states).filter(id => states[id].attributes?.last_activity_display !== undefined),
      camera:Object.keys(states).filter(id => id.startsWith('camera.')),
      timestamp_attribute:Object.keys(states[this.config.entity]?.attributes ?? {}).filter(key => key !== 'last_activity_display'),
    };
    for (const [key,values] of Object.entries(suggestions)) {
      const list = this.shadowRoot.querySelector(`#${key}-options`);
      if (list) list.replaceChildren(...values.map(value => {const option = document.createElement('option'); option.value = value; return option;}));
    }
  }
}
if (!customElements.get('snapshot-archive-last-activity')) customElements.define('snapshot-archive-last-activity', SnapshotArchiveLastActivity);
if (!customElements.get('snapshot-archive-last-activity-editor')) customElements.define('snapshot-archive-last-activity-editor', SnapshotArchiveLastActivityEditor);
window.customCards = window.customCards || [];
if (!window.customCards.some(card => card.type === 'snapshot-archive-last-activity')) window.customCards.push({type:'snapshot-archive-last-activity',name:'Snapshot Archive: Last Activity',description:'Last activity text with an optional camera archive button',preview:true});
