import { beforeEach, describe, expect, it, vi } from "vitest";
import "../src/index";
import type { KrogerRestockCard, RecentItem } from "../src/card";
import { findRecentSensor } from "../src/card";

const SENSOR = "sensor.kroger_restock_recently_scanned";

function item(overrides: Partial<RecentItem>): RecentItem {
  return {
    item_id: "a",
    name: "Creamy Ranch",
    size: "16 fl oz",
    quantity: 1,
    status: "in_cart",
    status_text: "In cart · Aisle 14",
    at: new Date().toISOString(),
    result: "in_cart",
    added: 0,
    can_undo: false,
    ...overrides,
  };
}

function makeHass(items: RecentItem[], responses: Record<string, unknown> = {}, external?: unknown) {
  const sent: any[] = [];
  return {
    sent,
    hass: {
      states: {
        [SENSOR]: {
          state: items[0]?.name ?? "unknown",
          attributes: { items, config_entry_id: "entry1", todo_entity_id: "todo.kroger_restock" },
        },
        "sensor.other": { state: "1", attributes: {} },
      },
      auth: external ? { external } : {},
      connection: {
        sendMessagePromise: vi.fn(async (msg: any) => {
          sent.push(msg);
          return { context: {}, response: responses[msg.service] ?? {} };
        }),
      },
    },
  };
}

async function mount(hass: any, config: Record<string, unknown> = {}): Promise<KrogerRestockCard> {
  const card = document.createElement("kroger-restock-card") as KrogerRestockCard;
  card.setConfig({ type: "custom:kroger-restock-card", entity: SENSOR, ...config });
  card.hass = hass;
  document.body.appendChild(card);
  await card.updateComplete;
  return card;
}

const $ = (card: Element, sel: string) => card.shadowRoot!.querySelector(sel) as HTMLElement | null;
const $$ = (card: Element, sel: string) => [...card.shadowRoot!.querySelectorAll(sel)] as HTMLElement[];

beforeEach(() => {
  document.body.innerHTML = "";
  delete (window as any).externalBus;
});

describe("registration", () => {
  it("registers the card, editor and picker entry", () => {
    expect(customElements.get("kroger-restock-card")).toBeDefined();
    expect(customElements.get("kroger-restock-card-editor")).toBeDefined();
    expect((window as any).customCards.some((c: any) => c.type === "kroger-restock-card")).toBe(true);
  });
  it("finds the sensor for the stub config", () => {
    const { hass } = makeHass([]);
    expect(findRecentSensor(hass)).toBe(SENSOR);
  });
});

describe("list", () => {
  it("shows rows newest first with quantity, status and time", async () => {
    const { hass } = makeHass([
      item({ item_id: "a", quantity: 2 }),
      item({ item_id: "b", name: "Large Eggs", size: null, status: "waiting", status_text: "Waiting on stock" }),
    ]);
    const card = await mount(hass);
    const rows = $$(card, "li.row");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("Creamy Ranch (16 fl oz)");
    expect(rows[0].querySelector(".qty")?.textContent).toBe("×2");
    expect(rows[0].textContent).toContain("In cart · Aisle 14 · just now");
    expect(rows[1].querySelector(".qty")).toBeNull();
  });

  it("respects rows and empty / missing sensor states", async () => {
    const many = Array.from({ length: 12 }, (_, i) => item({ item_id: String(i) }));
    let card = await mount(makeHass(many).hass, { rows: 5 });
    expect($$(card, "li.row")).toHaveLength(5);
    card = await mount(makeHass([]).hass);
    expect($(card, ".empty")?.textContent).toContain("Nothing scanned yet");
    card = await mount(makeHass([]).hass, { entity: "sensor.missing" });
    expect($(card, ".empty.warn")).not.toBeNull();
  });
});

describe("row actions", () => {
  it("+ and − call set_quantity", async () => {
    const { hass, sent } = makeHass([item({ quantity: 2 })], {
      set_quantity: { result: "updated", name: "Creamy Ranch", quantity: 3 },
    });
    const card = await mount(hass);
    const [minus, plus] = $$(card, ".actions button.icon");
    plus.click();
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({
      type: "call_service",
      domain: "kroger_restock",
      service: "set_quantity",
      service_data: { item_id: "a", quantity: 3, config_entry_id: "entry1" },
      return_response: true,
    });
    minus.click();
    await vi.waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1].service_data.quantity).toBe(1);
  });

  it("removing at 1 asks first, and shows the cart warning", async () => {
    const { hass, sent } = makeHass([item({ quantity: 1 })], {
      set_quantity: {
        result: "removed",
        name: "Creamy Ranch",
        warning: "Remove 1 from the Kroger app cart: Creamy Ranch.",
      },
    });
    const card = await mount(hass);
    $$(card, ".actions button.icon")[0].click();
    await card.updateComplete;
    expect(sent).toHaveLength(0);
    expect($(card, "button.confirm")?.textContent).toContain("Remove?");
    $(card, "button.confirm")!.click();
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].service_data.quantity).toBe(0);
    await vi.waitFor(() => expect($(card, ".line.warning")?.textContent).toContain("Remove 1 from the Kroger app cart"));
  });

  it("Undo +N lowers by the amount added", async () => {
    const { hass, sent } = makeHass([item({ quantity: 3, added: 2, can_undo: true, result: "duplicate" })]);
    const card = await mount(hass);
    const undo = $$(card, "button.text").find((b) => b.textContent!.includes("Undo"))!;
    expect(undo.textContent).toContain("Undo +2");
    undo.click();
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].service_data).toMatchObject({ item_id: "a", quantity: 1 });
  });

  it("Fix opens the to-do list for items needing review", async () => {
    const { hass } = makeHass([item({ status: "needs_review", status_text: "Needs review" })]);
    const card = await mount(hass);
    const events: string[] = [];
    window.addEventListener("location-changed", () => events.push(location.pathname + location.search));
    $$(card, "button.text").find((b) => b.textContent!.includes("Fix"))!.click();
    expect(events.at(-1)).toBe("/todo?entity_id=todo.kroger_restock");
  });

  it("hides actions when turned off", async () => {
    const card = await mount(makeHass([item({})]).hass, { show_actions: false });
    expect($(card, ".actions")).toBeNull();
  });
});

describe("adding", () => {
  async function submit(card: KrogerRestockCard, text: string) {
    const input = $(card, "input") as HTMLInputElement;
    input.value = text;
    input.dispatchEvent(new Event("input"));
    await card.updateComplete;
    $(card, "form.add")!.dispatchEvent(new Event("submit", { cancelable: true }));
  }

  it("routes barcodes, links and names", async () => {
    const { hass, sent } = makeHass([], {
      scan_upc: { result: "in_cart", name: "Coca-Cola", aisle: "Aisle 7", pushed: true },
      add_item: { result: "needs_review", name: "milk" },
    });
    const card = await mount(hass);
    await submit(card, "049000028911");
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ service: "scan_upc", service_data: { upc: "049000028911", source: "card" } });
    await vi.waitFor(() => expect($(card, ".line.success")?.textContent).toBe("✓ In cart: Coca-Cola · Aisle 7"));
    expect(($(card, "input") as HTMLInputElement).value).toBe("");

    await submit(card, "https://www.kroger.com/p/x/0001111041700");
    await vi.waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1].service_data).toMatchObject({ url: "https://www.kroger.com/p/x/0001111041700" });

    await submit(card, "milk");
    await vi.waitFor(() => expect(sent).toHaveLength(3));
    expect(sent[2]).toMatchObject({ service: "add_item", service_data: { name: "milk", source: "card" } });
  });

  it("shows errors and gives the text back", async () => {
    const { hass } = makeHass([]);
    hass.connection.sendMessagePromise = vi.fn(async () => {
      throw { code: "service_validation_error", message: "Not loaded" };
    });
    const card = await mount(hass);
    await submit(card, "4011");
    await vi.waitFor(() => expect($(card, ".line.error")?.textContent).toBe("Not loaded"));
    expect(($(card, "input") as HTMLInputElement).value).toBe("4011");
  });

  it("hides the text field when turned off", async () => {
    const card = await mount(makeHass([]).hass, { show_input: false });
    expect($(card, "form.add")).toBeNull();
  });
});

describe("scan button", () => {
  it("uses the app's native scanner when available and keeps scanning", async () => {
    const appHandled: unknown[] = [];
    (window as any).externalBus = (m: unknown) => appHandled.push(m);
    const external = { config: { hasBarCodeScanner: 1 }, fireMessage: vi.fn() };
    const { hass, sent } = makeHass([], { scan_upc: { result: "waiting", name: "Large Eggs" } }, external);
    const card = await mount(hass);
    ($(card, "button.scan") as HTMLButtonElement).click();
    expect(external.fireMessage).toHaveBeenCalledWith(expect.objectContaining({ type: "bar_code/scan" }));

    const scan = (code: string) =>
      (window as any).externalBus({
        type: "command",
        command: "bar_code/scan_result",
        payload: { rawValue: code, format: "ean_13" },
      });
    scan("0000000000033");
    scan("0000000000033"); // same code again right away: ignored
    await vi.waitFor(() =>
      expect(external.fireMessage).toHaveBeenLastCalledWith({
        type: "bar_code/notify",
        payload: { message: "⏳ Waiting on stock: Large Eggs" },
      }),
    );
    expect(sent).toHaveLength(1);
    expect(sent[0].service_data).toMatchObject({ upc: "0000000000033", source: "card" });
    expect(appHandled).toHaveLength(2);
    expect(document.querySelector("kroger-restock-camera")).toBeNull();
  });

  it("falls back to the camera, and can be turned off", async () => {
    const card = await mount(makeHass([]).hass);
    ($(card, "button.scan") as HTMLButtonElement).click();
    expect(document.querySelector("kroger-restock-camera")).not.toBeNull();
    const off = await mount(makeHass([]).hass, { scanner: "off" });
    expect($(off, "button.scan")).toBeNull();
    const appOnly = await mount(makeHass([]).hass, { scanner: "app" });
    expect($(appOnly, "button.scan")).toBeNull();
  });

  it("optional Shortcut button", async () => {
    const card = await mount(makeHass([]).hass, { shortcut: "Grocery scan" });
    expect($(card, "a.scan")?.getAttribute("href")).toBe("shortcuts://run-shortcut?name=Grocery%20scan");
  });
});
