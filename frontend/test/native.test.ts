import { describe, expect, it, vi } from "vitest";
import { NativeScanner, nativeScannerAvailable } from "../src/native-scanner";

function setup(hasScanner = 1) {
  const handled: unknown[] = [];
  const win: { externalBus?: (m: unknown) => unknown } = {
    externalBus: (m) => {
      handled.push(m);
      return true;
    },
  };
  const bus = { config: { hasBarCodeScanner: hasScanner }, fireMessage: vi.fn() };
  const hass = { auth: { external: bus } };
  return { win, bus, hass, handled };
}

describe("nativeScannerAvailable", () => {
  it("needs the app capability and the bus", () => {
    const { win, hass } = setup();
    expect(nativeScannerAvailable(hass, win)).toBe(true);
    expect(nativeScannerAvailable(setup(0).hass, win)).toBe(false);
    expect(nativeScannerAvailable({ auth: {} }, win)).toBe(false);
    expect(nativeScannerAvailable(hass, {})).toBe(false);
  });
});

describe("NativeScanner", () => {
  it("opens, reports codes, passes every message on, restores on abort", () => {
    const { win, bus, handled } = setup();
    const original = win.externalBus;
    const codes: string[] = [];
    const closed: string[] = [];
    const scanner = new NativeScanner(bus, win);
    scanner.start({
      title: "Scan",
      description: "Aim",
      alternativeLabel: "Type it",
      onCode: (c) => codes.push(c),
      onClose: (r) => closed.push(r),
    });
    expect(bus.fireMessage).toHaveBeenCalledWith({
      type: "bar_code/scan",
      payload: { title: "Scan", description: "Aim", alternative_option_label: "Type it" },
    });
    expect(win.externalBus).not.toBe(original);

    const result = {
      id: 5,
      type: "command",
      command: "bar_code/scan_result",
      payload: { rawValue: "049000028911", format: "upc_a" },
    };
    win.externalBus!(result);
    win.externalBus!(JSON.stringify({ ...result, payload: { rawValue: "0002", format: "ean_13" } }));
    win.externalBus!({ id: 6, type: "command", command: "navigate", payload: {} });
    expect(codes).toEqual(["049000028911", "0002"]);
    expect(handled).toHaveLength(3); // HA still gets (and acknowledges) everything

    scanner.notify("✓ In cart");
    expect(bus.fireMessage).toHaveBeenLastCalledWith({
      type: "bar_code/notify",
      payload: { message: "✓ In cart" },
    });

    win.externalBus!({ id: 7, type: "command", command: "bar_code/aborted", payload: { reason: "canceled" } });
    expect(closed).toEqual(["canceled"]);
    expect(win.externalBus).toBe(original);
    expect(scanner.open).toBe(false);
    expect(handled).toHaveLength(4);
  });

  it("close() tells the app and restores", () => {
    const { win, bus } = setup();
    const original = win.externalBus;
    const scanner = new NativeScanner(bus, win);
    scanner.start({ title: "t", description: "d", onCode: () => {}, onClose: () => {} });
    scanner.close();
    expect(bus.fireMessage).toHaveBeenLastCalledWith({ type: "bar_code/close" });
    expect(win.externalBus).toBe(original);
    scanner.notify("ignored when closed");
    expect(bus.fireMessage).toHaveBeenCalledTimes(2);
  });

  it("a broken callback never breaks HA's handling", () => {
    const { win, bus, handled } = setup();
    const scanner = new NativeScanner(bus, win);
    scanner.start({
      title: "t",
      description: "d",
      onCode: () => {
        throw new Error("boom");
      },
      onClose: () => {},
    });
    expect(win.externalBus!("{not json")).toBe(true);
    win.externalBus!({ type: "command", command: "bar_code/scan_result", payload: { rawValue: "1" } });
    expect(handled).toHaveLength(2);
  });
});
