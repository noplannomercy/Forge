# Forge 프롬프트 외부화 + 버전 관리 — Design Spec

> 2026-04-09 | Forge 프롬프트 관리

## 배경

현재 `SEMANTIC_PROMPT`(vlm.py)과 `META_PROMPT`(meta.py)가 코드에 하드코딩. 프롬프트 변경 시 코드 배포 필요. 어떤 Job이 어떤 프롬프트로 처리됐는지 추적 불가.

## 목표

1. 프롬프트를 DB에 저장하여 코드 배포 없이 교체
2. 버전 이력 보존 — 이전 버전으로 롤백 가능
3. Job에 어떤 프롬프트 버전을 사용했는지 추적 (기존 `prompt_version` 필드 활용)

## 설계 결정사항

| 결정 | 선택 | 이유 |
|------|------|------|
| 프롬프트 종류 | 2개 고정 (semantic, meta_extract) | 현재 필요한 것만. 나중에 확장 가능 |
| 버전 관리 | 이력 보존 (INSERT only, 덮어쓰기 아님) | 롤백 + Job 추적 |
| A/B 테스트 | 스코프 외 | 품질 평가 체계 없이 의미 없음 |
| 로드 방식 | 메모리 캐시 (startup 시 + 등록 시 갱신) | DB 매번 조회 불필요 |
| 초기 시딩 | DB 비어있으면 현재 하드코딩 값을 v1으로 INSERT | 기존 환경 깨지지 않음 |

## DB 스키마

```sql
CREATE TABLE IF NOT EXISTS forge_prompts (
    id          SERIAL PRIMARY KEY,
    type        VARCHAR(30) NOT NULL,     -- 'semantic' | 'meta_extract'
    version     INT NOT NULL,
    text        TEXT NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_forge_prompts_active
    ON forge_prompts(type) WHERE is_active = TRUE;
```

- `type`: `semantic` 또는 `meta_extract`
- `version`: 같은 type 내에서 자동 증가 (1, 2, 3...)
- `is_active`: type당 하나만 TRUE (unique partial index로 보장)
- 새 버전 등록 시: 기존 활성 → `is_active=FALSE`, 새 것 → `is_active=TRUE`

## API

### `GET /prompts`

전체 프롬프트 목록 (버전 이력). 관리 API 인증 적용.

```json
{
  "prompts": [
    {"id": 3, "type": "semantic", "version": 2, "text": "...", "is_active": true, "created_at": "..."},
    {"id": 2, "type": "semantic", "version": 1, "text": "...", "is_active": false, "created_at": "..."},
    {"id": 1, "type": "meta_extract", "version": 1, "text": "...", "is_active": true, "created_at": "..."}
  ]
}
```

### `GET /prompts/{type}/active`

현재 활성 프롬프트 조회.

```
GET /prompts/semantic/active
→ {"type": "semantic", "version": 2, "text": "...", "is_active": true}
```

### `POST /prompts`

새 버전 등록. 기존 활성 버전 비활성화 → 새 버전 활성화.

```json
POST /prompts
{
  "type": "semantic",
  "text": "새 프롬프트 내용..."
}
→ {"id": 4, "type": "semantic", "version": 3, "text": "...", "is_active": true}
```

## 동작 흐름

```
서버 시작 (lifespan startup)
  → DB에서 활성 프롬프트 로드 → 메모리 캐시 (app.state.prompts)
  → DB 비어있으면 현재 하드코딩 값으로 v1 시딩

POST /prompts (새 프롬프트 등록)
  → 기존 활성 is_active=FALSE
  → 새 row INSERT (version=기존max+1, is_active=TRUE)
  → 메모리 캐시 갱신

Worker 변환 시 (process_job)
  → app.state.prompts에서 활성 프롬프트 텍스트 가져옴
  → VLMClient에 프롬프트 전달
  → forge_jobs.prompt_version = "semantic-v{N}" 기록

MetaExtractor 호출 시
  → app.state.prompts에서 meta_extract 프롬프트 가져옴
  → forge_jobs.meta_prompt_version = "meta_extract-v{N}" 기록
```

## 파일 변경 요약

| 파일 | 변경 |
|------|------|
| `schema.sql` | `forge_prompts` 테이블 + unique partial index 추가 |
| `job_store.py` | `PromptStore` 클래스 (get_active, list_all, create_version) |
| `vlm.py` | 하드코딩 `SEMANTIC_PROMPT` 제거 → `prompt` 파라미터로 외부 주입 |
| `meta.py` | 하드코딩 `META_PROMPT` 제거 → `prompt` 파라미터로 외부 주입 |
| `worker.py` | prompts 캐시에서 로드 → VLMClient/MetaExtractor에 전달 + 버전 기록 |
| `admin.py` | `/prompts` 3개 엔드포인트 추가 (인증 적용) |
| `app.py` | startup에서 프롬프트 로드/시딩 + app.state.prompts 캐시 |

## 프롬프트 개선 (v2 등록)

외부화 완료 후, 개선된 프롬프트를 v2로 POST:

### semantic v2 (개선 방향)

- 다이어그램: "화살표 관계, 계층 구조, 인과관계를 명시하라"
- 중복 방지: "이전 배치 내용을 반복하지 마라"
- 세부 텍스트: "이미지 안 텍스트를 빠뜨리지 마라"

### meta_extract v2 (개선 방향)

- budget 추출 정확도 향상
- date 형식 통일 (YYYY-MM-DD)

## 스코프 외

- A/B 테스트 (품질 평가 체계 필요)
- 프롬프트 삭제 (이력 보존 원칙)
- 프롬프트 type 동적 추가 (2개 고정)
