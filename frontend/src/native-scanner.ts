// The Home Assistant companion app's native barcode scanner.
//
// The app advertises it with `hasBarCodeScanner` and opens it on a
// "bar_code/scan" message. Results come back through the app's call to
// window.externalBus(msg), which HA's frontend routes to its own internal
// listeners. A custom card can't register there, so we wrap
// window.externalBus: we look at scan results and then hand every message on
// unchanged, so HA still acknowledges it. This relies on an undocumented
// interface; if it isn't there, `available()` is false and the card falls
// back to the camera or the text field.

export interface ExternalBus {
  config?: { hasBarCodeScanner?: number | boolean };
  fireMessage: (msg: Record<string, unknown>) => void;
}

type Listener = (msg: unknown) => unknown;

interface BusWindow {
  externalBus?: Listener;
}

export function externalBus(hass: any): ExternalBus | undefined {
  return hass?.auth?.external;
}

export function nativeScannerAvailable(hass: any, win: BusWindow = window as any): boolean {
  const bus = externalBus(hass);
  return Boolean(
    bus?.config?.hasBarCodeScanner &&
      typeof bus.fireMessage === "function" &&
      typeof win.externalBus === "function",
  );
}

export interface NativeScanOptions {
  title: string;
  description: string;
  alternativeLabel?: string;
  onCode: (code: string, format: string) => void;
  /** reason: "canceled" | "alternative_options" | "replaced" */
  onClose: (reason: string) => void;
}

export class NativeScanner {
  private original?: Listener;
  private wrapper?: Listener;
  private options?: NativeScanOptions;

  constructor(
    private readonly bus: ExternalBus,
    private readonly win: BusWindow = window as any,
  ) {}

  get open(): boolean {
    return this.wrapper !== undefined;
  }

  start(options: NativeScanOptions): void {
    if (this.open) this.restore();
    this.options = options;
    this.original = this.win.externalBus;
    const original = this.original!;
    this.wrapper = (msg: unknown) => {
      try {
        this.inspect(typeof msg === "string" ? JSON.parse(msg) : msg);
      } catch {
        // Never break HA's own message handling.
      }
      return original(msg);
    };
    this.win.externalBus = this.wrapper;
    this.bus.fireMessage({
      type: "bar_code/scan",
      payload: {
        title: options.title,
        description: options.description,
        ...(options.alternativeLabel ? { alternative_option_label: options.alternativeLabel } : {}),
      },
    });
  }

  /** Show a short message in the open scanner (e.g. the last result). */
  notify(message: string): void {
    if (!this.open) return;
    this.bus.fireMessage({ type: "bar_code/notify", payload: { message } });
  }

  close(): void {
    if (!this.open) return;
    this.bus.fireMessage({ type: "bar_code/close" });
    this.restore();
  }

  private inspect(msg: any): void {
    if (!msg || msg.type !== "command") return;
    if (msg.command === "bar_code/scan_result") {
      const payload = msg.payload ?? {};
      if (typeof payload.rawValue === "string") {
        this.options?.onCode(payload.rawValue, String(payload.format ?? "unknown"));
      }
    } else if (msg.command === "bar_code/aborted") {
      const reason = String(msg.payload?.reason ?? "canceled");
      const options = this.options;
      this.restore();
      options?.onClose(reason);
    }
  }

  private restore(): void {
    if (this.wrapper && this.win.externalBus === this.wrapper && this.original) {
      this.win.externalBus = this.original;
    }
    this.wrapper = undefined;
    this.original = undefined;
    this.options = undefined;
  }
}
