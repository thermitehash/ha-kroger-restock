// Full-screen in-browser camera scanner (used when the companion app's
// native scanner isn't available). Appended to document.body so dashboard
// layouts can't clip it.

import { LitElement, css, html, nothing } from "lit";
import { createDetector, type Detector } from "./detector";
import type { ResultLine } from "./text";

const SCAN_INTERVAL_MS = 200;
const SAME_CODE_COOLDOWN_MS = 3000;

export class RestockCameraScanner extends LitElement {
  static properties = {
    message: { attribute: false },
    error: { state: true },
    cameras: { state: true },
    cameraId: { state: true },
  };

  wasmUrl = "";
  onCode?: (code: string) => void;
  onClose?: () => void;
  message?: ResultLine;
  error = "";
  cameras: MediaDeviceInfo[] = [];
  cameraId = "";

  private stream?: MediaStream;
  private detector?: Detector;
  private timer?: number;
  private busy = false;
  private lastCode = "";
  private lastAt = 0;

  static styles = css`
    :host {
      position: fixed;
      inset: 0;
      z-index: 10000;
      background: #000;
      color: #fff;
      display: flex;
      flex-direction: column;
      font-family: var(--ha-font-family-body, Roboto, sans-serif);
    }
    video {
      flex: 1;
      width: 100%;
      min-height: 0;
      object-fit: cover;
    }
    .frame {
      position: absolute;
      left: 10%;
      right: 10%;
      top: 35%;
      height: 22%;
      border: 2px solid rgba(255, 255, 255, 0.85);
      border-radius: 12px;
      pointer-events: none;
      box-shadow: 0 0 0 100vmax rgba(0, 0, 0, 0.35);
    }
    .top,
    .bottom {
      position: absolute;
      left: 0;
      right: 0;
      padding: 12px 16px;
      padding-top: max(12px, env(safe-area-inset-top));
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .top {
      top: 0;
      justify-content: space-between;
    }
    .bottom {
      bottom: 0;
      padding-bottom: max(16px, env(safe-area-inset-bottom));
      flex-direction: column;
      align-items: stretch;
    }
    button,
    select {
      font: inherit;
      color: #fff;
      background: rgba(0, 0, 0, 0.55);
      border: 1px solid rgba(255, 255, 255, 0.5);
      border-radius: 20px;
      padding: 8px 14px;
      min-height: 40px;
    }
    .msg {
      background: rgba(0, 0, 0, 0.7);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 15px;
      line-height: 1.35;
    }
    .msg.success {
      border-left: 4px solid #43a047;
    }
    .msg.info {
      border-left: 4px solid #1e88e5;
    }
    .msg.warning {
      border-left: 4px solid #fb8c00;
    }
    .msg.error {
      border-left: 4px solid #e53935;
    }
    .hint {
      opacity: 0.8;
      font-size: 13px;
      text-align: center;
    }
  `;

  connectedCallback(): void {
    super.connectedCallback();
    void this.start();
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    this.stop();
  }

  private async start(deviceId?: string): Promise<void> {
    this.stopStream();
    this.error = "";
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      this.error =
        "The camera needs a secure (https) connection, for example Home Assistant Cloud. Type the barcode instead.";
      return;
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: deviceId
          ? { deviceId: { exact: deviceId } }
          : { facingMode: { ideal: "environment" }, width: { ideal: 1280 } },
      });
    } catch (err) {
      this.error = `Can't open the camera: ${(err as Error).message || err}. Check the camera permission.`;
      return;
    }
    await this.updateComplete;
    const video = this.renderRoot.querySelector("video");
    if (!video) return;
    video.srcObject = this.stream;
    await video.play().catch(() => undefined);
    const track = this.stream.getVideoTracks()[0];
    this.cameraId = track?.getSettings().deviceId ?? "";
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      this.cameras = devices.filter((d) => d.kind === "videoinput");
    } catch {
      this.cameras = [];
    }
    try {
      this.detector ??= await createDetector(this.wasmUrl);
    } catch (err) {
      this.error = `Barcode reader failed to load: ${(err as Error).message || err}`;
      return;
    }
    this.timer = window.setInterval(() => void this.tick(video), SCAN_INTERVAL_MS);
  }

  private async tick(video: HTMLVideoElement): Promise<void> {
    if (this.busy || !this.detector || video.readyState < 2) return;
    this.busy = true;
    try {
      const found = await this.detector.detect(video);
      const code = found[0]?.rawValue;
      const now = Date.now();
      if (code && (code !== this.lastCode || now - this.lastAt > SAME_CODE_COOLDOWN_MS)) {
        this.lastCode = code;
        this.lastAt = now;
        navigator.vibrate?.(60);
        this.onCode?.(code);
      }
    } catch {
      // a bad frame; keep going
    } finally {
      this.busy = false;
    }
  }

  private stopStream(): void {
    if (this.timer !== undefined) window.clearInterval(this.timer);
    this.timer = undefined;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = undefined;
  }

  stop(): void {
    this.stopStream();
  }

  private close(): void {
    this.stop();
    this.onClose?.();
  }

  render() {
    return html`
      <video playsinline muted></video>
      ${this.error ? nothing : html`<div class="frame"></div>`}
      <div class="top">
        <button @click=${this.close} aria-label="Close scanner">✕ Done</button>
        ${this.cameras.length > 1
          ? html`<select
              aria-label="Camera"
              .value=${this.cameraId}
              @change=${(e: Event) => this.start((e.target as HTMLSelectElement).value)}
            >
              ${this.cameras.map(
                (c, i) =>
                  html`<option value=${c.deviceId} ?selected=${c.deviceId === this.cameraId}>
                    ${c.label || `Camera ${i + 1}`}
                  </option>`,
              )}
            </select>`
          : nothing}
      </div>
      <div class="bottom">
        ${this.error
          ? html`<div class="msg error" role="alert">${this.error}</div>`
          : this.message
            ? html`<div class="msg ${this.message.tone}" role="status">${this.message.text}</div>`
            : html`<div class="hint">Aim at the barcode. Keep scanning; tap Done when finished.</div>`}
      </div>
    `;
  }
}

if (!customElements.get("kroger-restock-camera")) {
  customElements.define("kroger-restock-camera", RestockCameraScanner);
}
