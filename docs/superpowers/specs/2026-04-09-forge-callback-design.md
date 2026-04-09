# Forge Callback URL — Design Spec

> 2026-04-09 | Forge callback 알림

## 배경

현재 Cortex가 Forge 변환 결과를 받으려면 `/result/{job_id}`를 poll해야 함. callback_url을 지원하면 Forge가 완료 시 Cortex에 push하여 poll 불필요.

## 목표

변환 완료/실패 시 지정된 callback_url로 결과를 POST. 배치는 파일별 개별 callback.

## 설계 결정사항

| 결정 | 선택 | 이유 |
|------|------|------|
| callback 범위 | 단건 + 배치 + 에러 | 성공/실패 모두 알림 필요 |
| 배치 callback | 개별 (파일마다 callback) | 각 파일은 독립적인 Job |
| callback 실패 | 3회 retry (1s, 2s, 4s) + 로그 | 일시적 네트워크 문제 커버, DB에 결과 보존 |
| payload | 전체 (result_text + meta + quality 등) | 300B 차이로 전체 보내는 게 효율적 |
| callback_url 미지정 | 기존과 동일 (callback 안 함) | 하위 호환 |

## API 변경

### `POST /convert`

```
기존: file, route, requested_by
추가: callback_url (optional, URL 문자열)
```

### `POST /batch`

```
기존: files, route, requested_by
추가: callback_url (optional) → 각 Job별로 개별 callback
```

## Callback 동작

```
Job ��료 또는 실패
  → httpx.post(callback_url, json=payload)
  → 실패 시 3회 retry (지수 백오프 1s, 2s, 4s)
  → 3회 모두 실패 → 로그 남기고 포기
  → Job 상태/결과는 DB에 보존 (callback 실패와 무관)
```

### Callback Payload

```json
{
  "job_id": "uuid",
  "status": "completed",
  "file_name": "안산시_제안서.pdf",
  "file_size": 25600000,
  "source_format": "pdf",
  "route": "vlm",
  "method": "semantic",
  "requested_by": "cortex-api",
  "result_text": "## 안산시 강소형 스마트도시...",
  "meta": {"category": "스마트도시", "client": "안산시", ...},
  "quality": {"total_chars": 63835, "total_batches": 13, ...},
  "prompt_version": "semantic-v2",
  "meta_prompt_version": "meta_extract-v1",
  "processing_ms": 84000,
  "error": null
}
```

실패 시:
```json
{
  "job_id": "uuid",
  "status": "failed",
  "file_name": "bad.pdf",
  "error": "conversion failed: ...",
  "result_text": null,
  "meta": {},
  "quality": null
}
```

## 파일 변경 요약

| 파일 | 변경 |
|------|------|
| `models.py` | Job에 `callback_url: str \| None = None` 추가 |
| `app.py` | `callback_url` 파라미터 추가, worker에 전달 |
| `worker.py` | 완료/실패 후 callback ��출 + 3회 retry |

## 스코프 외

- callback 인증 (Cortex 쪽 X-API-Key 헤더 전달 등)
- callback 상태 DB 기록 (callback_status 컬럼)
- 배치 ���체 완료 알림 (개별 callback만)
