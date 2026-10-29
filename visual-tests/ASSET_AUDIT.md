# V3 asset audit

Audited the supplied `asset-manifest.json`, `CONTACT_SHEET.jpg`, target reference,
and individual WebP assets. No image files were regenerated or retouched. This
report distinguishes a file loading successfully from its visual quality.

## Loading and server preservation

- All **158 PNG/WebP files** now in `assets/` decode successfully and respond from
  the actual FastAPI static mount with HTTP 200 and an `image/*` MIME type.
- The supplied archive contains **79 named images**, each in PNG and WebP form.
- `main.py` SHA-256 remains
  `9a1f07bb7805099474e293ea20f52da836f4b2c587caec5888920993b2a5e493`.
- No production/PostgreSQL data, backend routes, prices, or economic rules were
  changed by this audit.

## Source-art defects

PNG and WebP variants share the same crop/mask defects; changing extensions does
not repair them. Source replacements should contain only the named object with a
clean alpha channel and no adjacent objects or labels.

| Asset(s) | Observed defect | Recommended handling |
| --- | --- | --- |
| `objects/gift_big`, `objects/gift_small` | Segmented/partially missing gift and ribbon; the large present is missing most of its top. | Replace before using as a large promo image; a small existing navigation/decorative icon can stand in. |
| `objects/wood_crate`, `wood_box_small`, `wood_box_large`, `hay_bundle` | Portions of objects are missing after masking. | Avoid these crops; use the complete storage building for storage UI. |
| `objects/chicken_icon`, `chick_icon`, `grain_icon`, `egg_icon`, `gem_blue_icon` | Some include adjacent sprites and/or fragments of printed captions; several are cut off. | Use `characters/white_hen_right`, `characters/chicks_pair`, `objects/grain_wheat`, `objects/egg_single`, and `currency/blue_diamond` respectively, with the latter's mask caveat below. |
| `currency/wallet_coins_icon` | Cut coin with printed label below. | Use `currency/gold_coin_star` or `gold_coins_stack`. |
| `ui/trophy` | Cup cropped at left; neighboring gift/ribbon stroke at right. | Avoid prominent use; replacement needed for a standalone trophy. |
| `ui/alert` | Neighboring narrow orange stroke at right. | Avoid or clip to the main object. |
| `currency/blue_diamond`, `blue_crystals` | Opaque/mask bands or patch around crystals; neither alternate is clean. | Keep small as decoration; replace for high fidelity. |
| `characters/white_hen_left`, `white_hen_right`, `chicks_pair`, `farmer_avatar` | Rough alpha edges and horizontal transparency bands. | Usable at small UI sizes; clean re-export needed for enlargement. |
| `buildings/storage_barn`, `incubator` | Neighboring coin sliver on right plus mask bands. | Render modestly; clean re-export needed for enlarged standalone art. |
| `objects/eggs_and_sacks` | Crop shows eggs without the complete named sacks. | Use egg sprites and a separate complete sack asset. |
| `ui/nav_*` | Files include the original painted labels at the bottom and sometimes a neighboring tile edge. | Show only the icon in a clipped wrapper; render a real HTML label beside/below it. Never use the full tile as a control. |
| `ui/button_*` | Original painted text/button artwork. | Retain supplied files, but use real styled HTML buttons instead. |

## Fidelity limits

The supplied scenes are small landscape crops (for example the farm scene is
300×200), while the approved phone reference shows a taller, more detailed farm.
Cover scaling cannot recover absent pixels or scene detail. The interface can
match color, density, layout, DOM controls and icon placement, but the source pack
needs higher-resolution clean exports for an exact illustration match. Some
backgrounds contain neighboring illustration fragments; no complete screen,
atlas, baked balance, price, or button is used as the application UI.
