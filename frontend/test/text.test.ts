import { describe, expect, it } from "vitest";
import { classifyInput, quantityLine, relativeTime, resultLine } from "../src/text";

describe("resultLine", () => {
  it("in cart with size and aisle", () => {
    expect(
      resultLine({ result: "in_cart", name: "Creamy Ranch", size: "16 fl oz", aisle: "Aisle 14", pushed: true }),
    ).toEqual({ text: "✓ In cart: Creamy Ranch 16 fl oz · Aisle 14", tone: "success" });
  });
  it("push pending and recorded", () => {
    expect(resultLine({ result: "in_cart", name: "A", pushed: false }).tone).toBe("warning");
    expect(resultLine({ result: "in_cart", name: "A", already_in_cart: true }).text).toBe(
      "✓ In cart (recorded): A",
    );
  });
  it("other results", () => {
    expect(resultLine({ result: "waiting", name: "Eggs" }).text).toBe("⏳ Waiting on stock: Eggs");
    expect(resultLine({ result: "unmatched", upc: "0123" }).text).toContain("Unknown code 0123");
    expect(resultLine({ result: "needs_review", name: "milk" }).text).toBe("• Needs review: milk");
    expect(resultLine({ result: "duplicate", name: "A", quantity: 3 }).text).toBe(
      "↺ Already on list (qty 3): A",
    );
    expect(resultLine({ result: "duplicate", debounced: true }).text).toBe("Already scanned");
    expect(resultLine({ result: "ignored", message: "Ignored a QR code" })).toEqual({
      text: "⊘ Ignored a QR code",
      tone: "warning",
    });
  });
});

describe("quantityLine", () => {
  it("warning wins", () => {
    expect(quantityLine({ warning: "Remove 1 from the Kroger app cart: A." }).text).toBe(
      "⚠ Remove 1 from the Kroger app cart: A.",
    );
    expect(quantityLine({ result: "removed", name: "A" }).text).toBe("Removed: A");
    expect(quantityLine({ result: "updated", name: "A", quantity: 2 }).text).toBe("A: ×2");
  });
});

describe("classifyInput", () => {
  it("links, barcodes, names", () => {
    expect(classifyInput("  ")).toBeNull();
    expect(classifyInput("look https://www.kroger.com/p/x/0001111041700")?.kind).toBe("url");
    expect(classifyInput("0 49000 02891 1")).toEqual({ kind: "upc", value: "049000028911" });
    expect(classifyInput("4011")).toEqual({ kind: "upc", value: "4011" });
    expect(classifyInput("peanut butter")).toEqual({ kind: "name", value: "peanut butter" });
    expect(classifyInput("2% milk")?.kind).toBe("name");
  });
});

describe("relativeTime", () => {
  const now = Date.parse("2026-11-27T12:00:00Z");
  it("formats", () => {
    expect(relativeTime("2026-11-27T11:59:50Z", now)).toBe("just now");
    expect(relativeTime("2026-11-27T11:55:00Z", now)).toBe("5 min ago");
    expect(relativeTime("2026-11-27T09:00:00Z", now)).toBe("3 h ago");
    expect(relativeTime("2026-11-25T12:00:00Z", now)).toBe("2 d ago");
    expect(relativeTime(undefined, now)).toBe("");
    expect(relativeTime("garbage", now)).toBe("");
  });
});
