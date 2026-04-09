# Cortex → Forge 자동 연동 가이드

> Forge 쪽 전달용 (2026-04-09)

## 현재 상태

수동 호출로 연계 테스트 성공:
```
curl → Forge /convert?callback_url=http://cortex:9000/v1/ingest → Cortex ingest → 11 chunks
```

## Cortex가 해야 할 것

`cortex/core/chunker.py`에서 파일 포맷 감지 후 Forge에 자동 위임.

### 변경 포인트

```
cortex/config.py        — FORGE_URL 환경변수 추가
cortex/core/chunker.py  — 포맷별 Forge 라우팅
cortex/core/ingest.py   — Forge 결과 수신 처리
```

### 로직

```python
# chunker.py 또는 ingest.py에서
FORGE_FORMATS = {".pdf", ".pptx", ".docx", ".xlsx", ".jpg", ".png", ".tiff", ".bmp"}

if file_ext in FORGE_FORMATS:
    # Forge에 변환 요청
    response = httpx.post(
        f"{FORGE_URL}/convert?callback_url={CORTEX_INGEST_URL}&requested_by=cortex",
        files={"file": (file_name, file_bytes)},
    )
    job_id = response.json()["job_id"]
    # callback으로 자동 도착하니까 여기서 끝
    return {"status": "delegated_to_forge", "job_id": job_id}
else:
    # 기존 텍스트 처리
    ...
```

### Forge API 정보

| 항목 | 값 |
|------|-----|
| 변환 요청 | `POST {FORGE_URL}/convert` |
| 파라미터 | `file` (multipart), `callback_url`, `requested_by`, `route` (optional) |
| 응답 | `{"job_id": "uuid", "status": "queued"}` |
| callback payload | `{content, file_name, domain, metadata, extract, pre_converted, forge_job_id, forge_status, forge_error}` |
| 인증 | Forge→Cortex callback 시 `X-API-Key` 헤더 전달 (`CALLBACK_API_KEY` 환경변수) |
| Forge 포트 | 8003 (프로덕션), 8004 (개발 테스트) |

### 환경변수 (Cortex .env에 추가)

```
FORGE_URL=http://localhost:8004
```

### 주의사항

- Forge는 비동기 — `/convert` 호출 즉시 job_id 반환, 결과는 callback으로 도착
- callback이 Cortex `/v1/ingest`로 직접 들어오므로 Cortex 쪽 poll 불필요
- `pre_converted=true` 플래그로 Cortex가 확장자 무시하고 텍스트 모드 처리
- Forge 메타(category, title, keywords 등)가 Cortex metadata에 자동 merge됨
