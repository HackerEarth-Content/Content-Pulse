"""AE daily updates — mostly about not letting two people clobber each other,
which the Django app did silently via get_or_create + overwrite."""

DAY = "2030-05-06"


def body(member, **over):
    return {"member_id": member, "entry_date": DAY, "notes": "shipped things",
            "metrics": {"bug_fixes": 3, "deployments": 1}} | over


async def test_create_then_read_back(client, ae_member):
    r = await client.put("/api/ae/daily", json=body(ae_member))
    assert r.status_code == 200
    assert r.json()["metrics"]["bug_fixes"] == 3

    one = (await client.get(f"/api/ae/daily/{ae_member}/{DAY}")).json()
    assert one["metrics"]["deployments"] == 1 and one["notes"] == "shipped things"


async def test_overwrite_without_version_conflicts(client, ae_member):
    await client.put("/api/ae/daily", json=body(ae_member))
    r = await client.put("/api/ae/daily", json=body(ae_member, notes="clobbered"))
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "stale_update"


async def test_overwrite_with_current_version_succeeds(client, ae_member):
    created = (await client.put("/api/ae/daily", json=body(ae_member))).json()
    r = await client.put("/api/ae/daily", json=body(
        ae_member, notes="revised", metrics={"bug_fixes": 9},
        version=created["updated_at"],
    ))
    assert r.status_code == 200
    assert r.json()["notes"] == "revised"
    assert r.json()["metrics"]["bug_fixes"] == 9
    assert r.json()["metrics"]["deployments"] == 1  # untouched metrics survive


async def test_stale_version_conflicts(client, ae_member):
    created = (await client.put("/api/ae/daily", json=body(ae_member))).json()
    await client.put("/api/ae/daily", json=body(
        ae_member, notes="first", version=created["updated_at"]))
    r = await client.put("/api/ae/daily", json=body(
        ae_member, notes="second", version=created["updated_at"]))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale_update"


async def test_rejects_bad_input(client, ae_member, member):
    assert (await client.put("/api/ae/daily", json=body(
        ae_member, metrics={"nonsense": 1}))).json()["detail"]["code"] == "unknown_metric"
    assert (await client.put("/api/ae/daily", json=body(
        ae_member, metrics={"bug_fixes": -1}))).json()["detail"]["code"] == "negative_metric"
    # `member` is a content-role member, not an AE
    assert (await client.put("/api/ae/daily", json=body(member))).status_code == 403
    assert (await client.put("/api/ae/daily", json=body(ae_member, notes=""))).status_code == 422


async def test_metric_definitions_come_from_the_database(client):
    metrics = (await client.get("/api/ae/metrics")).json()
    assert len(metrics) == 10
    assert {"key": "bug_fixes", "label": "Bug Fixes", "sort_order": 6} in metrics


async def test_analytics_lists_every_metric_even_at_zero(client, ae_member):
    await client.put("/api/ae/daily", json=body(ae_member))
    data = (await client.get("/api/analytics/ae-metrics", params={
        "from": DAY, "to": DAY, "member_id": ae_member})).json()
    totals = {m["key"]: m["total"] for m in data["totals"]}
    assert len(totals) == 10
    assert totals["bug_fixes"] == 3 and totals["redash_queries"] == 0
