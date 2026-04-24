# Forge 사용자 매뉴얼

Forge 서비스를 처음 쓰는 사람을 위한 실전 가이드.
설치부터 LightRAG 자동 인제스트까지 순서대로 설명한다.

---

## 목차

1. [개요](#1-개요)
2. [설치 및 기동](#2-설치-및-기동)
3. [문서 변환 — /convert](#3-문서-변환--convert)
4. [역문서 생성 — /reverse-doc](#4-역문서-생성--reverse-doc)
5. [MD 정제 — /refine](#5-md-정제--refine)
6. [LightRAG 자동 인제스트](#6-lightrag-자동-인제스트)
7. [결과 조회 및 관리](#7-결과-조회-및-관리)
8. [Swagger UI로 테스트하기](#8-swagger-ui로-테스트하기)
9. [환경변수 빠른 참조](#9-환경변수-빠른-참조)
10. [자주 발생하는 문제](#10-자주-발생하는-문제)

---

## 1. 개요

Forge는 다음 두 가지 핵심 기능을 제공한다:

| 기능 | 엔드포인트 | 설명 |
|------|------------|------|
| 문서 변환 | `POST /convert` | PDF, DOCX, XLSX, HWPX, 이미지 → Markdown |
| 역문서 생성 | `POST /reverse-doc` | PL/SQL, Python 등 소스 코드 → 업무 명세 Markdown |

두 기능 모두 `callback_url`을 지정하면 변환 완료 후 결과를 LightRAG(또는 Cortex)에 자동으로 POST한다.

### 동작 흐름

```
[클라이언트]
    │
    ├─ POST /convert (파일 + callback_url)
    │       │
    │       ▼
    │   job_id 즉시 반환 (queued)
    │
    │   [백그라운드]
    │       ├─ 포맷 감지 → extract / vlm / docling 경로 선택
    │       ├─ Markdown 변환
    │       ├─ LLM 메타 추출 (제목, 분류, 키워드, 요약)
    │       └─ callback_url로 POST → LightRAG 인제스트
    │
    └─ GET /result/{job_id}  ← 결과 폴링
```

---

## 2. 설치 및 기동

### 사전 요구사항

- Python 3.11+
- (선택) PostgreSQL — 없으면 인메모리 모드로 동작 (재시작 시 데이터 소실)
- (선택) LibreOffice — HWPX, PPTX VLM 경로에 필요
- (선택) docling-serve — HWPX, `?route=docling` 경로에 필요

### 로컬 설치

```bash
git clone https://github.com/your-org/forge.git
cd forge
pip install -r requirements.txt
```

### 환경변수 설정

```bash
cp .env.example .env
# 편집기로 .env 열어서 VLM_URL, VLM_MODEL, VLM_API_KEY 입력
```

최소 필수 설정:
```env
VLM_URL=https://openrouter.ai/api/v1/chat/completions
VLM_MODEL=google/gemini-2.0-flash-001
VLM_API_KEY=sk-or-v1-...
```

### 서버 기동

```bash
uvicorn app:app --host 0.0.0.0 --port 8003
```

정상 기동 확인:
```bash
curl http://localhost:8003/health
# {"status":"ok"}
```

---

## 3. 문서 변환 — /convert

### 기본 사용법

```bash
# 파일 업로드 → 변환 시작
curl -X POST http://localhost:8003/convert \
  -F "file=@계약서.pdf"

# 응답
{"job_id": "abc123", "status": "queued"}
```

### 결과 조회

```bash
# JSON 전체 (상태 + 텍스트 + 메타 + 품질 정보)
curl http://localhost:8003/result/abc123

# 마크다운 텍스트만
curl "http://localhost:8003/result/abc123?format=text"
```

결과 상태값:
- `queued` — 대기 중
- `processing` — 변환 중
- `completed` — 완료
- `failed` — 오류 (error 필드에 사유)

### 경로 강제 지정

Forge는 파일 확장자/내용으로 경로를 자동 감지하지만 수동으로 지정할 수도 있다:

```bash
# docling 경로 강제 (고품질 PDF 파싱)
curl -X POST "http://localhost:8003/convert?route=docling" -F "file=@report.pdf"

# VLM 경로 강제 (이미지가 많은 PDF)
curl -X POST "http://localhost:8003/convert?route=vlm" -F "file=@scanned.pdf"
```

| 경로 | 언제 쓰나 |
|------|-----------|
| `extract` | 텍스트 기반 DOCX, XLSX, PDF — 빠르고 저렴 |
| `docling` | 복잡한 레이아웃 PDF, HWPX — 정확도 높음 |
| `vlm` | 스캔 PDF, 이미지 위주 PPTX — VLM이 내용 재구성 |

### 포맷별 자동 경로

| 파일 | 자동 선택 경로 |
|------|--------------|
| `.docx` | extract |
| `.xlsx` | extract |
| `.hwpx` | docling (LibreOffice bridge) |
| `.pdf` (텍스트) | extract |
| `.pdf` (스캔/이미지) | vlm |
| `.pptx` | vlm |
| `.jpg`, `.png`, `.tiff` | vlm |

---

## 4. 역문서 생성 — /reverse-doc

Oracle PL/SQL, Python, SQL 등의 소스 코드를 업로드하면 VLM이 업무 명세 Markdown을 생성한다.

### 기본 사용법

```bash
curl -X POST http://localhost:8003/reverse-doc \
  -F "file=@calculate_grade.pkb"

# 응답
{"job_id": "def456", "status": "queued"}
```

### 결과 조회

```bash
curl "http://localhost:8003/result/def456?format=text"
```

출력 예시:
```markdown
## 업무목적
고객 구매 금액 기반 등급 산출 로직을 구현한다.

## 처리흐름
1. customer_id 입력 수신
2. 주문 집계 테이블에서 total_amount 조회
3. 금액 기준 등급 판정 (GOLD / SILVER / BRONZE)
4. 결과 반환

## 입력/출력
- 입력: p_customer_id (VARCHAR2)
- 출력: v_tier (VARCHAR2)

## 규칙/예외
- total_amount > 1,000,000 이면 GOLD
- total_amount > 300,000 이면 SILVER
- 그 외 BRONZE
- NO_DATA_FOUND 예외 시 BRONZE 기본값 반환

## 근거
사내 고객 정책 문서 POLICY-2024-003 기준

## 추적성
이 코드는 POLICY-2024-003 고객 등급 산출 업무 규칙을 구현한다.

## 관련업무
- 선행: 주문 집계 배치 (BATCH_ORDER_AGG)
- 후행: 혜택 부여 프로시저 (GRANT_BENEFIT)
```

### 제약

- 최대 파일 크기: **200KB** (일반 /convert의 100MB와 별개)
- 지원 인코딩: UTF-8 (cp949 파일은 인코딩 변환 후 업로드 권장)

---

## 5. MD 정제 — /refine

기존 Markdown을 6단계 규칙으로 정제한다. 동기 응답 (즉시 결과 반환).

```bash
# 파일로 전달
curl -X POST http://localhost:8003/refine \
  -F "file=@draft.md"

# 텍스트로 직접 전달
curl -X POST http://localhost:8003/refine \
  -F "text=## 제목\n\n내용이 들어갑니다."
```

응답:
```json
{
  "refined_text": "## 제목\n\n내용이 들어갑니다.",
  "report": {
    "applied_rules": ["heading_normalize", "list_indent"],
    "skipped_rules": []
  },
  "quality": {"score": 0.95},
  "rule_versions": {"heading_normalize": "1.0"}
}
```

> `/reverse-doc`은 내부적으로 gate 통과 후 자동으로 refine을 수행하므로
> 역문서 결과물에 대해 별도로 /refine을 호출할 필요는 없다.

---

## 6. LightRAG 자동 인제스트

변환 완료 후 결과를 LightRAG에 자동으로 넣는 파이프라인이다.

### 사전 설정 (.env)

```env
# LightRAG가 요구하는 필드명으로 rename
CALLBACK_FIELD_MAP={"content": "text", "file_name": "file_source"}

# Forge 전용 필드(forge_job_id, domain 등)는 LightRAG로 보내지 않음
CALLBACK_KEEP_UNMAPPED=false

# LightRAG auth_mode=disabled이면 불필요
CALLBACK_API_KEY=
```

서버를 재시작해야 설정이 적용된다.

### 문서 변환 + LightRAG 인제스트

```bash
curl -X POST \
  "http://localhost:8003/convert?callback_url=http://193.168.195.222:9621/documents/text" \
  -F "file=@manual.pdf"
```

### 역문서 생성 + LightRAG 인제스트

```bash
curl -X POST http://localhost:8003/reverse-doc \
  -F "file=@procedure.pkb" \
  -F "callback_url=http://193.168.195.222:9621/documents/text"
```

### 동작 확인

LightRAG 문서 목록 API로 확인:
```bash
curl http://193.168.195.222:9621/documents
```

`file_source` 값으로 파일명이 보이면 인제스트 성공.

### callback payload 구조

`CALLBACK_FIELD_MAP` 적용 후 LightRAG로 전송되는 payload:
```json
{
  "text": "변환된 마크다운 내용...",
  "file_source": "manual.pdf"
}
```

---

## 7. 결과 조회 및 관리

### 결과 조회

```bash
# 전체 JSON
curl http://localhost:8003/result/{job_id}

# 텍스트만 (마크다운 그대로)
curl "http://localhost:8003/result/{job_id}?format=text"
```

전체 JSON 응답 구조:
```json
{
  "id": "uuid",
  "status": "completed",
  "file_name": "document.pdf",
  "source_format": "pdf",
  "route": "extract",
  "result": {
    "text": "## 변환된 내용...",
    "format": "md",
    "pages": 12
  },
  "meta": {
    "title": "연간 보고서",
    "category": "재무",
    "keywords": ["매출", "비용"],
    "summary": "2024년 연간 재무 현황..."
  },
  "quality": {
    "total_chars": 15420,
    "chars_per_page": 1285,
    "confidence": "high"
  },
  "created_at": "2026-04-24T09:30:00+00:00"
}
```

### 관리 API (FORGE_API_KEY 필요)

```bash
FORGE_KEY="your-forge-key"

# 전체 Job 목록
curl -H "X-Forge-Key: $FORGE_KEY" http://localhost:8003/jobs

# 완료된 PDF Job만
curl -H "X-Forge-Key: $FORGE_KEY" \
  "http://localhost:8003/jobs?status=completed&source_format=pdf"

# 메타 수동 수정
curl -X PATCH -H "X-Forge-Key: $FORGE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"category":"계약"}' \
  http://localhost:8003/jobs/{job_id}/meta

# 메타 재추출 (프롬프트 바꾼 후 다시 돌릴 때)
curl -X POST -H "X-Forge-Key: $FORGE_KEY" \
  http://localhost:8003/jobs/{job_id}/retry

# Job 삭제 (soft delete — DB 보존)
curl -X DELETE -H "X-Forge-Key: $FORGE_KEY" \
  http://localhost:8003/jobs/{job_id}

# 일별 변환 통계
curl -H "X-Forge-Key: $FORGE_KEY" \
  "http://localhost:8003/stats/daily?from=2026-04-01&to=2026-04-24"
```

---

## 8. Swagger UI로 테스트하기

브라우저에서 바로 API를 테스트할 수 있다.

```
http://localhost:8003/docs
```

자주 쓰는 순서:

1. **POST /convert** — `Try it out` → `file` 선택 → `Execute`
2. 응답에서 `job_id` 복사
3. **GET /result/{job_id}** — `job_id` 입력 → `Execute`
4. `status`가 `completed`이면 `result.text`에서 변환된 Markdown 확인

---

## 9. 환경변수 빠른 참조

| 변수 | 설명 | 예시 |
|------|------|------|
| `VLM_URL` | VLM API 엔드포인트 | `https://openrouter.ai/api/v1/chat/completions` |
| `VLM_MODEL` | VLM 모델명 | `google/gemini-2.0-flash-001` |
| `VLM_API_KEY` | VLM API 키 | `sk-or-v1-...` |
| `DATABASE_URL` | PostgreSQL DSN | `postgresql://user:pass@host:5432/db` |
| `FORGE_API_KEY` | 관리 API 인증 키 | `forge-secret` |
| `DOCLING_SERVE_URL` | docling-serve URL | `http://192.168.1.100:5001` |
| `REVDOC_MODEL` | 역문서 전용 모델 (옵션) | `google/gemini-2.0-pro` |
| `CALLBACK_API_KEY` | callback POST 인증 키 | LightRAG 비인증이면 불필요 |
| `CALLBACK_FIELD_MAP` | callback payload 필드명 rename | `{"content":"text","file_name":"file_source"}` |
| `CALLBACK_KEEP_UNMAPPED` | rename 안 된 필드 포함 여부 | `false` (LightRAG 연동 시) |

---

## 10. 자주 발생하는 문제

### Job이 `failed` 상태로 끝난다

```bash
curl http://localhost:8003/result/{job_id}
# "error" 필드 확인
```

| 에러 메시지 | 원인 | 해결 |
|------------|------|------|
| `LibreOffice not found` | HWPX/PPTX VLM 경로에 LibreOffice 없음 | LibreOffice 설치 후 재시도 |
| `docling-serve unreachable` | DOCLING_SERVE_URL 미설정 또는 서버 다운 | .env 확인 또는 서버 기동 |
| `VLM API error 429` | 모델 API 속도 제한 | 잠시 후 재시도 |
| `reverse-doc max 200KB` | 소스 파일이 200KB 초과 | 파일 분할 후 각각 업로드 |

### callback이 LightRAG에 도달하지 않는다

1. `.env`에 `CALLBACK_FIELD_MAP`이 설정되어 있는지 확인
2. 서버를 재시작했는지 확인 (환경변수는 재시작해야 적용)
3. `CALLBACK_KEEP_UNMAPPED=false`가 설정되어 있는지 확인
4. LightRAG 서버가 떠있는지 확인: `curl http://lightrag-host:9621/health`

### Windows에서 서버 포트 충돌

```bash
# 8003 포트를 점유한 프로세스 확인
netstat -ano | findstr ":8003"

# PID로 프로세스 종료
taskkill /F /PID {PID}
```

### 한글 파일명이 깨진다

Linux/Mac에서 cp949 인코딩 파일명을 다룰 때 발생.
파일명을 영문으로 바꿔 업로드하거나, `requested_by` 파라미터로 원본명을 기록해 둔다.

### InMemory 모드에서 서버 재시작 후 데이터가 사라졌다

`DATABASE_URL`을 설정하지 않으면 InMemory 모드로 동작한다.
프로덕션에서는 반드시 PostgreSQL `DATABASE_URL`을 설정할 것:

```env
DATABASE_URL=postgresql://forge:password@localhost:5432/forge_db
```

스키마 초기화:
```bash
psql "$DATABASE_URL" -f schema.sql
```
