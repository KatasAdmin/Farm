# Monetag reward audit — 2026-11-04

Branch: `fix/monetag-reward-audit-20261104`. Production must remain on main until
CI, private Monetag configuration review and manual end-to-end verification pass.
No passwords or real postback secrets belong in this document, GitHub, client JS or URLs shared in chat.

## Confirmed defects in the previous integration

* Popup sub_zone_id was required to equal main zone 12193261. Official popup
  documentation permits a linked popup sub-zone. Main zone remains validated.
* Popup request_var is prefixed with main zone; the old exact placement check rejected it.
* The SDK call lacked `type: 'pop'` and followed an awaited preparation request,
  losing the original popup user gesture.
* SDK completions/errors, unpaid events, bounded confirmation history and platform
  attribution were not persisted. Late postbacks did not automatically deliver grants.

Railway HTTP log sample on audit day contained 29 postback requests: 22 HTTP 200,
6 HTTP 400 and 1 HTTP 422. This supports rejected callbacks, not proof of a paid
impression or an explanation of the publisher dashboard's zero. Dashboard ownership,
zone enablement, traffic eligibility and actual event parameters required private
Monetag inspection. See the verified follow-up below. A successful Promise or HTTP 200 is never counted as revenue.

## Reward policy and limits

| Item | Valued event postbacks | Goods per completed threshold |
|---|---:|---:|
| Grain | 1 | 1 |
| Eggs | 2 | 2 |
| Milk | 5 | 1 |
| Chicken | 20 | 1 |
| Goose | 80 | 1 |
| Cow | 250 | 1 |
| Purchasing credit | 1 | 2 coins (nonwithdrawable) |

SDK reports are telemetry only, including a forged `valued` result. Only a secret-
authenticated `valued` event tied to a random server-issued account/placement/
zone token credits progress. A duplicate or non_valued event never does. Official popup docs allow one credit
per ymid for any valued event_type, including a valued click from a linked zone.
The official docs recommend postbacks for reward/accounting integrity; there is
no safe way for this server to authenticate a browser Promise on its own.

Each account shares progress between verified Telegram identity and web login.
40 starts/UTC day, 10 starts/rolling hour and 30 seconds cooldown are enforced
under the existing shared transaction lock. Reservations expire in ten minutes;
unused reservations are not starts. At most 60 reservations/hour. Paid reward
credit is independently capped by original reservation day/hour, including late
postbacks. Postbacks may arrive for 48 hours (provider retries can last about 38h).
After two minutes an unconfirmed attempt becomes finite history, not an endless
spinner. A legitimate late callback can still credit it. Unconfirmed attempts and
unpaid impressions do not earn goods.

Threshold grants and claims are transactional and persistent. Warehouse capacity
includes grain, eggs, feathers and milk; bird capacity includes chickens and geese.
A full building defers the grant, never discards it. Production catches up before
an advertising hen is added, avoiding retroactive eggs. Reload/status automatically
delivers eligible grants once there is room. No earned or real-money balance, XP, referral or organic-production activity is
awarded by ad delivery. The explicit credit option adds only restricted bonus
coins with source and emission accounting.

### Advertising provenance (follow-up authorized 2026-11-05)

The original inventory provenance gap has been addressed for newly delivered ad
rewards: a server-side subset counter tags inventory, animals and their production.
Tags survive listings, partial purchases, returns, incubation and feed use. Ordinary
quantities, prices, timing and market allocation are unchanged. Integer production
classification carries fractional debt across polling, rounds toward restriction
and cannot create a new unrestricted fraction by refreshing. Partial ad funding of
an indivisible animal tags the whole animal; any ad funding in a promo package or
incubation tags that indivisible result. Restricted stock is spent first.

Sales of tagged goods become purchasing credit, including an earned-funded buyer's
payment. A separate receipt ledger tracks this advertising subset of bonus money;
subsequent animal/grain purchases and automatic feed buys inherit the tag. Ad-only
production/acquisition does not generate untagged referral resource commissions.
Existing earned balances and ordinary inventory are not retroactively reclassified.
No per-coin hash is needed: transactional quantities and source amounts conserve
both total goods and money. Historical claimed ad rewards cannot safely be
retagged without original provenance; the inspected real callbacks were all unpaid.

Current release gates: green PostgreSQL CI for these new paths, staging/manual
paid event verification and publisher traffic classification review.

## Private publisher configuration required

1. Log in yourself at https://publishers.monetag.com/ in the shared safe browser.
   Verify App 3563430 belongs to Farmlife2026bot and its SDK main zone is 12193261.
2. Enable reward postbacks, including valued and non_valued impression events.
   Use this URL template in the private publisher form (not in the game client):

   `https://farm-web-production-cfb9.up.railway.app/api/ads/monetag/postback?secret=PRIVATE_RAILWAY_VALUE&ymid={ymid}&zone_id={zone_id}&sub_zone_id={sub_zone_id}&event_type={event_type}&reward_event_type={reward_event_type}&request_var={request_var}&telegram_id={telegram_id}&estimated_price={estimated_price}`

   Confirm exact supported macros and event filters against the actual publisher
   form before saving. The application accepts impression/click, valued/non_valued.
   Request placement is `grain_reward`, `eggs_reward`, `milk_reward`, `chickens_reward`;
   popup main-zone prefixes are normalized server-side.
3. Railway Variables only: `MONETAG_POSTBACK_SECRET` random >=24 characters and
   `MONETAG_REWARDS_ENABLED=1`. Rotate any earlier secret which may have appeared
   in access URLs. Application middleware removes the secret from Uvicorn request
   query logging; edge/proxy logging must also omit query strings. Never expose it
   to SDK or frontend. Global pause blocks new prepares, preserves owed grants.
4. Browser: create a separate **website** property for the production HTTPS origin.
   Ask Monetag which incentivized/rewarded format is approved for ordinary web and
   whether it supports this SDK's `type:'pop'`, ymid and authenticated reward
   postbacks. Do not paste a generic on-click zone into a rewarded integration.
   Only if explicitly compatible, set its distinct `MONETAG_WEB_ZONE_ID` and
   `MONETAG_WEB_REWARDED_ENABLED=1` in Railway. Otherwise keep disabled and implement
   the provider-approved web SDK separately. Never fall back to the TMA zone.
5. Ad destination selection (websites/app installs vs Telegram) belongs to Monetag
   inventory/targeting, not link rewriting. Confirm those settings with support.
6. Estimated postback prices are summed once per impression token and labelled as
   estimates. Settled revenue is `null`, not a fabricated zero or calculated CPM.
   Actual financial reporting remains in the publisher dashboard until an official
   authorized reporting integration is verified. Statistics may refresh hourly.

## Verification before production publication

Automated: API auth/ownership; wrong secret/zone/placement/account; popup subzone
and placement prefix; retry/click/multiple-subzone dedupe; missing SDK event data;
non-valued and delayed valued event; shared-platform progress; all thresholds;
capacity and deferred delivery; rollback; quotas; real PostgreSQL concurrent
callbacks/claims and non-destructive schema upgrade; mock SDK synchronous gesture,
progress, failure, unconfigured zone and dynamic shop buttons. No real advertising
impressions are generated in automation.

Manual release gates:

* Review publisher settings above, compare actual callbacks with accepted schema.
* Review and test the advertising provenance changes above. Existing players'
  ordinary inventory and earned money must remain unchanged.
* Run CI with isolated PostgreSQL. Never point TEST_DATABASE_URL at Railway.
* On a staging deployment, use your own consenting test account, mobile Telegram
  Mini App and normal browser. Verify supported formats, progress after reload,
  one threshold award, delayed postback, full warehouse and anti-repeat behavior.
* Check actual publisher stats after the documented reporting delay and compare
  valued callbacks. No automated production ad clicks or fabricated paid events.
* Review and approve the PR, then publish. This branch alone must not redeploy main.

## Official references

* https://docs.monetag.com/docs/ad-integration/rewarded-popup/
* https://docs.monetag.com/docs/postbacks/configuration/
* https://docs.monetag.com/docs/postbacks/macroses/
* https://docs.monetag.com/docs/postbacks/

## Verified publisher follow-up — 2026-11-05 (Kyiv)

Safe user login succeeded. Actual cabinet confirms Farmlife2026bot / App 3563430,
popup SDK zone 12193261, and postback endpoint with all nine expected parameters,
including estimated_price. Secret presence/length were checked without logging it.
The dashboard showed zero impressions/profit for the selected date range.

Latest available runtime logs contained 34 postback requests: one unresolved-macro
422, and **33 non_valued events** (27 HTTP 200, six HTTP 400); no valued event was
observed. Placement counts: grain 20, eggs 8, chickens 5. This directly explains
why these particular callbacks provided no paid credit. Provider documentation
includes fraud/fallback under non_valued; logs do not reveal the exact classifier
reason. Do not claim the user committed fraud. Changing phones is not evidence
that integration is fixed or a way to evade traffic filtering. No self-click ad
traffic was generated during this audit.

There were no website properties. Added only the actual Farm production hostname
as website **3563620**, pending ownership verification; no web ad zone activated.
The cabinet supports verification-file or HTML-tag methods. Browser download did
not yield a file and the copy-code clipboard API did not yield usable content;
verification is not complete. Do not create duplicate sites or pretend verified.
No production application code or Railway variables have been changed.

### Support inquiry prepared (not sent)

Please review App 3563430, SDK zone 12193261 (Farmlife2026bot). All 33 received
real postbacks in our available logs on Nov 4–5 were reward_event_type=non_valued;
the publisher dashboard reports zero impressions and profit. The postback URL is
configured with ymid, zone_id, sub_zone_id, event_type, reward_event_type,
estimated_price, request_var and telegram_id. Please explain whether these are
fallback, traffic-quality filtering, zone restrictions or another classification,
and confirm whether the zone is enabled for paid traffic. We will not generate
self-click traffic for testing. Please also confirm an approved rewarded format
and SDK/postback configuration for our ordinary web version (website 3563620).
No secret URL, user IDs or private credentials are included in this inquiry.

## Follow-up: ranking and expanded rewards — 2026-11-05

Seven newer callbacks at 00:44–00:46 Kyiv were again non_valued, HTTP 200.
A visible advertiser countdown is not payment confirmation. Support conversation
was sent with explicit user permission; it remains waiting for a teammate.

Leaderboard now shows five players by the same main farmer_level as the profile,
with exact own ordinal place even outside top five. Ties use name then immutable
id consistently. The separate animal-weighted farm_score has been removed from
ranking. Rankings are generated after the current player's main-level update.

Direct ad rewards now include goose (80 paid events, 160 coins shop value) and cow
(250, 500 coins). Grain is 1 unit (2 coins) per new paid event; previously owed
2-grain grants retain their recorded quantity. Eggs remain 2 per 2 events (1
coin/event), milk 1 per 5 (2.2), chicken 1 per 20 (2). No feather ad reward.
The universal purchasing-credit option gives 2 restricted coins per paid event,
allowing all existing purchases, bundles, incubator and upgrades through ordinary
purchase handlers, with unchanged prices/capacities/level gates. The advertising
source tag follows this credit. Emission totals include it; earned/real-money
balances do not increase. These are game values, not provider ad revenue.
Daily/hourly account limits remain shared across every reward type.
