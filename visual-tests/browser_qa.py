"""Real mobile/browser QA for the asset-pack-v3 interface (no mocked APIs).

Start the unchanged server against the LOCAL visual QA database:
  DATABASE_URL=postgresql://farm:farm@127.0.0.1:5543/farm_visual_test \
    .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8085
Then run:
  .venv/bin/python visual-tests/browser_qa.py

Only unique qa_ accounts are created. Production/database URLs are not accepted;
no existing rows are deleted/reset. Only those new players' last_tick is aged to
exercise real daily feeding/egg production. Screenshots contain actual API data.
"""

import json
import time
import uuid
from pathlib import Path

import httpx
import psycopg
from playwright.sync_api import sync_playwright
from psycopg.rows import dict_row

BASE_URL = "http://127.0.0.1:8085"
TEST_DATABASE = "postgresql://farm:farm@127.0.0.1:5543/farm_visual_test"
OUTPUT = Path("/workspace/artifacts/farm-v3")
SCREENS = ("farm", "coop", "market", "shop", "wallet", "profile", "storage", "tasks", "upgrades")


def sql(query, params=()):
    with psycopg.connect(TEST_DATABASE, row_factory=dict_row) as connection:
        return connection.execute(query, params).fetchall()


def api(path, token=None, payload=None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    with httpx.Client(base_url=BASE_URL, timeout=15) as client:
        response = (client.post(path, headers=headers, json=payload) if payload is not None
                    else client.get(path, headers=headers))
    assert response.status_code == 200, (path, response.status_code, response.text)
    return response.json()


def age(token, days):
    account = api("/api/state", token)["me"]
    assert account["name"].startswith("qa_") and 1 <= days <= 3
    changed = sql("UPDATE players SET last_tick=%s WHERE id=%s AND name=%s RETURNING id",
                  (time.time() - days * 86400 - 2, account["id"], account["name"]))
    assert len(changed) == 1
    return api("/api/state", token)


def seed_seller(days, two_hens=False):
    token = api("/api/join", payload={"name": "qa_" + uuid.uuid4().hex[:12]})["token"]
    if two_hens:
        api("/api/shop", token, {"item": "chickens", "amount": 1})
        api("/api/shop", token, {"item": "grain", "amount": 1})
    produced = age(token, days)
    quantity = days * (2 if two_hens else 1)
    assert produced["me"]["eggs"] == quantity
    api("/api/sell", token, {"item": "eggs", "amount": quantity, "price": 5})
    return token, api("/api/state", token)


def ready(page):
    page.wait_for_function("document.readyState === 'complete'")
    page.wait_for_function("!document.body.classList.contains('pending')")
    page.evaluate("document.fonts.ready")
    page.wait_for_function("Array.from(document.images).every(img => img.complete && img.naturalWidth > 0)")
    page.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")


def go(page, screen):
    # Exercise the actual navigation controls wherever present.
    if screen in {"farm", "market", "shop", "wallet", "profile"}:
        page.locator(f'#nav [data-tab="{screen}"]').click()
    elif screen == "coop":
        page.locator('#nav [data-tab="farm"]').click()
        page.locator('#farm .quick[onclick="tab(\'coop\')"]').click()
    elif screen in {"storage", "tasks"}:
        page.locator('#nav [data-tab="farm"]').click()
        page.locator(f'#farm .quick[onclick="tab(\'{screen}\')"]').click()
    else:
        page.locator('#nav [data-tab="profile"]').click()
        page.locator(f'#profile .menu-row[onclick="tab(\'{screen}\')"]').click()
    page.locator(f"#{screen}.active").wait_for()
    ready(page)


def screenshot(page, name):
    ready(page)
    page.wait_for_function("document.getElementById('toast').hidden", timeout=7000)
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=str(OUTPUT / (name + ".png")), full_page=False)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    assert api("/health") == {"ok": True}
    errors, bad_images, layout_checks = [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True,
                                      device_scale_factor=1, reduced_motion="reduce")
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())
        page.on("response", lambda response: bad_images.append({"url": response.url, "status": response.status})
                if "/assets/" in response.url and response.status >= 400 else None)
        page.goto(BASE_URL)
        page.locator("#name").fill("qa_Фермер_" + uuid.uuid4().hex[:4])
        page.locator("#join-form button").click()
        page.locator("#app").wait_for(state="visible")
        ready(page)
        token = page.evaluate("localStorage.getItem('farm_token')")
        original_id = api("/api/state", token)["me"]["id"]
        assert api("/api/state", token)["me"]["coins"] == 100
        page.reload()
        page.locator("#app").wait_for(state="visible")
        assert page.evaluate("localStorage.getItem('farm_token')") == token
        assert api("/api/state", token)["me"]["id"] == original_id

        go(page, "shop")
        page.locator("#shop .shop-catalog .product").filter(has_text="Корм для кур").get_by_role("button", name="Купить", exact=True).click()
        page.locator("#purchase-amount").fill("10")
        assert page.locator("#purchase-total").inner_text() == "20"
        page.locator("#purchase-confirm").click()
        page.wait_for_function("state.me.coins === 80 && state.me.grain === 15")
        ready(page)
        page.locator("#shop .shop-catalog .product").filter(has_text="Производит яйца").get_by_role("button", name="Купить", exact=True).click()
        assert page.locator("#purchase-total").inner_text() == "30"
        page.locator("#purchase-confirm").click()
        page.wait_for_function("state.me.coins === 50 && state.me.chickens === 2")

        # Real stock reservation and cancellation through the market controls.
        go(page, "market")
        page.locator("#msell").click()
        page.locator("#sellitem").select_option("grain")
        page.locator("#sellnum").fill("3")
        page.locator("#sellprice").fill("2")
        page.get_by_role("button", name="Продать в общий пул", exact=True).click()
        page.wait_for_function("state.me.grain === 12 && state.my_listings.length === 1")
        page.locator("#mylist").get_by_role("button", name="Вернуть", exact=True).click()
        page.wait_for_function("state.me.grain === 15 && state.my_listings.length === 0")

        go(page, "shop")
        page.locator("#auto-shop").fill("10")
        toggle = page.locator("#shop .auto-toggle")
        toggle.click()
        page.wait_for_function("state.me.autobuy_enabled === true && state.me.autobuy_amount === 10")
        ready(page)
        toggle.click()
        page.wait_for_function("state.me.autobuy_enabled === false")
        ready(page)
        before_feed = api("/api/state", token)["me"]
        after_feed = age(token, 1)["me"]
        assert after_feed["grain"] == before_feed["grain"] - 2
        assert after_feed["eggs"] == before_feed["eggs"] + 2
        assert after_feed["coins"] == before_feed["coins"]
        page.evaluate("refresh()")
        page.wait_for_function("state.me.grain === 13 && state.me.eggs === 2")
        page.reload()
        page.wait_for_function("state && state.me.grain === 13 && state.me.eggs === 2")

        seller_a, a_before = seed_seller(2)
        seller_b, b_before = seed_seller(3, two_hens=True)
        # This newly provisioned QA database has no other active egg sellers.
        all_eggs = sql("SELECT SUM(quantity) AS amount FROM market WHERE item='eggs' AND quantity>0")
        assert all_eggs[0]["amount"] == 8, "Use a fresh dedicated QA database without other active egg offers"
        page.evaluate("refresh()")
        go(page, "market")
        page.locator("#mbuy").click()
        page.locator("#pool .product").filter(has=page.get_by_role("heading", name="Яйца", exact=True)).get_by_role("button", name="Купить", exact=True).click()
        page.locator("#purchase-amount").fill("4")
        assert page.locator("#purchase-total").inner_text() == "20"
        page.locator("#purchase-confirm").click()
        page.wait_for_function("state.me.coins === 30 && state.me.eggs === 6")
        a_after, b_after = api("/api/state", seller_a), api("/api/state", seller_b)
        assert a_after["me"]["coins"] - a_before["me"]["coins"] == 5
        assert b_after["me"]["coins"] - b_before["me"]["coins"] == 15
        assert a_after["my_listings"][0]["quantity"] == 1
        assert b_after["my_listings"][0]["quantity"] == 3
        emission = sql("SELECT (SELECT treasury FROM economy WHERE id=1) + (SELECT SUM(coins) FROM players) AS coins")[0]["coins"]
        assert emission == 10000

        # Actual screen captures, each exactly 390 x 844 CSS px.
        for screen in SCREENS:
            go(page, screen)
            if screen == "market":
                page.locator("#mbuy").click()
                screenshot(page, "market-buy")
                page.locator("#msell").click()
                screenshot(page, "market-sell")
                page.locator("#mbuy").click()
            else:
                screenshot(page, screen)
        go(page, "shop")
        page.locator("#shop .shop-catalog .product").filter(has_text="Производит яйца").get_by_role("button", name="Купить", exact=True).click()
        screenshot(page, "purchase")
        page.get_by_role("button", name="Отмена", exact=True).click()

        for width in (320, 375, 390, 430):
            page.set_viewport_size({"width": width, "height": 844})
            for screen in SCREENS:
                go(page, screen)
                if screen == "market":
                    for mode in ("buy", "sell"):
                        page.locator("#m" + mode).click()
                        overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                        assert not overflow, (width, screen, mode)
                        layout_checks.append({"width": width, "screen": "market-" + mode, "overflow": False})
                else:
                    assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth"), (width, screen)
                    layout_checks.append({"width": width, "screen": screen, "overflow": False})
                # Last content control can scroll completely above the fixed bottom navigation.
                content_controls = page.locator(f"#{screen} button:visible:not([disabled])")
                if content_controls.count():
                    last = content_controls.last
                    last.scroll_into_view_if_needed()
                    page.evaluate("window.scrollBy(0, 180)")
                    bounds, nav = last.bounding_box(), page.locator("#nav").bounding_box()
                    assert bounds["y"] + bounds["height"] <= nav["y"] + 1, (width, screen, "bottom navigation overlaps last control", bounds, nav)
                ready(page)

        broken = page.evaluate("Array.from(document.images).filter(img => !img.complete || !img.naturalWidth).map(img => img.src)")
        assert not broken, broken
        assert not errors, errors
        assert not bad_images, bad_images
        # Return unsold test reservations through the real API (no deletion/reset).
        for seller, state in ((seller_a, a_after), (seller_b, b_after)):
            api("/api/cancel/" + state["my_listings"][0]["id"], seller, {})
        context.close()
        browser.close()
    report = {"result": "PASS", "browser": "Chromium", "viewport": "390x844", "screenshots": 11,
              "layout_checks": layout_checks, "javascript_errors": errors, "image_errors": bad_images,
              "economy_total": emission, "checks": ["registration", "persisted token/reload", "grain purchase",
              "hen purchase", "listing reserve/cancel", "autobuy on/off", "daily production", "proportional pool buy 1:3",
              "all screen image decoding", "bottom navigation clearance"]}
    (OUTPUT / "browser-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "layout_checks"}, ensure_ascii=False, indent=2))
    print("Layout checks:", len(layout_checks))


if __name__ == "__main__":
    main()
