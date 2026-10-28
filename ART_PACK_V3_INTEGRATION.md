# V3 game-art integration (staged, not deployed)

This branch prepares the existing UI to read independent **raster** assets from `NOVAYA_ZHIZN_FARM_ART_PACK_V3.zip`. The images themselves are **not yet uploaded to GitHub**. Until they are installed, the farm and coop art use the existing SVG fallback. The wallet treasure artwork is hidden if absent.

## Upload assets preserving exact paths

From the ZIP, copy all contents of `assets/` into the repository's `assets/` directory. For example:

- `assets/backgrounds/farm_sunset.webp` → the home farm illustration
- `assets/backgrounds/chicken_coop_warm.webp` → the coop illustration
- `assets/backgrounds/wallet_treasure.webp` → the treasure/coin chest in the wallet
- `assets/currency/gold_coin.webp` → wallet currency icon

Keep `main.py`, PostgreSQL data, API behavior, prices and balances intact. Make image-only changes on this branch; do not delete existing `assets/farm-scene.svg` and `assets/coop-scene.svg`, since they are fallbacks. Avoid committing `reference/` promotional images to production unless needed.

### Validation after binary upload
1. Confirm each `/assets/...` image responds with HTTP 200 and correct image MIME type.
2. Open farm, coop and wallet on iPhone-size viewport; ensure images show and layout is not clipped.
3. Confirm the old SVGs are **not** displayed after the assets are uploaded.
4. Test account login, grain purchase, auto feeding, marketplace listings, cancellation and ledger.
5. Merge only after visual comparison to the user's target screenshot and successful smoke tests.

**Why this split?** The GitHub connector in this chat can edit UTF-8 source but cannot directly ingest local ZIP/binary files from the chat runtime. Committing paths with fallbacks prevents breaking production while image upload is pending.
