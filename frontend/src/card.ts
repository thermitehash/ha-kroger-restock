// "Restock scanner" card: scan or type items onto the Kroger Restock list and
// see (and fix) the most recently added items.

import { LitElement, css, html, nothing, type PropertyValues } from "lit";
import "./camera";
import type { RestockCameraScanner } from "./camera";
import "./fix-dialog";
import type { Candidate, RestockFixDialog } from "./fix-dialog";
import { NativeScanner, externalBus, nativeScannerAvailable } from "./native-scanner";
import {
  classifyInput,
  quantityLine,
  relativeTime,
  resultLine,
  type ResultLine,
  type ScanResponse,
} from "./text";

export const CARD_TYPE = "kroger-restock-card";
const DOMAIN = "kroger_restock";
const REMOVE_CONFIRM_MS = 4000;
const SAME_CODE_MS = 3000;

export type ScannerMode = "auto" | "app" | "camera" | "off";

export interface CardConfig {
  type: string;
  entity?: string;
  title?: string;
  rows?: number;
  scanner?: ScannerMode;
  show_input?: boolean;
  show_actions?: boolean;
  shortcut?: string;
}

export interface RecentItem {
  item_id: string;
  name: string;
  size?: string | null;
  quantity: number;
  status: string;
  status_text?: string;
  aisle?: string | null;
  result?: string;
  at?: string;
  added?: number;
  can_undo?: boolean;
  candidates?: Candidate[];
}

/** Where the card's own files (the .wasm reader) are served from. */
function assetBase(): { base: string; version: string } {
  try {
    const url = new URL(import.meta.url);
    return {
      base: url.href.slice(0, url.href.lastIndexOf("/") + 1).split("?")[0],
      version: url.searchParams.get("v") ?? "",
    };
  } catch {
    return { base: "/kroger_restock_frontend/", version: "" };
  }
}

function haptic(kind: "success" | "warning" | "failure" | "light"): void {
  window.dispatchEvent(new CustomEvent("haptic", { detail: kind }));
}

export class KrogerRestockCard extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    _line: { state: true },
    _busy: { state: true },
    _text: { state: true },
    _confirmRemove: { state: true },
    _scanning: { state: true },
  };

  hass: any;
  _config!: CardConfig;
  _line?: ResultLine;
  _busy = false;
  _text = "";
  _confirmRemove?: string;
  _scanning = false;

  private native?: NativeScanner;
  private camera?: RestockCameraScanner;
  private queue: Promise<unknown> = Promise.resolve();
  private lastCode = "";
  private lastCodeAt = 0;
  private confirmTimer?: number;
  private clock?: number;

  static getConfigElement(): HTMLElement {
    return document.createElement(`${CARD_TYPE}-editor`);
  }

  static getStubConfig(hass: any): Partial<CardConfig> {
    return { entity: findRecentSensor(hass) ?? "", rows: 10 };
  }

  setConfig(config: CardConfig): void {
    if (!config) throw new Error("Invalid configuration");
    this._config = {
      rows: 10,
      scanner: "auto",
      show_input: true,
      show_actions: true,
      ...config,
    };
  }

  getCardSize(): number {
    return 2 + Math.min(this.items.length, this._config?.rows ?? 10);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  connectedCallback(): void {
    super.connectedCallback();
    // Keep "5 min ago" fresh.
    this.clock = window.setInterval(() => this.requestUpdate(), 30_000);
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    window.clearInterval(this.clock);
    window.clearTimeout(this.confirmTimer);
    this.native?.close();
    this.closeCamera();
  }

  protected shouldUpdate(changed: PropertyValues): boolean {
    if (!changed.has("hass") || changed.size > 1) return true;
    const old = changed.get("hass");
    const id = this.entityId;
    return !old || !id || old.states[id] !== this.hass.states[id];
  }

  // ------------------------------------------------------------------
  // Data

  get entityId(): string | undefined {
    return this._config?.entity || findRecentSensor(this.hass);
  }

  get stateObj(): any {
    const id = this.entityId;
    return id ? this.hass?.states?.[id] : undefined;
  }

  get items(): RecentItem[] {
    const items = this.stateObj?.attributes?.items;
    return Array.isArray(items) ? items : [];
  }

  /** Every item waiting for a product pick, oldest first. */
  get needsFix(): RecentItem[] {
    const items = this.stateObj?.attributes?.needs_fix;
    return Array.isArray(items) ? items : [];
  }

  get entryId(): string | undefined {
    return this.stateObj?.attributes?.config_entry_id;
  }

  get scannerKind(): "app" | "camera" | null {
    const mode = this._config?.scanner ?? "auto";
    if (mode === "off") return null;
    const app = nativeScannerAvailable(this.hass);
    if (mode === "app") return app ? "app" : null;
    if (mode === "camera") return "camera";
    return app ? "app" : "camera";
  }

  async callService(service: string, data: Record<string, unknown>): Promise<ScanResponse> {
    const serviceData = { ...data };
    if (this.entryId) serviceData.config_entry_id = this.entryId;
    const result = await this.hass.connection.sendMessagePromise({
      type: "call_service",
      domain: DOMAIN,
      service,
      service_data: serviceData,
      return_response: true,
    });
    return (result?.response ?? {}) as ScanResponse;
  }

  private show(line: ResultLine): void {
    this._line = line;
    haptic(line.tone === "success" ? "success" : line.tone === "error" ? "failure" : "warning");
  }

  private showError(err: unknown): ResultLine {
    const line: ResultLine = {
      text: (err as any)?.message || String(err),
      tone: "error",
    };
    this.show(line);
    return line;
  }

  /** Run actions one at a time, in order. */
  private enqueue<T>(job: () => Promise<T>): Promise<T> {
    const next = this.queue.then(job, job);
    this.queue = next.catch(() => undefined);
    return next;
  }

  // ------------------------------------------------------------------
  // Adding

  async scanCode(code: string): Promise<ResultLine | undefined> {
    const now = Date.now();
    if (code === this.lastCode && now - this.lastCodeAt < SAME_CODE_MS) return undefined;
    this.lastCode = code;
    this.lastCodeAt = now;
    return this.enqueue(async () => {
      this._busy = true;
      try {
        const line = resultLine(await this.callService("scan_upc", { upc: code, source: "card" }));
        this.show(line);
        return line;
      } catch (err) {
        return this.showError(err);
      } finally {
        this._busy = false;
      }
    });
  }

  async submitText(): Promise<void> {
    const raw = this._text;
    const input = classifyInput(raw);
    if (!input) return;
    // Clear now, so typing the next item while this one is added isn't lost.
    this._text = "";
    await this.enqueue(async () => {
      this._busy = true;
      try {
        let response: ScanResponse;
        if (input.kind === "url") {
          response = await this.callService("scan_upc", { url: input.value, source: "card" });
        } else if (input.kind === "upc") {
          response = await this.callService("scan_upc", { upc: input.value, source: "card" });
        } else {
          response = await this.callService("add_item", { name: input.value, source: "card" });
        }
        this.show(resultLine(response));
      } catch (err) {
        this.showError(err);
        if (!this._text) this._text = raw; // give it back to fix and retry
      } finally {
        this._busy = false;
      }
    });
  }

  // ------------------------------------------------------------------
  // Scanning

  startScan(): void {
    const kind = this.scannerKind;
    if (kind === "app") this.startNative();
    else if (kind === "camera") this.openCamera();
  }

  private startNative(): void {
    const bus = externalBus(this.hass);
    if (!bus) return;
    this.native ??= new NativeScanner(bus);
    this._scanning = true;
    this.native.start({
      title: "Scan groceries",
      description: "Aim at the barcode. Keep scanning; close when you're done.",
      alternativeLabel: "Type it instead",
      onCode: (code) => {
        void this.scanCode(code).then((line) => {
          if (line) this.native?.notify(line.text);
        });
      },
      onClose: (reason) => {
        this._scanning = false;
        if (reason === "alternative_options") {
          void this.updateComplete.then(() =>
            (this.renderRoot.querySelector("input") as HTMLInputElement | null)?.focus(),
          );
        }
      },
    });
  }

  private openCamera(): void {
    if (this.camera) return;
    const { base, version } = assetBase();
    const camera = document.createElement("kroger-restock-camera") as RestockCameraScanner;
    camera.wasmUrl = `${base}zxing_reader.wasm${version ? `?v=${version}` : ""}`;
    camera.onCode = (code) => {
      void this.scanCode(code).then((line) => {
        if (line && this.camera) this.camera.message = line;
      });
    };
    camera.onClose = () => this.closeCamera();
    document.body.appendChild(camera);
    this.camera = camera;
    this._scanning = true;
  }

  private closeCamera(): void {
    this.camera?.remove();
    this.camera = undefined;
    this._scanning = false;
  }

  // ------------------------------------------------------------------
  // Row actions

  async setQuantity(item: RecentItem, quantity: number): Promise<void> {
    if (quantity < 1 && this._confirmRemove !== item.item_id) {
      this._confirmRemove = item.item_id;
      window.clearTimeout(this.confirmTimer);
      this.confirmTimer = window.setTimeout(() => (this._confirmRemove = undefined), REMOVE_CONFIRM_MS);
      haptic("light");
      return;
    }
    this._confirmRemove = undefined;
    await this.enqueue(async () => {
      this._busy = true;
      try {
        this.show(quantityLine(await this.callService("set_quantity", { item_id: item.item_id, quantity })));
      } catch (err) {
        this.showError(err);
      } finally {
        this._busy = false;
      }
    });
  }

  undo(item: RecentItem): Promise<void> {
    return this.setQuantity(item, item.quantity - (item.added ?? 1));
  }

  /** Open the "Pick the right product" pop-up for one item. */
  openFix(item: RecentItem, progress?: { index: number; total: number }): RestockFixDialog {
    document.querySelector("kroger-restock-fix")?.remove();
    const dialog = document.createElement("kroger-restock-fix") as RestockFixDialog;
    dialog.item = item;
    dialog.progress = progress;
    dialog.callService = (service, data) => this.callService(service, data);
    dialog.onDone = (response, kind) =>
      this.show(kind === "remove" ? quantityLine(response) : resultLine(response));
    document.body.appendChild(dialog);
    return dialog;
  }

  /** "Fix" button: walk every item that needs a product pick, one by one. */
  fixAll(): void {
    const queue = this.needsFix.map((i) => i.item_id);
    const total = queue.length;
    let index = 0;
    const next = () => {
      const current = new Map(this.needsFix.map((i) => [i.item_id, i]));
      while (queue.length && !current.has(queue[0])) {
        queue.shift(); // fixed elsewhere meanwhile
        index += 1;
      }
      const id = queue.shift();
      if (id === undefined) return;
      index += 1;
      const dialog = this.openFix(current.get(id)!, { index, total });
      dialog.onDone = (response, kind) => {
        this.show(kind === "remove" ? quantityLine(response) : resultLine(response));
        next();
      };
      dialog.onSkip = next;
    };
    next();
  }

  // ------------------------------------------------------------------
  // Rendering

  render() {
    if (!this._config || !this.hass) return nothing;
    const config = this._config;
    const stateObj = this.stateObj;
    const scanner = this.scannerKind;
    const rows = this.items.slice(0, config.rows ?? 10);
    return html`
      <ha-card .header=${config.title || undefined}>
        <div class="controls">
          ${scanner
            ? html`<button
                class="scan"
                @click=${this.startScan}
                ?disabled=${this._scanning}
                aria-label="Scan a barcode"
              >
                <ha-icon icon="mdi:barcode-scan"></ha-icon><span>Scan</span>
              </button>`
            : nothing}
          ${this.renderFixButton()}
          ${config.shortcut
            ? html`<a
                class="scan secondary"
                href=${`shortcuts://run-shortcut?name=${encodeURIComponent(config.shortcut)}`}
                aria-label="Run the iPhone Shortcut"
                ><ha-icon icon="mdi:apple-ios"></ha-icon><span>Shortcut</span></a
              >`
            : nothing}
          ${config.show_input
            ? html`<form
                class="add"
                @submit=${(e: Event) => {
                  e.preventDefault();
                  void this.submitText();
                }}
              >
                <input
                  type="text"
                  enterkeyhint="send"
                  autocomplete="off"
                  .value=${this._text}
                  @input=${(e: Event) => (this._text = (e.target as HTMLInputElement).value)}
                  placeholder="Barcode, name or link"
                  aria-label="Barcode, item name or Kroger link"
                />
                <button type="submit" ?disabled=${!this._text.trim() || this._busy} aria-label="Add">
                  <ha-icon icon="mdi:plus"></ha-icon>
                </button>
              </form>`
            : nothing}
        </div>
        ${this._line
          ? html`<div class="line ${this._line.tone}" role="status">${this._line.text}</div>`
          : nothing}
        ${!stateObj
          ? html`<div class="empty warn">
              Pick the Kroger Restock "Recently scanned" sensor in the card settings.
            </div>`
          : rows.length === 0
            ? html`<div class="empty">Nothing scanned yet.</div>`
            : html`<ul class="rows">
                ${rows.map((item) => this.renderRow(item))}
              </ul>`}
      </ha-card>
    `;
  }

  private renderFixButton() {
    const count = this.needsFix.length;
    return html`<button
      class="fixall"
      @click=${this.fixAll}
      ?disabled=${count === 0}
      aria-label=${count ? `Fix ${count} item${count === 1 ? "" : "s"} that need a product picked` : "Nothing to fix"}
      title=${count ? "Pick the right product for items that need review" : "Nothing needs fixing"}
    >
      <ha-icon icon="mdi:auto-fix"></ha-icon><span>Fix</span>${count
        ? html`<span class="badge">${count > 99 ? "99+" : count}</span>`
        : nothing}
    </button>`;
  }

  private renderRow(item: RecentItem) {
    const actions = this._config.show_actions;
    const review = item.status === "needs_review" || item.status === "unmatched";
    const confirming = this._confirmRemove === item.item_id;
    const name = [item.name, item.size ? `(${item.size})` : ""].filter(Boolean).join(" ");
    return html`<li class="row status-${item.status}">
      <div class="main">
        <div class="name">
          <span>${name}</span>${item.quantity > 1 ? html`<span class="qty">×${item.quantity}</span>` : nothing}
        </div>
        <div class="sub">
          ${item.status_text ?? item.status}${item.at ? html` · ${relativeTime(item.at)}` : nothing}
        </div>
      </div>
      ${actions
        ? html`<div class="actions">
            ${item.can_undo
              ? html`<button class="text" @click=${() => this.undo(item)} ?disabled=${this._busy}>
                  Undo +${item.added ?? 1}
                </button>`
              : nothing}
            ${review
              ? html`<button class="text" @click=${() => this.openFix(item)}>Fix</button>`
              : nothing}
            <button
              class="icon ${confirming ? "confirm" : ""}"
              @click=${() => this.setQuantity(item, item.quantity - 1)}
              ?disabled=${this._busy}
              aria-label=${item.quantity > 1 ? `One less ${item.name}` : `Remove ${item.name}`}
            >
              ${confirming
                ? html`<span>Remove?</span>`
                : html`<ha-icon icon=${item.quantity > 1 ? "mdi:minus" : "mdi:delete-outline"}></ha-icon>`}
            </button>
            <button
              class="icon"
              @click=${() => this.setQuantity(item, item.quantity + 1)}
              ?disabled=${this._busy || item.quantity >= 99}
              aria-label=${`One more ${item.name}`}
            >
              <ha-icon icon="mdi:plus"></ha-icon>
            </button>
          </div>`
        : nothing}
    </li>`;
  }

  static styles = css`
    ha-card {
      overflow: hidden;
    }
    .controls {
      display: flex;
      gap: 8px;
      padding: 12px 12px 4px;
      flex-wrap: wrap;
    }
    button,
    input,
    a.scan {
      font: inherit;
      color: inherit;
    }
    .scan {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 44px;
      padding: 0 16px;
      border: none;
      border-radius: 22px;
      background: var(--primary-color);
      color: var(--text-primary-color, #fff);
      font-weight: 500;
      cursor: pointer;
      text-decoration: none;
    }
    .scan.secondary {
      background: transparent;
      color: var(--primary-color);
      border: 1px solid var(--primary-color);
    }
    .scan:disabled {
      opacity: 0.6;
    }
    .fixall {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 44px;
      padding: 0 14px;
      border-radius: 22px;
      border: 1px solid var(--warning-color, #ffa600);
      background: transparent;
      color: var(--warning-color, #ffa600);
      font-weight: 500;
      cursor: pointer;
    }
    .fixall .badge {
      min-width: 22px;
      height: 22px;
      padding: 0 6px;
      box-sizing: border-box;
      border-radius: 11px;
      background: var(--warning-color, #ffa600);
      color: #fff;
      font-size: 13px;
      line-height: 22px;
      text-align: center;
    }
    .fixall:disabled {
      border-color: var(--divider-color);
      color: var(--disabled-text-color, #bdbdbd);
      cursor: default;
    }
    form.add {
      flex: 1 1 200px;
      display: flex;
      min-width: 0;
      border: 1px solid var(--divider-color);
      border-radius: 22px;
      overflow: hidden;
      background: var(--card-background-color);
    }
    form.add input {
      flex: 1;
      min-width: 0;
      border: none;
      background: transparent;
      padding: 0 14px;
      min-height: 42px;
      font-size: 16px; /* no zoom on iOS */
      outline: none;
    }
    form.add button {
      border: none;
      background: transparent;
      color: var(--primary-color);
      width: 44px;
      cursor: pointer;
    }
    form.add button:disabled {
      color: var(--disabled-text-color);
    }
    .line {
      margin: 8px 12px 0;
      padding: 8px 12px;
      border-radius: 8px;
      border-left: 4px solid var(--info-color, #039be5);
      background: var(--secondary-background-color);
      font-size: 14px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .line.success {
      border-left-color: var(--success-color, #43a047);
    }
    .line.warning {
      border-left-color: var(--warning-color, #ffa600);
    }
    .line.error {
      border-left-color: var(--error-color, #db4437);
    }
    .empty {
      padding: 16px 12px 20px;
      color: var(--secondary-text-color);
    }
    .empty.warn {
      color: var(--warning-color, #ffa600);
    }
    ul.rows {
      list-style: none;
      margin: 8px 0 4px;
      padding: 0;
    }
    li.row {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-top: 1px solid var(--divider-color);
    }
    li.row:first-child {
      border-top: none;
    }
    .main {
      flex: 1;
      min-width: 0;
    }
    .name {
      display: flex;
      gap: 6px;
      align-items: baseline;
      font-size: 15px;
      line-height: 1.3;
    }
    .name span:first-child {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .qty {
      flex: none;
      font-weight: 600;
      color: var(--primary-color);
    }
    .sub {
      font-size: 12.5px;
      color: var(--secondary-text-color);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .status-needs_review .sub,
    .status-unmatched .sub,
    .status-check_cart .sub {
      color: var(--warning-color, #ffa600);
    }
    .actions {
      flex: none;
      display: flex;
      align-items: center;
      gap: 2px;
    }
    .actions button {
      border: none;
      background: transparent;
      cursor: pointer;
      min-height: 40px;
      border-radius: 20px;
      color: var(--secondary-text-color);
    }
    .actions button.icon {
      min-width: 40px;
    }
    .actions button.text {
      color: var(--primary-color);
      font-weight: 500;
      padding: 0 8px;
    }
    .actions button.confirm {
      color: var(--error-color, #db4437);
      font-weight: 600;
      padding: 0 8px;
    }
    .actions button:disabled {
      opacity: 0.5;
    }
  `;
}

/** The first "Recently scanned" sensor of this integration. */
export function findRecentSensor(hass: any): string | undefined {
  if (!hass?.states) return undefined;
  return Object.keys(hass.states).find((id) => {
    const attrs = hass.states[id]?.attributes;
    return id.startsWith("sensor.") && Array.isArray(attrs?.items) && "todo_entity_id" in (attrs ?? {});
  });
}
