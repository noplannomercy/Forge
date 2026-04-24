"""Tests for DoclingLogStore (T13, DOCLING-08).

Mirrors the VLMLogStore test pattern in tests/test_postgres_store.py but
covers both the InMemory and Postgres implementations with the new ABC
signature (keyword-only args, {job_id, pages, latency_ms, status_code,
fallback, reason}).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from job_store import (
    DoclingLogStore,
    InMemoryDoclingLogStore,
    PostgresDoclingLogStore,
)


@pytest.mark.asyncio
async def test_in_memory_insert_and_list():
    """insert then list_all returns the row with all fields preserved."""
    store: DoclingLogStore = InMemoryDoclingLogStore()

    await store.insert(
        job_id="job-1",
        pages=12,
        latency_ms=2500,
        status_code=200,
        fallback=False,
        reason=None,
    )

    rows = await store.list_all()
    assert len(rows) == 1
    row = rows[0]
    assert row["job_id"] == "job-1"
    assert row["pages"] == 12
    assert row["latency_ms"] == 2500
    assert row["status_code"] == 200
    assert row["fallback"] is False
    assert row["fallback_reason"] is None
    assert "created_at" in row


@pytest.mark.asyncio
async def test_in_memory_tracks_both_success_and_fallback():
    """Both a success row and a fallback row are retained, fields distinct."""
    store = InMemoryDoclingLogStore()

    # Success: docling-serve responded 200
    await store.insert(
        job_id="job-ok",
        pages=5,
        latency_ms=1200,
        status_code=200,
        fallback=False,
        reason=None,
    )
    # Fallback: network error → pypdfium2
    await store.insert(
        job_id="job-fallback",
        pages=5,
        latency_ms=0,
        status_code=None,
        fallback=True,
        reason="HTTPError: connect timeout",
    )

    rows = await store.list_all()
    assert len(rows) == 2

    success = next(r for r in rows if r["job_id"] == "job-ok")
    fallback = next(r for r in rows if r["job_id"] == "job-fallback")

    assert success["fallback"] is False
    assert success["status_code"] == 200
    assert success["fallback_reason"] is None

    assert fallback["fallback"] is True
    assert fallback["status_code"] is None
    assert fallback["fallback_reason"] == "HTTPError: connect timeout"


@pytest.mark.asyncio
async def test_in_memory_created_at_populated():
    """created_at is a timezone-aware datetime (UTC)."""
    store = InMemoryDoclingLogStore()
    await store.insert(
        job_id="job-ts",
        pages=1,
        latency_ms=100,
        status_code=200,
        fallback=False,
        reason=None,
    )
    rows = await store.list_all()
    created_at = rows[0]["created_at"]
    assert isinstance(created_at, datetime)
    assert created_at.tzinfo is not None
    # UTC offset should be zero
    assert created_at.utcoffset().total_seconds() == 0


@pytest.mark.asyncio
async def test_postgres_store_uses_pool():
    """PostgresDoclingLogStore.insert acquires a conn and executes INSERT
    with the supplied args in order."""
    # Mock connection — execute is awaited
    conn = AsyncMock()
    conn.execute = AsyncMock()

    # Mock pool — pool.acquire() is an async context manager yielding conn
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=None)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_cm)

    store = PostgresDoclingLogStore(pool)
    await store.insert(
        job_id="job-pg",
        pages=7,
        latency_ms=1800,
        status_code=200,
        fallback=False,
        reason=None,
    )

    # pool.acquire was used as a context manager
    pool.acquire.assert_called_once()
    # execute called once with 7 args: the SQL + 6 positional params
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args
    sql = call_args.args[0]
    params = call_args.args[1:]
    assert "INSERT INTO forge_docling_logs" in sql
    assert params == ("job-pg", 7, 1800, 200, False, None)


@pytest.mark.asyncio
async def test_postgres_store_passes_fallback_row():
    """Fallback rows carry status_code=None and a reason through unchanged."""
    conn = AsyncMock()
    conn.execute = AsyncMock()

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=None)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_cm)

    store = PostgresDoclingLogStore(pool)
    await store.insert(
        job_id="job-fb",
        pages=3,
        latency_ms=0,
        status_code=None,
        fallback=True,
        reason="TimeoutError",
    )

    call_args = conn.execute.call_args
    params = call_args.args[1:]
    assert params == ("job-fb", 3, 0, None, True, "TimeoutError")
