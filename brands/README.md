# Brand images

`custom_integrations/kroger_restock/` holds the files for a pull request to
[home-assistant/brands](https://github.com/home-assistant/brands) under
`custom_integrations/kroger_restock/` (`icon.png` 256×256, `icon@2x.png` 512×512).

`transparent/` is the alternative: a white cart on a transparent background
with a green outline, in case the brands reviewers ask for a transparent icon.

Home Assistant 2026.x also serves brand images straight from a custom
integration's `brand/` folder, so the same icons ship in
`custom_components/kroger_restock/brand/`.

Sources are in `assets/`. Re-render with `node script/render_icons.js`.
