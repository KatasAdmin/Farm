"""Regression checks against the real, unchanged FastAPI/PostgreSQL server.

Run from the repository root with a separately provisioned LOCAL test database:

    FARM_VISUAL_TEST_DATABASE_URL=postgresql://farm:farm@127.0.0.1:5543/farm_visual_regression_test \
      .venv/bin/python -m pytest -q visual-tests/test_regression.py

The suite creates unique accounts through the public API. It never truncates,
resets, deletes, or migrates existing data. Only generated test accounts have
last_tick advanced to exercise the actual daily production rules. No coins,
eggs, grain or hens are injected directly. The database is intentionally kept
for inspection after the tests.
"""

import os
import time
import uuid
from urllib.parse import urlparse

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row


@pytest.fixture(scope="module")
def client():
    url = os.getenv("FARM_VISUAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set FARM_VISUAL_TEST_DATABASE_URL to the dedicated local test database")
    parsed = urlparse(url)
    assert parsed.hostname in {"localhost", "127.0.0.1"}
    assert parsed.port == 5543, "Only the visual QA PostgreSQL instance is allowed"
    assert parsed.path == "/farm_visual_regression_test", "Refuse to touch any other database"
    original = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    import main

    with TestClient(main.app) as test_client:
        yield test_client
    if original is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = original


def query(sql, params=()):
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        return connection.execute(sql, params).fetchall()


def emission():
    return query("SELECT (SELECT treasury FROM economy WHERE id=1) + "
                 "(SELECT COALESCE(SUM(coins),0) FROM players) AS total")[0]["total"]


def player(client):
    name = "qa_" + uuid.uuid4().hex[:18]
    response = client.post("/api/join", json={"name": name})
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    assert len(token) == 32
    headers = {"Authorization": "Bearer " + token}
    assert get_state(client, headers)["me"]["name"] == name
    return headers


def get_state(client, headers):
    response = client.get("/api/state", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def post(client, headers, route, data):
    response = client.post(route, headers=headers, json=data)
    assert response.status_code == 200, response.text
    return response.json()


def age_generated_player(client, headers, days):
    """Move only this freshly generated player's clock; production remains real."""
    account = get_state(client, headers)["me"]
    assert account["name"].startswith("qa_")
    assert 1 <= days <= 5
    query("UPDATE players SET last_tick=%s WHERE id=%s AND name=%s RETURNING id",
          (time.time() - days * 86400 - 2, account["id"], account["name"]))
    return get_state(client, headers)


def test_registration_auth_and_conserved_starting_fund(client):
    assert emission() == 10000
    treasury_before = query("SELECT treasury FROM economy WHERE id=1")[0]["treasury"]
    headers = player(client)
    state = get_state(client, headers)
    assert (state["me"]["coins"], state["me"]["chickens"], state["me"]["grain"], state["me"]["eggs"]) == (100, 1, 5, 0)
    assert state["economy"]["treasury"] == treasury_before - 100
    assert emission() == 10000
    assert client.get("/api/state").status_code == 401
    assert client.get("/api/finance", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.post("/api/join", json={"name": state["me"]["name"]}).status_code == 409
    assert emission() == 10000


def test_system_purchases_flow_to_treasury_and_ledger(client):
    headers = player(client)
    before = get_state(client, headers)
    post(client, headers, "/api/shop", {"item": "chickens", "amount": 1})
    post(client, headers, "/api/shop", {"item": "grain", "amount": 5})
    after = get_state(client, headers)
    assert after["shop"] == {"grain": 2, "chickens": 30}
    assert after["me"]["coins"] == 60
    assert after["me"]["chickens"] == 2
    assert after["me"]["grain"] == 10
    assert after["economy"]["treasury"] == before["economy"]["treasury"] + 40
    logs = client.get("/api/finance", headers=headers).json()["entries"]
    assert sorted(entry["delta"] for entry in logs if entry["kind"] == "shop") == [-30, -10]
    assert emission() == 10000


def test_daily_feed_is_once_per_day_and_persists(client):
    headers = player(client)
    post(client, headers, "/api/shop", {"item": "chickens", "amount": 1})
    before = get_state(client, headers)
    after = age_generated_player(client, headers, 1)
    assert after["farm"]["cycle_seconds"] == 86400
    assert after["me"]["grain"] == before["me"]["grain"] - 2
    assert after["me"]["eggs"] == before["me"]["eggs"] + 2
    assert after["me"]["coins"] == before["me"]["coins"]
    reloaded = get_state(client, headers)
    assert reloaded["me"]["grain"] == after["me"]["grain"]
    assert reloaded["me"]["eggs"] == after["me"]["eggs"]
    assert client.post("/api/feed", headers=headers).status_code == 410
    assert emission() == 10000


def test_automatic_grain_purchase_uses_real_balance(client):
    headers = player(client)
    post(client, headers, "/api/shop", {"item": "chickens", "amount": 2})
    post(client, headers, "/api/autobuy", {"item": "on", "amount": 10})
    before = get_state(client, headers)
    # Day 1 consumes 3 of the 5 initial grain. Day 2 buys 10 then consumes 3.
    after = age_generated_player(client, headers, 2)
    assert after["me"]["coins"] == before["me"]["coins"] - 20
    assert after["me"]["grain"] == 9
    assert after["me"]["eggs"] == 6
    assert after["economy"]["treasury"] == before["economy"]["treasury"] + 20
    logs = client.get("/api/finance", headers=headers).json()["entries"]
    assert any(entry["kind"] == "auto_grain" and entry["delta"] == -20 for entry in logs)
    post(client, headers, "/api/autobuy", {"item": "off", "amount": 10})
    assert get_state(client, headers)["me"]["autobuy_enabled"] is False
    assert emission() == 10000


def test_proportional_pool_egg_sales_have_no_commission(client):
    seller_a, seller_b, buyer = player(client), player(client), player(client)
    age_generated_player(client, seller_a, 2)
    age_generated_player(client, seller_b, 4)
    post(client, seller_a, "/api/sell", {"item": "eggs", "amount": 2, "price": 1})
    post(client, seller_b, "/api/sell", {"item": "eggs", "amount": 4, "price": 999})
    a_before = get_state(client, seller_a)
    b_before = get_state(client, seller_b)
    assert a_before["my_listings"][0]["price"] == 5
    assert b_before["my_listings"][0]["price"] == 5
    # All prior tests leave no active egg offers. This price group is 2:4.
    assert sum(row["quantity"] for row in a_before["market"] if row["item"] == "eggs") == 6
    result = post(client, buyer, "/api/buy", {"item": "eggs", "amount": 3})
    assert result["spent"] == 15
    a_after, b_after, bought = get_state(client, seller_a), get_state(client, seller_b), get_state(client, buyer)
    assert a_after["my_listings"][0]["quantity"] == 1
    assert b_after["my_listings"][0]["quantity"] == 2
    assert a_after["me"]["coins"] - a_before["me"]["coins"] == 5
    assert b_after["me"]["coins"] - b_before["me"]["coins"] == 10
    assert bought["me"]["coins"] == 85
    assert bought["me"]["eggs"] == 3
    assert bought["economy"]["treasury"] == a_before["economy"]["treasury"]
    for headers, state in ((seller_a, a_after), (seller_b, b_after)):
        post(client, headers, "/api/cancel/" + state["my_listings"][0]["id"], {})
    assert emission() == 10000


def test_listing_reservation_cancel_and_unauthorized_cancel(client):
    seller, outsider = player(client), player(client)
    post(client, seller, "/api/sell", {"item": "grain", "amount": 3, "price": 2})
    reserved = get_state(client, seller)
    listing_id = reserved["my_listings"][0]["id"]
    assert reserved["me"]["grain"] == 2
    assert client.post("/api/cancel/" + listing_id, headers=outsider, json={}).status_code == 404
    post(client, seller, "/api/cancel/" + listing_id, {})
    assert get_state(client, seller)["me"]["grain"] == 5
    assert get_state(client, seller)["my_listings"] == []
    assert client.post("/api/cancel/" + listing_id, headers=seller, json={}).status_code == 404
    assert emission() == 10000


def test_rejected_operations_leave_balance_untouched(client):
    headers = player(client)
    for request in ({"item": "grain", "amount": 0}, {"item": "grain", "amount": -1},
                    {"item": "grain", "amount": 10001}, {"item": "eggs", "amount": 1},
                    {"item": "chickens", "amount": 4}):
        assert client.post("/api/shop", headers=headers, json=request).status_code == 400
    assert client.post("/api/sell", headers=headers, json={"item": "eggs", "amount": 1, "price": 5}).status_code == 400
    assert client.post("/api/bundle", headers=headers, json={}).status_code == 400
    after = get_state(client, headers)
    assert (after["me"]["coins"], after["me"]["grain"], after["me"]["chickens"]) == (100, 5, 1)
    assert emission() == 10000
