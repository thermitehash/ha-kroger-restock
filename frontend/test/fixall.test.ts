import { beforeEach, describe, expect, it, vi } from "vitest";
import "../src/index";
import type { KrogerRestockCard, RecentItem } from "../src/card";

const SENSOR = "sensor.kroger_restock_recently_scanned";

function fixItem(id: string, name: string, candidates = 3): RecentItem {
  return {
    item_id: id,
    name,
    quantity: 1,
    status: "needs_review",
    status_text: "Needs review",
    candidates: Array.from({ length: candidates }, (_, i) => ({
      product_id: `${id}-p${i}`,
      name: `${name} option ${i}`,
      price: 1.99,
      aisle: "Aisle 3",
      image_url: null,
    })),
  };
}

function makeHass(needsFix: RecentItem[], responses: Record<string, unknown> = {}) {
  const sent: any[] = [];
  const hass: any = {
    states: {
      [SENSOR]: {
        state: "x",
        attributes: {
          items: [],
          needs_fix: needsFix,
          needs_fix_count: needsFix.length,
          config_entry_id: "entry1",
          todo_entity_id: "todo.kroger_restock",
        },
      },
    },
    auth: {},
    connection: {
      sendMessagePromise: vi.fn(async (msg: any) => {
        sent.push(msg);
        return { response: responses[msg.service] ?? {} };
      }),
    },
  };
  return { hass, sent };
}

async function mount(hass: any): Promise<KrogerRestockCard> {
  const card = document.createElement("kroger-restock-card") as KrogerRestockCard;
  card.setConfig({ type: "custom:kroger-restock-card", entity: SENSOR });
  card.hass = hass;
  document.body.appendChild(card);
  await card.updateComplete;
  return card;
}

const fixButton = (card: KrogerRestockCard) =>
  card.shadowRoot!.querySelector("button.fixall") as HTMLButtonElement;
const dialog = () => document.querySelector("kroger-restock-fix") as any;
const inDialog = (sel: string) => dialog()?.shadowRoot.querySelector(sel) as HTMLElement | null;

function clearBody(): void {
  while (document.body.firstChild) document.body.firstChild.remove();
}

beforeEach(clearBody);

describe("Fix button", () => {
  it("shows how many items need a fix", async () => {
    const card = await mount(makeHass([fixItem("a", "milk"), fixItem("b", "bread")]).hass);
    const button = fixButton(card);
    expect(button.disabled).toBe(false);
    expect(button.querySelector(".badge")?.textContent).toBe("2");
    expect(button.getAttribute("aria-label")).toBe("Fix 2 items that need a product picked");
  });

  it("is greyed out with no count when nothing needs fixing", async () => {
    const card = await mount(makeHass([]).hass);
    const button = fixButton(card);
    expect(button.disabled).toBe(true);
    expect(button.querySelector(".badge")).toBeNull();
    expect(button.getAttribute("title")).toBe("Nothing needs fixing");
    button.click();
    expect(dialog()).toBeNull();
  });

  it("caps the badge at 99+", async () => {
    const many = Array.from({ length: 120 }, (_, i) => fixItem(String(i), `thing ${i}`, 0));
    const card = await mount(makeHass(many).hass);
    expect(fixButton(card).querySelector(".badge")?.textContent).toBe("99+");
  });

  it("walks every item: pick, skip, then the last one has no Skip", async () => {
    const { hass, sent } = makeHass(
      [fixItem("a", "milk"), fixItem("b", "bread"), fixItem("c", "eggs")],
      { resolve_item: { result: "in_cart", name: "milk option 1", pushed: true } },
    );
    const card = await mount(hass);
    fixButton(card).click();
    await dialog().updateComplete;
    expect(inDialog(".for")?.textContent).toContain("milk");
    expect(inDialog(".progress")?.textContent).toBe("1 of 3");
    expect(inDialog("button.skip")).not.toBeNull();

    (dialog().shadowRoot.querySelectorAll("button.match")[1] as HTMLElement).click();
    await vi.waitFor(() => expect(inDialog(".progress")?.textContent).toBe("2 of 3"));
    expect(sent[0]).toMatchObject({ service: "resolve_item", service_data: { item_id: "a", product_id: "a-p1" } });
    expect(inDialog(".for")?.textContent).toContain("bread");

    inDialog("button.skip")!.click();
    await dialog().updateComplete;
    expect(inDialog(".progress")?.textContent).toBe("3 of 3");
    expect(inDialog(".for")?.textContent).toContain("eggs");
    expect(inDialog("button.skip")).toBeNull();
    expect(inDialog("button.cancel")?.textContent).toBe("Done");
    expect(sent).toHaveLength(1); // skipping changes nothing
  });

  it("Done stops the walk", async () => {
    const card = await mount(makeHass([fixItem("a", "milk"), fixItem("b", "bread")]).hass);
    fixButton(card).click();
    await dialog().updateComplete;
    inDialog("button.cancel")!.click();
    expect(dialog()).toBeNull();
  });

  it("skips items fixed elsewhere in the meantime", async () => {
    const { hass } = makeHass([fixItem("a", "milk"), fixItem("b", "bread"), fixItem("c", "eggs")]);
    const card = await mount(hass);
    fixButton(card).click();
    await dialog().updateComplete;
    // "bread" gets fixed on another device while "milk" is open.
    hass.states[SENSOR] = {
      ...hass.states[SENSOR],
      attributes: { ...hass.states[SENSOR].attributes, needs_fix: [fixItem("a", "milk"), fixItem("c", "eggs")] },
    };
    card.hass = { ...hass };
    await card.updateComplete;
    inDialog("button.skip")!.click();
    await dialog().updateComplete;
    expect(inDialog(".for")?.textContent).toContain("eggs");
    expect(inDialog(".progress")?.textContent).toBe("3 of 3");
  });

  it("a single item shows no progress or Skip", async () => {
    const card = await mount(makeHass([fixItem("a", "milk")]).hass);
    fixButton(card).click();
    await dialog().updateComplete;
    expect(inDialog(".progress")).toBeNull();
    expect(inDialog("button.skip")).toBeNull();
  });
});
