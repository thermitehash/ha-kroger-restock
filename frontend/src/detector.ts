// Barcode decoding for the in-browser camera: the browser's own
// BarcodeDetector where it supports retail barcodes (Chrome on Android,
// macOS), otherwise the ZXing WebAssembly ponyfill (Safari/iOS, Firefox).
// The .wasm file is served by the integration itself, never from a CDN.

export const RETAIL_FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e"] as const;

export interface Detected {
  rawValue: string;
  format: string;
}

export interface Detector {
  detect(source: CanvasImageSource): Promise<Detected[]>;
}

export async function createDetector(wasmUrl: string): Promise<Detector> {
  const Native = (globalThis as any).BarcodeDetector;
  if (Native?.getSupportedFormats) {
    try {
      const supported: string[] = await Native.getSupportedFormats();
      if (RETAIL_FORMATS.every((f) => supported.includes(f))) {
        return new Native({ formats: [...RETAIL_FORMATS] });
      }
    } catch {
      // fall through to the ponyfill
    }
  }
  const mod = await import("barcode-detector/ponyfill");
  mod.prepareZXingModule({
    overrides: {
      locateFile: (path: string, prefix: string) =>
        path.endsWith(".wasm") ? wasmUrl : prefix + path,
    },
  });
  return new mod.BarcodeDetector({ formats: [...RETAIL_FORMATS] }) as unknown as Detector;
}
