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
zone enablement, traffic eligibility and actual event parameters require private
Monetag inspection. A successful Promise or HTTP 200 is never counted as revenue.

## Reward policy and limits

| Item | Valued impression postbacks | Goods per completed threshold |
|---|---:|---:|
| Grain | 1 | 2 |
| Eggs | 2 | 2 |
| Milk | 5 | 1 |
| Chicken | 20 | 1 |

SDK reports are telemetry only, including a forged `valued` result. Only a secret-
authenticated `valued` impression tied to a random server-issued account/placement/
zone token credits progress. A click, duplicate or non_valued event never does.
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
delivers eligible grants once there is room. No coin, real-money, XP, referral or
organic-production activity is awarded by the ad delivery itself.

### Economy boundary / release gate

Normal market, feeding, production, referrals and withdrawal formulas are unchanged.
Existing system buybacks for grain/birds are nonwithdrawable purchasing credit;
existing player-market receipts inherit the buyer's bonus/purchased/earned source.
**The current game does not track the provenance of individual inventory units.**
Therefore advertising eggs/milk sold to a buyer paying earned coins can currently
produce an earned seller receipt; ad hens' subsequent production is also ordinary
production. This is a pre-existing inventory provenance gap, not solved by an ad
callback signature. If the requirement forbids even such indirect conversion,
**do not enable/release these rewards** until ad inventory/listing/production
provenance is designed and tested. Do not claim that “no direct coin write” proves
full economic isolation. Expanding provenance changes market/animal mechanisms and
must be reconciled with the requested prohibition on changing them.

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
* Resolve the economy provenance boundary above without reclassifying existing
  players' legitimately earned money.
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
