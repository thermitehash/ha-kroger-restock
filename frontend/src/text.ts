// Pure helpers: result text, input classification, relative times.

export interface ScanResponse {
  result?: string;
  name?: string | null;
  size?: string | null;
  aisle?: string | null;
  quantity?: number;
  upc?: string | null;
  message?: string;
  reason?: string;
  pushed?: boolean;
  already_in_cart?: boolean;
  debounced?: boolean;
  added?: number;
  error?: string;
  warning?: string;
  previous_quantity?: number;
  kroger_cart_remove?: number;
  item_id?: string;
}

export type Tone = "success" | "info" | "warning" | "error";

export interface ResultLine {
  text: string;
  tone: Tone;
}

/** One line describing what a scan_upc / add_item response means. */
export function resultLine(r: ScanResponse): ResultLine {
  const name = r.name ?? "";
  switch (r.result) {
    case "in_cart": {
      let text = [name, r.size].filter(Boolean).join(" ");
      if (r.aisle) text += ` · ${r.aisle}`;
      if (r.already_in_cart) return { text: `✓ In cart (recorded): ${text}`, tone: "success" };
      if (r.pushed === false) return { text: `✓ On list, cart push pending: ${text}`, tone: "warning" };
      return { text: `✓ In cart: ${text}`, tone: "success" };
    }
    case "waiting":
      return { text: `⏳ Waiting on stock: ${name}`, tone: "info" };
    case "unmatched":
      return { text: `? Unknown code ${r.upc || name} (added for you to fix)`, tone: "warning" };
    case "needs_review":
      return { text: `• Needs review: ${name}`, tone: "warning" };
    case "duplicate":
      if (r.debounced) return { text: "Already scanned", tone: "info" };
      return { text: `↺ Already on list (qty ${r.quantity}): ${name}`, tone: "info" };
    case "ignored":
      return { text: `⊘ ${r.message || "Ignored"}`, tone: "warning" };
    default:
      return { text: r.error || "Done", tone: r.error ? "error" : "info" };
  }
}

/** Result of set_quantity. */
export function quantityLine(r: ScanResponse): ResultLine {
  if (r.warning) return { text: `⚠ ${r.warning}`, tone: "warning" };
  if (r.result === "removed") return { text: `Removed: ${r.name}`, tone: "info" };
  if (r.error) return { text: `Quantity ${r.quantity} saved; cart push pending: ${r.name}`, tone: "warning" };
  return { text: `${r.name}: ×${r.quantity}`, tone: "success" };
}

export type InputKind =
  | { kind: "url"; value: string }
  | { kind: "upc"; value: string }
  | { kind: "name"; value: string };

/** Decide whether typed text is a link, a barcode or an item name. */
export function classifyInput(raw: string): InputKind | null {
  const value = raw.trim();
  if (!value) return null;
  if (/https?:\/\//i.test(value)) return { kind: "url", value };
  const digits = value.replace(/[\s-]/g, "");
  if (/^\d{4,14}$/.test(digits)) return { kind: "upc", value: digits };
  return { kind: "name", value };
}

/** "just now", "5 min ago", "3 h ago", "2 d ago". */
export function relativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, Math.round((now - then) / 1000));
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}
