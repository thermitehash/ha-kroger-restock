// Entry point: registers the card, its editor and the card-picker entry.
// Loaded on every dashboard by the integration (no resource to add).

import { CARD_TYPE, KrogerRestockCard } from "./card";
import { KrogerRestockCardEditor } from "./editor";

if (!customElements.get(CARD_TYPE)) customElements.define(CARD_TYPE, KrogerRestockCard);
if (!customElements.get(`${CARD_TYPE}-editor`)) {
  customElements.define(`${CARD_TYPE}-editor`, KrogerRestockCardEditor);
}

const w = window as any;
w.customCards = w.customCards || [];
if (!w.customCards.some((c: { type: string }) => c.type === CARD_TYPE)) {
  w.customCards.push({
    type: CARD_TYPE,
    name: "Restock scanner",
    description: "Scan or type groceries onto the Kroger Restock list and fix recent additions.",
    preview: true,
    documentationURL: "https://github.com/thrivestorm2/ha-kroger-restock#restock-scanner-card",
  });
}
