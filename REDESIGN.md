# Sapphire farm redesign

Five new independently generated, full-resolution wide scenes are integrated into
real game screens. No screenshot fragments or external image URLs are used.

Scenes in `assets/redesign/`: `coop.webp`, `market.webp`, `shop.webp`, `wallet.webp`,
`profile.webp` (1536×1024). Scene composition is preserved at mobile widths.

Sixteen new transparent sprites, each supplied separately in PNG and WebP:
`hen`, `egg`, `grain`, `coin`, `crystal`, `farmer`, `shop-icon`, `coop-icon`,
`storage`, `wallet-icon`, `incubator`, `statistics`, `achievement`, `settings`,
`upgrade`, `gift`. Dimensions and file sizes: `assets/redesign/manifest.json`.
Sprites were extracted from an original generated transparent asset sheet;
no captions, UI frames, or balances are baked into the artwork.

The existing HTML controls, API data bindings, authentication and economy remain.
`assets/game.js` changes only image paths. `main.py`, prices, daily production,
database schema and production dependencies are unchanged. No Railway operations
or production database connections were performed. Payment buttons remain disabled.
Levels, capacity and real-currency exchange are explicitly described as unsupported.
The decorative fake progress in the player header was replaced with a neutral bar.

## Verification (2026-10-29)

- 7 existing API/economy regression tests PASS using a separate local PostgreSQL 15
  instance on 127.0.0.1:5543. No database resets or deletions.
- Chromium: real registration, session persistence, grain/hen purchases, market
  reserve/cancel and proportional pool purchase, daily feeding and autobuy PASS.
- 40 layout checks on 320/375/390/430 px PASS, including bottom navigation clearance.
- 195 local PNG/WebP images: HTTP 200, correct content type and browser decode PASS.
- No JavaScript or image errors. Economy total remains 10,000 coins.
- JavaScript syntax and git whitespace checks PASS.
- Actual screenshots and browser report: `visual-tests/sapphire/`.

Run commands are documented in `visual-tests/browser_qa.py`,
`visual-tests/test_regression.py` and `visual-tests/check_assets.py`.
Starlette emits one existing AnyIO deprecation warning during pytest.

## Fidelity limits

The requested reference attachment was not available in this conversation or the
checkout. This is an implementation of the written visual specification, not a
verified 95–100% match. Generated illustrations are original interpretations.
Chromium mobile viewports were checked; a physical iPhone / Safari was not available.
The original art pack remains for secondary screens and some ancillary icons.
