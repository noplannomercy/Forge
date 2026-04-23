# Forge-Cortex 연동 가이드

> 이 문서는 Forge와 Cortex가 어떻게 통신하는지, callback 구조,
> 인증 체계, URL 패턴, 실제 테스트 방법을 설명한다.

---

## 역할 분담

```
Forge (포트 8003)              Cortex (포트 9000)
──────────────────            ──────────────────
파일 → 마크다운 변환           마크다운 → 청킹 + 임베딩 + 검색
메타데이터 자동 추출            그래프 (AGE) + 벡터 (pgvector)
프롬프트 버전 관리              RAG 질의 응답
VLM 호출 + 비용 추적           사용자 인터페이스
```

두 서비스는 **완전 독립**. 같은 DB를 공유하지만 테이블은 분리 (forge_* vs Cortex 테이블).
코드 의존성 0. Forge는 Cortex 코드를 참조하지 않고, Cortex도 Forge 코드를 참조하지 않는다.

---

## 통신 흐름

### 플로우 1: Cortex가 Forge에 변환 위임

Cortex의 `/v1/ingest/file`에 파일을 올리면, Cortex가 Forge에 변환을 위임하고
결과를 callback으로 돌려받는다.

```
사용자                    Cortex                      Forge
  │                        │                           │
  │ POST /v1/ingest/file   │                           │
  │ (X-API-Key: test)      │                           │
  │ file=@문서.docx        │                           │
  │ ──────────────────────►│                           │
  │                        │                           │
  │                        │ POST /convert              │
  │                        │ ?callback_url=http://cortex:9000/v1/ingest
  │                        │ ?callback_api_key=test     │
  │                        │ ?requested_by=cortex       │
  │                        │ ?domain=general            │
  │                        │ file=@문서.docx            │
  │                        │ ─────────────────────────►│
  │                        │                           │
  │                        │     200 {job_id, queued}   │
  │ ◄─────────────────────│                           │
  │ 200 {delegated_to_forge,                           │
  │      forge_job_id}     │                           │
  │                        │                           │
  │                        │   (Forge가 변환 처리...)   │
  │                        │                           │
  │                        │                    변환 완료│
  │                        │                           │
  │                        │ POST /v1/ingest           │
  │                        │ X-API-Key: test           │
  │                        │ {content, file_name,       │
  │                        │  domain, metadata,         │
  │                        │  pre_converted: true}      │
  │                        │ ◄─────────────────────────│
  │                        │                           │
  │                        │ Cortex: 청킹 + 임베딩     │
  │                        │ → documents 테이블에 저장  │
```

### 플로우 2: 직접 Forge 호출

Cortex를 거치지 않고 Forge API를 직접 호출할 수도 있다.

```bash
# 변환만 (callback 없음)
curl -X POST http://localhost:8003/convert -F "file=@문서.docx"
# → job_id 받고
curl http://localhost:8003/result/{job_id}
# → 마크다운 결과 직접 조회

# 변환 + callback (Cortex로 자동 전달)
curl -X POST "http://localhost:8003/convert?callback_url=http://cortex:9000/v1/ingest&domain=legal" \
  -F "file=@계약서.pdf"
# → 변환 완료 후 Cortex에 자동 POST
```

---

## Callback 상세

### Forge가 보내는 Callback Payload

변환 완료 후 Forge가 `callback_url`로 POST하는 내용:

```json
{
  "content": "# 제목\n\n변환된 마크다운 본문...",
  "file_name": "거버 제안_V.0.2.docx",
  "domain": "general",
  "metadata": {
    "category": "LLM 거버넌스",
    "title": "현대케피코 LLM 거버넌스 제안서",
    "summary": "폐쇄망 환경에서 LLM 서비스를 안전하게 운영하기 위한 제안",
    "keywords": ["LLM", "거버넌스", "폐쇄망", "OpenWebUI", "vLLM"]
  },
  "extract": true,
  "pre_converted": true,
  "forge_job_id": "a39db89c-e26e-40e3-9f4b-f66e0aa26301",
  "forge_status": "completed",
  "forge_error": null
}
```

**필드 설명:**

| 필드 | 설명 | Cortex가 쓰는 용도 |
|------|------|---------------------|
| `content` | 변환된 마크다운 전문 | 청킹 대상 텍스트 |
| `file_name` | 원본 파일명 | source 식별 |
| `domain` | 문서 분류 | 인덱스/검색 필터 |
| `metadata` | 자동 추출 메타 | 검색 보강 + 필터링 |
| `pre_converted` | `true` (항상) | Cortex에게 "이미 변환됨, 텍스트 그대로 써라" 신호 |
| `extract` | `true` (항상) | Cortex 내부 플래그 |
| `forge_job_id` | Forge Job UUID | Cortex→Forge 역추적 |
| `forge_status` | completed 또는 failed | 실패 시에도 callback 보냄 |
| `forge_error` | 에러 메시지 (실패 시) | 실패 원인 전달 |

### Callback Retry

```
시도 1 → 실패 → 1초 대기
시도 2 → 실패 → 2초 대기
시도 3 → 실패 → 로그에 에러 기록, 포기
```

3회 retry 후 전부 실패해도 **변환 결과 자체는 forge_jobs에 보존**.
나중에 `/result/{job_id}`로 직접 조회하거나, `/jobs/{id}/retry`로 메타 재추출 가능.

### Callback 실패 시

변환 결과는 DB에 있으므로 데이터 유실 없음. callback만 안 간 상태.
수동 복구 방법:

```bash
# 1. Forge에서 결과 확인
curl http://localhost:8003/result/{forge_job_id}

# 2. 수동으로 Cortex에 넣기
curl -X POST -H "X-API-Key: test" -H "Content-Type: application/json" \
  -d '{"content":"마크다운...", "file_name":"...", "pre_converted":true}' \
  http://localhost:9000/v1/ingest
```

---

## Consumer 예시

Forge는 consumer-agnostic하게 callback 결과를 전송한다. 어느 consumer든
`pre_converted=true`, `X-API-Key` 헤더를 수용하면 Forge의 결과를 받을 수 있다.
Forge는 consumer 이름을 전혀 알지 못하며, 단순히 `callback_url`로 payload를
POST할 뿐이다.

### Cortex (기존)

Cortex의 `/v1/ingest`는 Forge의 기본 payload 포맷을 그대로 수용한다.

```bash
curl -X POST "http://forge:8003/convert?callback_url=http://cortex:9000/v1/ingest" \
  -F "file=@doc.pdf"
```

callback payload (기본 포맷):

```json
{
  "content": "...",
  "file_name": "doc.pdf",
  "domain": "...",
  "metadata": {...},
  "extract": true,
  "pre_converted": true,
  "forge_job_id": "...",
  "forge_status": "completed",
  "forge_error": null
}
```

### 타 consumer 예시

일부 consumer는 필드명이 다르다. 예를 들어 어떤 엔드포인트는 `content` 대신
`text`, `file_name` 대신 `file_source`를 기대한다. 이런 경우
`CALLBACK_FIELD_MAP` env로 consumer-specific 코드 없이 **필드명 rename** 만으로
연결할 수 있다.

`.env`:

```
CALLBACK_FIELD_MAP={"content":"text","file_name":"file_source"}
CALLBACK_KEEP_UNMAPPED=false
```

호출:

```bash
curl -X POST "http://forge:8003/convert?callback_url=http://other-consumer:9621/documents/text" \
  -F "file=@doc.pdf"
```

callback payload는 렌더링 시점에 필드명 rename + 매핑되지 않은 key drop을
수행한 뒤 전송된다:

```json
{
  "text": "...",
  "file_source": "doc.pdf"
}
```

### 주의사항

- `CALLBACK_FIELD_MAP`은 Forge 인스턴스 단위의 **단일 env** 값이다. 서로 다른
  payload 포맷을 요구하는 다중 consumer를 병렬 운영하려면 Forge 인스턴스를
  각각 띄워야 한다.
- `CALLBACK_KEEP_UNMAPPED=true`로 두면 rename 규칙에 없는 필드도 그대로 전달
  된다 (consumer가 관대한 경우 유용).
- 이 접근은 **C1 (Cortex 독립)** 을 준수한다 — Forge는 consumer 이름을 알 필요
  없이, env가 시키는 대로 dict 키를 rename해서 POST할 뿐이다.

---

## 인증 체계

### Cortex → Forge 방향

Cortex가 Forge `/convert`를 호출할 때 **인증 없음**. Forge의 변환 API는 공개.
(필요하면 API Gateway나 네트워크 수준에서 제한)

### Forge → Cortex 방향 (callback)

Cortex의 `/v1/ingest`는 `X-API-Key` 헤더가 필요하다.

```
Forge .env:    CALLBACK_API_KEY=test
Cortex .env:   CORTEX_API_KEY=test    (또는 integration compose 기본값)
```

Forge가 callback POST 할 때:
```
Header: X-API-Key: test    ← Forge의 CALLBACK_API_KEY 값
```

Cortex가 수신할 때:
```
검증: request.headers["X-API-Key"] == CORTEX_API_KEY ?
  → 일치: 200 (정상 처리)
  → 불일치: 401 Unauthorized
```

**두 값이 다르면 callback이 401로 거부된다.** 양쪽 `.env`에 반드시 같은 값.

### Cortex 관리 API 인증

Cortex의 `/v1/ingest/file`, `/v1/health` 등도 `X-API-Key`가 필요하다.
사용자가 직접 Cortex API를 호출할 때:

```bash
curl -H "X-API-Key: test" -X POST http://localhost:9000/v1/ingest/file \
  -F "file=@문서.docx"
```

---

## 환경별 URL 매트릭스

같은 코드가 환경에 따라 다른 URL로 통신한다.

### Cortex → Forge 호출 URL

Cortex의 `CORTEX_FORGE_URL` 환경변수 값:

| 환경 | URL |
|------|-----|
| 로컬 (양쪽 host) | `http://localhost:8003` |
| Docker (같은 network) | `http://forge:8003` |
| Docker (분리) | `http://host.docker.internal:8003` |
| AWS ECS | `http://forge.internal:8003` (Cloud Map) |

### Forge → Cortex callback URL

Cortex가 Forge 호출 시 `?callback_url=` 쿼리파라미터로 전달하는 값:

| 환경 | callback_url |
|------|-------------|
| 로컬 (양쪽 host) | `http://localhost:9000/v1/ingest` |
| Docker (같은 network) | `http://cortex:9000/v1/ingest` |
| Docker (분리) | `http://host.docker.internal:9000/v1/ingest` |
| AWS ECS | `http://cortex.internal:9000/v1/ingest` (Cloud Map) |

**핵심:** Forge는 Cortex URL을 하드코딩하지 않는다. 항상 요청의 `callback_url` 파라미터를 따른다.
Cortex가 자기 주소를 넘겨주면 Forge는 그 주소로 결과를 보낸다.

---

## Docker Integration 통신 구조

```
┌──────────────────────────────────────────┐
│            hc-rag-network                │
│                                          │
│  ┌──────────┐       ┌──────────┐        │
│  │ postgres │       │  redis   │        │
│  │  :5432   │       │  :6379   │        │
│  └─────┬────┘       └──────────┘        │
│        │                                 │
│  ┌─────┴────┐       ┌──────────┐        │
│  │ cortex   │◄─────►│  forge   │        │
│  │  :9000   │ HTTP  │  :8003   │        │
│  └──────────┘       └──────────┘        │
│                                          │
└──────────────────────────────────────────┘

cortex → forge:8003/convert     (변환 위임)
forge  → cortex:9000/v1/ingest  (callback)
cortex → postgres:5432          (DB)
forge  → postgres:5432          (DB)
cortex → redis:6379             (캐시)
```

모든 통신은 `hc-rag-network` 안에서 서비스명(DNS alias)으로 이뤄진다.
`localhost`를 사용하지 않는다.

---

## 통합 테스트 방법

### 전제: 4개 컨테이너 실행 중

```bash
docker network create hc-rag-network || true
cd infra && docker compose up -d
cd ../cortex && docker compose -f docker-compose.integration.yml up -d
cd ../Forge && docker compose -f docker-compose.integration.yml up -d
```

### 테스트 1: Cortex 경유 위임

```bash
# Cortex에 파일 업로드 → Forge 위임 → callback → 청크 생성
curl -s -X POST -H "X-API-Key: test" \
  -F "file=@Forge/tests/file/거버 제안_V.0.2.docx" \
  http://localhost:9000/v1/ingest/file

# 예상 응답:
# {"status":"delegated_to_forge", "forge_job_id":"...", "message":"..."}
```

60초 대기 후 결과 확인:

```bash
# Cortex 통계 — 청크 수 확인
curl -s -H "X-API-Key: test" http://localhost:9000/v1/stats
# {"documents": 11, ...}

# DB 직접 확인
docker exec hc-rag-postgres psql -U hc -d hc_rag \
  -c "SELECT COUNT(*) FROM documents"
```

### 테스트 2: Forge 직접 호출 + callback

```bash
# Forge에 직접 업로드 (callback_url 포함)
curl -s -X POST \
  "http://localhost:8003/convert?callback_url=http://cortex:9000/v1/ingest&domain=legal" \
  -F "file=@Forge/tests/file/거버 제안_V.0.2.docx"

# 로그에서 callback 성공 확인
docker logs forge 2>&1 | grep "Callback sent"
# Callback sent to http://cortex:9000/v1/ingest (status 200)
```

### 테스트 3: DB 공존 확인

```bash
docker exec hc-rag-postgres psql -U hc -d hc_rag -c "
SELECT tablename FROM pg_tables
WHERE schemaname='public'
ORDER BY tablename"

# forge_jobs, forge_prompts, forge_vlm_logs  (Forge)
# documents, document_metadata, ...           (Cortex)
```

---

## 검증 완료 결과 (2026-04-09)

Docker integration 환경에서 실제 테스트:

| 테스트 | 결과 |
|--------|------|
| 거버 제안.docx 위임 | 11 chunks |
| 현대케피코.docx 위임 | 14 chunks |
| 총 documents | 25 |
| Entities (그래프) | 222 |
| Relations (그래프) | 210 |
| 서비스명 통신 | cortex:9000 ↔ forge:8003 ✅ |
| X-API-Key 인증 | 양쪽 `test` 일치 ✅ |
| DB 테이블 공존 | forge_* + Cortex 테이블 충돌 없음 ✅ |
| schema.sql auto-apply | 양쪽 lifespan에서 정상 실행 ✅ |

---

## 문제 해결

### callback 401 Unauthorized
Forge의 `CALLBACK_API_KEY`와 Cortex의 `CORTEX_API_KEY`가 다름.
양쪽 `.env` 확인해서 같은 값으로 맞춰야 함.

### callback connection refused
Cortex가 아직 안 떴거나, 네트워크가 다름.
- `docker ps`로 cortex-api 확인
- `docker network inspect hc-rag-network`로 양쪽 다 같은 네트워크에 있는지 확인

### "delegated_to_forge" 후 결과 안 옴
Forge 컨테이너 로그 확인:
```bash
docker logs forge 2>&1 | tail -20
```
- VLM 타임아웃이면 `Callback attempt failed` 로그 확인
- Forge가 안 떠있으면 Cortex 위임 자체가 실패

### Cortex에 중복 청크 생성
같은 파일을 여러 번 위임하면 각각 별도 source로 저장됨.
Cortex 쪽에서 source 중복 체크가 필요할 수 있음 (Forge 영역 아님).
