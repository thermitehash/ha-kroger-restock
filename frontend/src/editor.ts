// Visual editor for the Restock scanner card (uses Home Assistant's ha-form).

import { LitElement, html, nothing } from "lit";
import { CARD_TYPE, type CardConfig } from "./card";

const SCHEMA = [
  {
    name: "entity",
    selector: { entity: { domain: "sensor", integration: "kroger_restock" } },
  },
  { name: "title", selector: { text: {} } },
  { name: "rows", selector: { number: { min: 1, max: 25, mode: "box" } } },
  {
    name: "scanner",
    selector: {
      select: {
        mode: "dropdown",
        options: [
          { value: "auto", label: "Automatic (app scanner, else camera)" },
          { value: "app", label: "Home Assistant app scanner only" },
          { value: "camera", label: "Browser camera only" },
          { value: "off", label: "No scan button" },
        ],
      },
    },
  },
  { name: "show_input", selector: { boolean: {} } },
  { name: "show_actions", selector: { boolean: {} } },
  { name: "shortcut", selector: { text: {} } },
];

const LABELS: Record<string, string> = {
  entity: "Recently scanned sensor",
  title: "Title (optional)",
  rows: "Items to show",
  scanner: "Scan button",
  show_input: "Show the text field (barcode, name or link)",
  show_actions: "Show − / + / undo buttons",
  shortcut: "iPhone Shortcut to run (optional, name)",
};

const HELPERS: Record<string, string> = {
  shortcut: "Adds a button that runs this Shortcut, e.g. Grocery scan. Leave empty for none.",
};

export class KrogerRestockCardEditor extends LitElement {
  static properties = { hass: { attribute: false }, _config: { state: true } };

  hass: any;
  _config?: CardConfig;

  setConfig(config: CardConfig): void {
    this._config = config;
  }

  render() {
    if (!this.hass || !this._config) return nothing;
    const data = { rows: 10, scanner: "auto", show_input: true, show_actions: true, ...this._config };
    return html`<ha-form
      .hass=${this.hass}
      .data=${data}
      .schema=${SCHEMA}
      .computeLabel=${(s: { name: string }) => LABELS[s.name] ?? s.name}
      .computeHelper=${(s: { name: string }) => HELPERS[s.name]}
      @value-changed=${this.changed}
    ></ha-form>`;
  }

  private changed(ev: CustomEvent): void {
    ev.stopPropagation();
    const config = { ...ev.detail.value, type: `custom:${CARD_TYPE}` };
    for (const key of ["title", "shortcut"]) if (!config[key]) delete config[key];
    this.dispatchEvent(
      new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }),
    );
  }
}
