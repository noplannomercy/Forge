# Forge Callback URL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 변환 완료/실패 시 callback_url로 결과 POST. 3회 retry.

**Architecture:** models.py에 callback_url 필드 추가. app.py에 파라미터 추가. worker.py에서 완료/실패 후 callback 호출.

**Tech Stack:** Python 3.11, FastAPI, httpx, pytest

---

## File Map

| 파일 | 역할 | Task |
|------|------|------|
| `models.py` | Job에 callback_url 필드 | 1 |
| `worker.py` | callback 호출 + retry | 1 |
| `app.py` | callback_url 파라미터 + worker 전달 | 2 |
| `tests/` | 테스트 | 1-2 |

---

### Task 1: Worker callback + Model

**Files:**
- Modify: `models.py`
- Modify: `worker.py`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: models.py에 callback_url 추가**

Job 클래스에 `callback_url` 필드 추가 (기존 `meta_prompt_version` 뒤에):

```python
    callback_url: str | None = None
```

- [ ] **Step 2: 테스트 작성**

```python
# tests/test_worker.py 에 추가

@pytest.mark.asyncio
async def test_worker_calls_callback_on_success(store, config):
    """완료 시 callback_url 호출"""
    job = await store.create("test.docx", "docx", "extract", callback_url="http://cortex/ingest")
    mock_result = ConvertResult(
        text="# Hello", format="md", pages=1, file_name="test.docx",
        source_format="docx", route="extract",
        quality=Quality(total_chars=7, chars_per_page=7, total_pages=1,
                       failed_pages=0, confidence="high", method="extract"),
    )
    with patch("worker.EXTRACTORS", {"docx": AsyncMock(return_value=mock_result)}):
        with patch("worker.MetaExtractor") as MockMeta:
            mock_meta = AsyncMock()
            mock_meta.extract = AsyncMock(return_value={})
            mock_meta.close = AsyncMock()
            MockMeta.return_value = mock_meta
            with patch("worker._send_callback", new_callable=AsyncMock) as mock_cb:
                await process_job(job, b"fake", "extract", store, config)
    mock_cb.assert_called_once()
    call_args = mock_cb.call_args
    assert call_args[0][0] == "http://cortex/ingest"  # url
    assert call_args[0][1]["status"] == "completed"     # payload


@pytest.mark.asyncio
async def test_worker_calls_callback_on_failure(store, config):
    """실패 시에도 callback_url 호출"""
    job = await store.create("bad.docx", "docx", "extract", callback_url="http://cortex/ingest")
    with patch("worker.EXTRACTORS", {"docx": AsyncMock(side_effect=Exception("corrupt"))}):
        with patch("worker._send_callback", new_callable=AsyncMock) as mock_cb:
            await process_job(job, b"bad", "extract", store, config)
    mock_cb.assert_called_once()
    call_args = mock_cb.call_args
    assert call_args[0][1]["status"] == "failed"
    assert "corrupt" in call_args[0][1]["error"]


@pytest.mark.asyncio
async def test_worker_no_callback_when_url_missing(store, config):
    """callback_url 없으면 호출 안 함"""
    job = await store.create("test.docx", "docx", "extract")
    mock_result = ConvertResult(
        text="# Hello", format="md", pages=1, file_name="test.docx",
        source_format="docx", route="extract",
        quality=Quality(total_chars=7, chars_per_page=7, total_pages=1,
                       failed_pages=0, confidence="high", method="extract"),
    )
    with patch("worker.EXTRACTORS", {"docx": AsyncMock(return_value=mock_result)}):
        with patch("worker.MetaExtractor") as MockMeta:
            mock_meta = AsyncMock()
            mock_meta.extract = AsyncMock(return_value={})
            mock_meta.close = AsyncMock()
            MockMeta.return_value = mock_meta
            with patch("worker._send_callback", new_callable=AsyncMock) as mock_cb:
                await process_job(job, b"fake", "extract", store, config)
    mock_cb.assert_not_called()
```

- [ ] **Step 3: worker.py에 callback 함수 추가**

worker.py 상단에 `import httpx` 추가. `_extract_meta` 함수 앞에 `_send_callback` 함수 추가:

```python
CALLBACK_RETRIES = 3
CALLBACK_DELAYS = [1, 2, 4]


async def _send_callback(url: str, payload: dict) -> None:
    """callback_url로 결과 POST. 3회 retry."""
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(CALLBACK_RETRIES):
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                logger.info("Callback sent to %s (status %d)", url, response.status_code)
                return
            except Exception as e:
                logger.warning("Callback attempt %d failed: %s", attempt + 1, e)
                if attempt < CALLBACK_RETRIES - 1:
                    await asyncio.sleep(CALLBACK_DELAYS[attempt])
    logger.error("Callback failed after %d attempts: %s", CALLBACK_RETRIES, url)
```

- [ ] **Step 4: worker.py process_job에 callback 호출 추가**

`process_job` 함수의 마지막에 callback 로직 추가. 기존 try/except 구조를 감싸는 형태:

현재 구조:
```python
    try:
        if route == "extract":
            ...
            await store.save_result(job.id, result)
            meta = ...
        elif route == "vlm":
            ...
            await store.save_result(job.id, result)
            meta = ...
    except Exception as e:
        await store.save_error(job.id, str(e))
```

변경: try/except 뒤에 callback 호출 추가:

```python
    try:
        if route == "extract":
            ...
        elif route == "vlm":
            ...
    except Exception as e:
        await store.save_error(job.id, str(e))

    # Callback
    if job.callback_url:
        updated_job = await store.get(job.id)
        if updated_job:
            payload = {
                "job_id": updated_job.id,
                "status": updated_job.status,
                "file_name": updated_job.file_name,
                "file_size": updated_job.file_size,
                "source_format": updated_job.source_format,
                "route": updated_job.route,
                "method": updated_job.method,
                "requested_by": updated_job.requested_by,
                "result_text": updated_job.result.text if updated_job.result else None,
                "meta": updated_job.meta,
                "quality": updated_job.result.quality.model_dump() if updated_job.result else None,
                "prompt_version": updated_job.prompt_version,
                "meta_prompt_version": updated_job.meta_prompt_version,
                "processing_ms": updated_job.processing_ms,
                "error": updated_job.error,
            }
            await _send_callback(job.callback_url, payload)
```

중요: callback은 try/except 바깥에서 실행. 성공이든 실패든 호출.

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_worker.py -v`
Expected: 통과

- [ ] **Step 6: 커밋**

```bash
git add models.py worker.py tests/test_worker.py
git commit -m "feat: callback URL — POST result on job complete/fail with 3x retry"
```

---

### Task 2: API 파라미터 + 전달

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: 테스트 추가**

```python
# tests/test_app.py 에 추가

@pytest.mark.asyncio
async def test_convert_with_callback_url(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock):
            resp = await client.post(
                "/convert?callback_url=http://cortex/ingest",
                files={"file": ("test.docx", b"content", "application/octet-stream")},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
```

- [ ] **Step 2: app.py /convert에 callback_url 추가**

`convert` 엔드포인트에 파라미터 추가:
```python
        callback_url: str | None = Query(None, description="완료/실패 시 결과를 POST할 URL"),
```

`store.create` 호출에 `callback_url=callback_url` 추가:
```python
        job = await current_store.create(
            file_name, source_format, detected_route,
            file_size=len(file_bytes), method=method, requested_by=requested_by,
            callback_url=callback_url,
        )
```

- [ ] **Step 3: app.py /batch에도 동일 추가**

`batch` 엔드포인트에 `callback_url` 파라미터 + `store.create`에 전달.

- [ ] **Step 4: 전체 테스트**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/ -v`
Expected: 전체 통과

- [ ] **Step 5: TODO + CLAUDE.md 업데이트**

- [ ] **Step 6: 커밋**

```bash
git add app.py tests/test_app.py
git commit -m "feat: callback_url parameter on /convert and /batch"
```

---
