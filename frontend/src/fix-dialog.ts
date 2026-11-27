// "Fix" pop-up: pick the right product for an item that needs review (or
// wasn't found) from up to 5 closest matches, or search again.
// Appended to document.body so dashboard layouts can't clip it; it uses the
// page's Home Assistant theme variables.

import { LitElement, css, html, nothing } from "lit";
import type { ScanResponse } from "./text";

export interface Candidate {
  product_id: string;
  name: string;
  brand?: string | null;
  size?: string | null;
  price?: number | null;
  image_url?: string | null;
  aisle?: string | null;
  in_stock?: boolean;
}

export interface FixItem {
  item_id: string;
  name: string;
  status: string;
  quantity: number;
  candidates?: Candidate[];
}

export type CallService = (service: string, data: Record<string, unknown>) => Promise<ScanResponse & Record<string, any>>;

const MAX_MATCHES = 5;
const REMOVE_CONFIRM_MS = 4000;

/** Saved by a version before 0.14: no picture, price or aisle fields at all. */
export function isStale(candidate: Candidate): boolean {
  return !("price" in candidate) && !("image_url" in candidate) && !("aisle" in candidate);
}

export function money(value: number | null | undefined): string {
  return typeof value === "number" ? `$${value.toFixed(2)}` : "";
}

export class RestockFixDialog extends LitElement {
  static properties = {
    item: { attribute: false },
    results: { state: true },
    query: { state: true },
    busy: { state: true },
    error: { state: true },
    searched: { state: true },
    confirmRemove: { state: true },
    brokenImages: { state: true },
  };

  item!: FixItem;
  callService!: CallService;
  /** Walking several items ("Fix" button): position and a Skip button. */
  progress?: { index: number; total: number };
  onDone?: (response: ScanResponse, kind: "resolve" | "remove") => void;
  onSkip?: () => void;
  /** The user dismissed the pop-up (Cancel, close button, backdrop, Escape). */
  onClose?: () => void;

  results: Candidate[] = [];
  query = "";
  busy = false;
  error = "";
  searched = false;
  confirmRemove = false;
  brokenImages: Set<string> = new Set();

  private confirmTimer?: number;
  private keyHandler = (e: KeyboardEvent) => {
    if (e.key === "Escape") this.close();
  };

  connectedCallback(): void {
    super.connectedCallback();
    this.results = (this.item.candidates ?? []).slice(0, MAX_MATCHES);
    // A barcode that wasn't found is named after the code: not a useful search.
    this.query = this.item.status === "unmatched" && /^\d+$/.test(this.item.name) ? "" : this.item.name;
    document.addEventListener("keydown", this.keyHandler);
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    document.removeEventListener("keydown", this.keyHandler);
    window.clearTimeout(this.confirmTimer);
  }

  protected firstUpdated(): void {
    // With nothing to pick from, start typing a search right away.
    if (!this.results.length) (this.renderRoot.querySelector("input") as HTMLElement | null)?.focus();
    else if (this.query.trim() && this.results.some(isStale)) void this.refreshStale();
  }

  /** Matches saved by older versions have no picture, price or aisle: fetch them fresh. */
  private async refreshStale(): Promise<void> {
    this.busy = true;
    try {
      const result = await this.callService("search_products", { query: this.query.trim(), limit: MAX_MATCHES });
      const fresh: Candidate[] = (result.products ?? []).slice(0, MAX_MATCHES);
      if (fresh.length && this.isConnected) this.results = fresh;
    } catch {
      // Keep the saved matches; the user can still pick or search.
    } finally {
      this.busy = false;
    }
  }

  private imageFailed(url: string): void {
    this.brokenImages = new Set([...this.brokenImages, url]);
  }

  close(): void {
    this.remove();
    this.onClose?.();
  }

  /** Leave quietly after a pick or remove (onDone decides what's next). */
  private finish(): void {
    this.remove();
  }

  skip(): void {
    this.remove();
    this.onSkip?.();
  }

  async search(): Promise<void> {
    const query = this.query.trim();
    if (!query || this.busy) return;
    this.busy = true;
    this.error = "";
    try {
      const result = await this.callService("search_products", { query, limit: MAX_MATCHES });
      this.results = (result.products ?? []).slice(0, MAX_MATCHES);
      this.searched = true;
    } catch (err) {
      this.error = (err as any)?.message || String(err);
    } finally {
      this.busy = false;
    }
  }

  async pick(match: Candidate): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    this.error = "";
    try {
      const response = await this.callService("resolve_item", {
        item_id: this.item.item_id,
        product_id: match.product_id,
      });
      this.finish();
      this.onDone?.(response, "resolve");
    } catch (err) {
      this.error = (err as any)?.message || String(err);
    } finally {
      this.busy = false;
    }
  }

  async removeItem(): Promise<void> {
    if (!this.confirmRemove) {
      this.confirmRemove = true;
      window.clearTimeout(this.confirmTimer);
      this.confirmTimer = window.setTimeout(() => (this.confirmRemove = false), REMOVE_CONFIRM_MS);
      return;
    }
    this.busy = true;
    try {
      const response = await this.callService("set_quantity", { item_id: this.item.item_id, quantity: 0 });
      this.finish();
      this.onDone?.(response, "remove");
    } catch (err) {
      this.error = (err as any)?.message || String(err);
    } finally {
      this.busy = false;
    }
  }

  render() {
    const item = this.item;
    return html`
      <div class="backdrop" @click=${this.close}></div>
      <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="title">
        <header>
          <div>
            <h2 id="title">
              Pick the right product${this.progress && this.progress.total > 1
                ? html`<span class="progress">${this.progress.index} of ${this.progress.total}</span>`
                : nothing}
            </h2>
            <div class="for">
              for “${item.name}”${item.quantity > 1 ? html` ×${item.quantity}` : nothing}
            </div>
          </div>
          <button class="close" @click=${this.close} aria-label="Close">✕</button>
        </header>
        <form
          class="search"
          @submit=${(e: Event) => {
            e.preventDefault();
            void this.search();
          }}
        >
          <input
            type="search"
            enterkeyhint="search"
            autocomplete="off"
            .value=${this.query}
            @input=${(e: Event) => (this.query = (e.target as HTMLInputElement).value)}
            placeholder="Search by name, e.g. 2% milk"
            aria-label="Search products"
          />
          <button type="submit" ?disabled=${!this.query.trim() || this.busy}>Search</button>
        </form>
        ${this.error ? html`<div class="error" role="alert">${this.error}</div>` : nothing}
        <div class="list" aria-busy=${this.busy ? "true" : "false"}>
          ${this.results.length
            ? this.results.map((m) => this.renderMatch(m))
            : html`<div class="empty">
                ${this.searched
                  ? "No products found. Try other words."
                  : item.status === "unmatched"
                    ? "This barcode isn't in the Kroger catalog. Search by name to pick the product."
                    : "No matches yet. Search by name."}
              </div>`}
        </div>
        <footer>
          <button class="remove ${this.confirmRemove ? "confirm" : ""}" @click=${this.removeItem} ?disabled=${this.busy}>
            ${this.confirmRemove ? "Tap again to remove" : "Remove item"}
          </button>
          <span class="right">
            ${this.progress && this.progress.index < this.progress.total
              ? html`<button class="skip" @click=${this.skip} ?disabled=${this.busy}>Skip</button>`
              : nothing}
            <button class="cancel" @click=${this.close}>${this.progress ? "Done" : "Cancel"}</button>
          </span>
        </footer>
      </div>
    `;
  }

  private renderMatch(m: Candidate) {
    const details = [m.brand && !m.name.toLowerCase().includes(m.brand.toLowerCase()) ? m.brand : "", m.size]
      .filter(Boolean)
      .join(" · ");
    const meta = [money(m.price), m.aisle].filter(Boolean).join(" · ");
    return html`<button class="match" @click=${() => this.pick(m)} ?disabled=${this.busy}>
      ${m.image_url && !this.brokenImages.has(m.image_url)
        ? html`<img
            src=${m.image_url}
            alt=""
            loading="lazy"
            referrerpolicy="no-referrer"
            @error=${() => this.imageFailed(m.image_url!)}
          />`
        : html`<span class="noimg" aria-hidden="true"></span>`}
      <span class="text">
        <span class="name">${m.name}</span>
        ${details ? html`<span class="details">${details}</span>` : nothing}
        <span class="meta">
          ${meta}${m.in_stock === false ? html`<span class="oos">Out of stock</span>` : nothing}
        </span>
      </span>
      <span class="pick">Pick</span>
    </button>`;
  }

  static styles = css`
    :host {
      position: fixed;
      inset: 0;
      z-index: 9000;
      display: flex;
      align-items: center;
      justify-content: center;
      font-family: var(--ha-font-family-body, Roboto, sans-serif);
      color: var(--primary-text-color, #212121);
    }
    .backdrop {
      position: absolute;
      inset: 0;
      background: rgba(0, 0, 0, 0.45);
    }
    .sheet {
      position: relative;
      width: min(520px, 100% - 32px);
      max-height: min(720px, 100% - 48px);
      display: flex;
      flex-direction: column;
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-dialog-border-radius, 24px);
      box-shadow: 0 12px 40px rgba(0, 0, 0, 0.3);
      overflow: hidden;
    }
    @media (max-width: 600px) {
      :host {
        align-items: flex-end;
      }
      .sheet {
        width: 100%;
        max-height: 88%;
        border-radius: 20px 20px 0 0;
        padding-bottom: env(safe-area-inset-bottom);
      }
    }
    header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 8px;
      padding: 18px 16px 8px 20px;
    }
    h2 {
      margin: 0;
      font-size: 20px;
      font-weight: 500;
    }
    .for {
      color: var(--secondary-text-color, #727272);
      font-size: 14px;
      margin-top: 2px;
      overflow-wrap: anywhere;
    }
    button {
      font: inherit;
      color: inherit;
      cursor: pointer;
    }
    .close {
      border: none;
      background: transparent;
      font-size: 18px;
      width: 40px;
      height: 40px;
      border-radius: 20px;
      color: var(--secondary-text-color, #727272);
    }
    form.search {
      display: flex;
      gap: 8px;
      padding: 4px 16px 8px;
    }
    form.search input {
      flex: 1;
      min-width: 0;
      min-height: 42px;
      padding: 0 14px;
      font-size: 16px;
      color: inherit;
      background: var(--secondary-background-color, #f5f5f5);
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      border-radius: 21px;
      outline: none;
    }
    form.search button {
      border: none;
      border-radius: 21px;
      padding: 0 16px;
      background: var(--primary-color, #03a9f4);
      color: var(--text-primary-color, #fff);
      font-weight: 500;
    }
    form.search button:disabled {
      opacity: 0.5;
    }
    .error {
      margin: 0 16px 8px;
      padding: 8px 12px;
      border-radius: 8px;
      border-left: 4px solid var(--error-color, #db4437);
      background: var(--secondary-background-color, #f5f5f5);
      font-size: 14px;
    }
    .list {
      overflow-y: auto;
      padding: 0 8px;
      flex: 1;
    }
    .list[aria-busy="true"] {
      opacity: 0.6;
    }
    .empty {
      padding: 20px 12px;
      color: var(--secondary-text-color, #727272);
    }
    button.match {
      display: flex;
      align-items: center;
      gap: 12px;
      width: 100%;
      text-align: left;
      padding: 10px 8px;
      border: none;
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      background: transparent;
      border-radius: 0;
    }
    button.match:last-child {
      border-bottom: none;
    }
    button.match:hover,
    button.match:focus-visible {
      background: var(--secondary-background-color, #f5f5f5);
      outline: none;
    }
    img,
    .noimg {
      flex: none;
      width: 52px;
      height: 52px;
      border-radius: 8px;
      object-fit: contain;
      background: #fff;
    }
    .noimg {
      background: var(--secondary-background-color, #f5f5f5);
    }
    .text {
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 1px;
    }
    .name {
      font-size: 15px;
      line-height: 1.3;
    }
    .details,
    .meta {
      font-size: 13px;
      color: var(--secondary-text-color, #727272);
    }
    .oos {
      margin-left: 6px;
      color: var(--warning-color, #ffa600);
      font-weight: 500;
    }
    .pick {
      flex: none;
      color: var(--primary-color, #03a9f4);
      font-weight: 500;
      padding: 0 6px;
    }
    footer {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      padding: 10px 16px 14px;
      border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    }
    footer button {
      border: none;
      background: transparent;
      min-height: 40px;
      padding: 0 12px;
      border-radius: 20px;
      font-weight: 500;
    }
    .remove {
      color: var(--error-color, #db4437);
    }
    .remove.confirm {
      background: var(--error-color, #db4437);
      color: #fff;
    }
    .cancel,
    .skip {
      color: var(--primary-color, #03a9f4);
    }
    .right {
      display: flex;
      gap: 4px;
    }
    .progress {
      margin-left: 10px;
      font-size: 14px;
      font-weight: 400;
      color: var(--secondary-text-color, #727272);
      white-space: nowrap;
    }
  `;
}

if (!customElements.get("kroger-restock-fix")) {
  customElements.define("kroger-restock-fix", RestockFixDialog);
}
