import pytest

from job_store import (
    REFINE_RULE_DEFAULTS,
    InMemoryRefineRuleStore,
    seed_refine_rules,
)


@pytest.fixture
def store():
    return InMemoryRefineRuleStore()


@pytest.mark.asyncio
async def test_active_raises_when_missing(store):
    with pytest.raises(LookupError):
        await store.active("encoding")


@pytest.mark.asyncio
async def test_seed_and_active(store):
    await seed_refine_rules(store)

    # encoding stage: try_order[0] == "utf-8"
    encoding = await store.active("encoding")
    assert encoding["try_order"][0] == "utf-8"
    assert "version" in encoding

    # validator stage: min_length == 100
    validator = await store.active("validator")
    assert validator["min_length"] == 100
    assert validator["require_utf8"] is True

    # every stage in defaults should be seeded
    for stage in REFINE_RULE_DEFAULTS:
        rule = await store.active(stage)
        assert rule["version"] == 1


@pytest.mark.asyncio
async def test_upsert_increments_version(store):
    v1 = await store.upsert("encoding", {"try_order": ["utf-8"]})
    v2 = await store.upsert("encoding", {"try_order": ["utf-8", "cp949"]})
    assert v1 == 1
    assert v2 == 2


@pytest.mark.asyncio
async def test_upsert_marks_previous_inactive(store):
    await store.upsert("encoding", {"try_order": ["utf-8"]})
    await store.upsert("encoding", {"try_order": ["utf-8", "cp949"]})

    versions = await store.list_versions("encoding")
    assert len(versions) == 2
    active = [v for v in versions if v["is_active"]]
    assert len(active) == 1
    assert active[0]["version"] == 2


@pytest.mark.asyncio
async def test_list_versions_returns_newest_first(store):
    await store.upsert("newline", {"replace_with": "\n"})
    await store.upsert("newline", {"replace_with": "\r\n"})
    await store.upsert("newline", {"replace_with": "\n\n"})

    versions = await store.list_versions("newline")
    assert [v["version"] for v in versions] == [3, 2, 1]


@pytest.mark.asyncio
async def test_active_returns_version_key(store):
    await store.upsert("validator", {"min_length": 50, "require_utf8": True})
    rule = await store.active("validator")
    assert rule["version"] == 1
    assert rule["min_length"] == 50
    assert rule["require_utf8"] is True

    # After a second upsert, version in active() reflects the newest
    await store.upsert("validator", {"min_length": 200, "require_utf8": False})
    rule2 = await store.active("validator")
    assert rule2["version"] == 2
    assert rule2["min_length"] == 200


@pytest.mark.asyncio
async def test_seed_is_idempotent(store):
    await seed_refine_rules(store)
    await seed_refine_rules(store)  # second call should not bump versions
    for stage in REFINE_RULE_DEFAULTS:
        rule = await store.active(stage)
        assert rule["version"] == 1


@pytest.mark.asyncio
async def test_upsert_rejects_config_with_version_key():
    store = InMemoryRefineRuleStore()
    with pytest.raises(ValueError, match="version"):
        await store.upsert("encoding", {"try_order": ["utf-8"], "version": 99})
