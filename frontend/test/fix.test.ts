import { beforeEach, describe, expect, it, vi } from "vitest";
import "../src/fix-dialog";
import { money, type RestockFixDialog } from "../src/fix-dialog";

const candidates = Array.from({ length: 6 }, (_, i) => ({
  product_id: `00011110417${String(i).padStart(2, "0")}`,
  name: `Kroger Milk ${i}`,
  brand: "Kroger",
  size: "1 gal",
  price: 2 + i,
  image_url: i === 0 ? "https://example.com/milk.jpg" : null,
  aisle: "Aisle 12",
  in_stock: i !== 2,
}));

async function open(
  item: Record<string, unknown>,
  responses: Record<string, any> = {},
): Promise<{ dialog: RestockFixDialog; calls: any[]; done: any[] }> {
  const calls: any[] = [];
  const done: any[] = [];
  const dialog = document.createElement("kroger-restock-fix") as RestockFixDialog;
  dialog.item = { item_id: "i1", name: "milk", status: "needs_review", quantity: 1, ...item } as any;
  dialog.callService = vi.fn(async (service: string, data: Record<string, unknown>) => {
    calls.push({ service, data });
    const r = responses[service];
    if (r instanceof Error) throw r;
    return r ?? {};
  });
  dialog.onDone = (response, kind) => done.push({ response, kind });
  document.body.appendChild(dialog);
  await dialog.updateComplete;
  return { dialog, calls, done };
}

const q = (d: RestockFixDialog, sel: string) => d.shadowRoot!.querySelector(sel) as HTMLElement | null;
const qa = (d: RestockFixDialog, sel: string) => [...d.shadowRoot!.querySelectorAll(sel)] as HTMLElement[];

function clearBody(): void {
  while (document.body.firstChild) document.body.firstChild.remove();
}

beforeEach(clearBody);

describe("Fix pop-up", () => {
  it("shows up to 5 matches with size, price, aisle and stock", async () => {
    const { dialog } = await open({ candidates, quantity: 2 });
    const rows = qa(dialog, "button.match");
    expect(rows).toHaveLength(5);
    expect(rows[0].textContent).toContain("Kroger Milk 0");
    expect(rows[0].textContent).toContain("1 gal");
    expect(rows[0].textContent).toContain("$2.00 · Aisle 12");
    expect(rows[0].querySelector("img")?.getAttribute("src")).toBe("https://example.com/milk.jpg");
    expect(rows[2].querySelector(".oos")?.textContent).toBe("Out of stock");
    expect(q(dialog, ".for")?.textContent).toContain("“milk” ×2");
    expect((q(dialog, "input") as HTMLInputElement).value).toBe("milk");
  });

  it("picking resolves the item and closes", async () => {
    const resolved = { result: "in_cart", name: "Kroger Milk 3", aisle: "Aisle 12", pushed: true };
    const { dialog, calls, done } = await open({ candidates }, { resolve_item: resolved });
    qa(dialog, "button.match")[3].click();
    await vi.waitFor(() => expect(done).toHaveLength(1));
    expect(calls).toEqual([{ service: "resolve_item", data: { item_id: "i1", product_id: "0001111041703" } }]);
    expect(done[0]).toEqual({ response: resolved, kind: "resolve" });
    expect(document.querySelector("kroger-restock-fix")).toBeNull();
  });

  it("a failed pick stays open with the error", async () => {
    const { dialog, done } = await open({ candidates }, { resolve_item: new Error("Product not found") });
    qa(dialog, "button.match")[0].click();
    await vi.waitFor(() => expect(q(dialog, ".error")?.textContent).toBe("Product not found"));
    expect(done).toHaveLength(0);
    expect(document.querySelector("kroger-restock-fix")).not.toBeNull();
  });

  it("search replaces the matches", async () => {
    const found = [{ product_id: "0001111041600", name: "Whole Milk", size: "1 gal", price: 3.49 }];
    const { dialog, calls } = await open({ candidates }, { search_products: { products: found } });
    const input = q(dialog, "input") as HTMLInputElement;
    input.value = "whole milk";
    input.dispatchEvent(new Event("input"));
    await dialog.updateComplete;
    q(dialog, "form.search")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.waitFor(() => expect(qa(dialog, "button.match")).toHaveLength(1));
    expect(calls[0]).toEqual({ service: "search_products", data: { query: "whole milk", limit: 5 } });
    expect(qa(dialog, "button.match")[0].textContent).toContain("Whole Milk");
  });

  it("unmatched barcodes start with an empty search and explain", async () => {
    const { dialog } = await open({ status: "unmatched", name: "0012345678905", candidates: [] });
    expect((q(dialog, "input") as HTMLInputElement).value).toBe("");
    expect(q(dialog, ".empty")?.textContent).toContain("isn't in the Kroger catalog");
  });

  it("a search with no results says so", async () => {
    const { dialog } = await open({ candidates: [] }, { search_products: { products: [] } });
    q(dialog, "form.search")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.waitFor(() => expect(q(dialog, ".empty")?.textContent).toContain("No products found"));
  });

  it("remove asks first", async () => {
    const { dialog, calls, done } = await open({ candidates }, { set_quantity: { result: "removed", name: "milk" } });
    q(dialog, "button.remove")!.click();
    await dialog.updateComplete;
    expect(calls).toHaveLength(0);
    expect(q(dialog, "button.remove")?.textContent).toContain("Tap again");
    q(dialog, "button.remove")!.click();
    await vi.waitFor(() => expect(done).toHaveLength(1));
    expect(calls[0]).toEqual({ service: "set_quantity", data: { item_id: "i1", quantity: 0 } });
    expect(done[0].kind).toBe("remove");
  });

  it("closes with Cancel, the close button, the backdrop or Escape", async () => {
    for (const how of ["button.cancel", "button.close", ".backdrop", "escape"]) {
      const { dialog } = await open({ candidates });
      if (how === "escape") document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
      else q(dialog, how)!.click();
      expect(document.querySelector("kroger-restock-fix")).toBeNull();
    }
  });

  it("formats money", () => {
    expect(money(2.5)).toBe("$2.50");
    expect(money(null)).toBe("");
  });
});
