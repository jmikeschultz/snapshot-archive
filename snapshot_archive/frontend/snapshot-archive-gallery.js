/* Snapshot Archive wrapper for Zen UI. HACS assets remain untouched. */
class SnapshotArchiveHeatmap extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>
      :host {display:block} dialog {color:var(--primary-text-color,#222);background:var(--card-background-color,#fff);border:0;border-radius:16px;padding:20px;width:min(960px,90vw);max-height:85vh;box-sizing:border-box}
      dialog::backdrop {background:rgba(0,0,0,.65)} header {display:flex;align-items:center;gap:16px} h2 {flex:1;font-size:20px} button {cursor:pointer;font:inherit;color:inherit;background:var(--secondary-background-color,#eee);border:0;border-radius:8px;padding:10px}
      .grid {display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px} .grid .tile {min-width:0} .grid .tile {overflow:hidden;border-radius:8px;background:var(--secondary-background-color,#eee)} .grid .preview {padding:0;overflow:hidden;text-align:center;width:100%;display:block;border-radius:0} .grid .caption {display:flex;align-items:center;justify-content:space-between;padding:4px 8px} .grid .caption span {padding:4px 0} .grid .delete {display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;padding:6px;background:transparent;color:var(--secondary-text-color,#666)} .grid .delete:hover {color:var(--error-color,#b00020);background:var(--card-background-color,#fff)} .grid .delete svg {width:18px;height:18px;fill:currentColor} .grid .delete[aria-busy="true"] {opacity:.4} button:disabled {cursor:default;opacity:.6} .grid img {width:100%;height:150px;object-fit:cover;display:block} .grid span {display:block;padding:8px} .full img {max-width:100%;max-height:70vh;object-fit:contain;display:block;margin:auto} .status {padding:12px 0} .more {margin-top:16px} [hidden] {display:none!important}
    </style><div class="heatmap"></div><dialog class="gallery" aria-labelledby="gallery-title"><header><h2 id="gallery-title">Snapshots</h2><button class="close" aria-label="Close gallery">Close</button></header><p class="status" role="status" aria-live="polite"></p><div class="grid"></div><button class="more" hidden>Load more</button></dialog><dialog class="full" aria-label="Full-size snapshot"><header><h2>Snapshot</h2><button class="close" aria-label="Close full-size image">Close</button></header><img alt="Archived camera snapshot"></dialog>`;
    this.gallery = this.shadowRoot.querySelector(".gallery");
    this.full = this.shadowRoot.querySelector(".full");
    this.status = this.shadowRoot.querySelector(".status");
    this.grid = this.shadowRoot.querySelector(".grid");
    this.more = this.shadowRoot.querySelector(".more");
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
  release() {
    this.generation++; this.controller?.abort();
    this.deleteOperation = null;
    for (const url of this.urls) URL.revokeObjectURL(url);
    this.urls.clear(); this.grid.replaceChildren(); this.more.hidden = true;
    this.full.close(); this.full.querySelector("img").removeAttribute("src");
  }
  async request(path, signal, options = {}) {
    if (!this.hass?.fetchWithAuth) throw new Error("Authenticated Home Assistant connection unavailable. Reload and sign in.");
    const response = await this.hass.fetchWithAuth(path, {...options, signal: AbortSignal.any([signal, AbortSignal.timeout(30000)])});
    if (!response.ok) {
      const error = new Error(response.status === 401 || response.status === 403 ? "Authentication failed. Sign in again or check permissions." : `Archive request failed (${response.status}).`);
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
    if (!window.confirm("Permanently delete this archived snapshot? This cannot be undone.")) return;
    const operation = Symbol("delete");
    this.deleteOperation = operation;
    this.grid.querySelectorAll(".delete").forEach(item => {item.disabled = true;});
    button.setAttribute("aria-busy", "true");
    try {
      try {
        await this.request(snapshot.url, this.controller.signal, {method:"DELETE"});
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
      caption.append(label, remove); tile.append(button, caption); this.grid.append(tile);
      return {snapshot,button,label};
    });
    let index = 0;
    await Promise.all(Array.from({length:Math.min(4,jobs.length)}, async () => {
      while (index < jobs.length && generation === this.generation) {
        const {snapshot,button,label} = jobs[index++];
        try {
          const response = await this.request(snapshot.url, this.controller.signal);
          const blob = await response.blob();
          if (generation !== this.generation) return;
          if (!blob.type.startsWith("image/")) throw new Error("Invalid image response");
          const url = URL.createObjectURL(blob); this.urls.add(url);
          const img = document.createElement("img"); img.src = url; img.alt = `Snapshot at ${label.textContent}`;
          img.onerror = () => {label.textContent = "Image could not be decoded"; button.disabled = true;};
          button.prepend(img); button.disabled = false;
          button.onclick = () => {this.full.querySelector("img").src = url; this.full.querySelector("h2").textContent = label.textContent; this.full.showModal();};
        } catch (error) {if (generation === this.generation && error.name !== "AbortError") label.textContent = error.message;}
      }
    }));
    if (generation === this.generation) this.more.hidden = this.offset >= this.snapshots.length;
  }
}
if (!customElements.get("snapshot-archive-heatmap")) customElements.define("snapshot-archive-heatmap", SnapshotArchiveHeatmap);
