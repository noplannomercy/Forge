# Forge — Document Converter Service

다양한 포맷(PDF, DOCX, PPTX, XLSX, HWPX, 이미지)을 Markdown으로 변환하는 비동기 REST 마이크로서비스.
소스 코드를 업로드하면 VLM이 역문서(업무 명세 MD)를 자동 생성하는 `/reverse-doc` 엔드포인트도 제공.
변환 완료 후 callback URL로 결과를 POST해 LightRAG, Cortex 등 RAG 파이프라인에 자동 주입 가능.

---

## 지원 포맷

| 포맷 | 경로 | 방식 |
|------|------|------|
| DOCX | extract | python-docx 텍스트+표 |
| XLSX | extract | openpyxl 시트별 표 |
| HWPX | docling | LibreOffice DOCX bridge → docling-serve |
| PDF (텍스트) | extract | pypdfium2 텍스트 추출 |
| PDF (이미지/스캔) | vlm | semantic 배치 VLM 재구성 |
| PPTX | vlm | LibreOffice→PDF→VLM |
| JPG/PNG/TIFF/BMP | vlm | VLM 직접 |

---

## 퀵스타트

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

PPTX VLM 경로 또는 HWPX 변환을 사용하려면 LibreOffice도 필요:
```bash
# Windows
winget install TheDocumentFoundation.LibreOffice

# Linux (Docker)
apt-get install -y libreoffice-core
```

### 2. 환경변수 설정

```bash
cp .env.example .env
```

`.env` 필수 설정:
```env
VLM_URL=https://openrouter.ai/api/v1/chat/completions
VLM_MODEL=google/gemini-2.0-flash-001
VLM_API_KEY=sk-or-v1-xxx
```

PostgreSQL 사용 시 (프로덕션):
```env
DATABASE_URL=postgresql://user:pass@localhost:5432/dbname
```

### 3. DB 스키마 적용 (PostgreSQL 사용 시)

```bash
psql -h localhost -p 5432 -U user -d dbname -f schema.sql
```

### 4. 서버 실행

```bash
uvicorn app:app --port 8003
```

### 5. 헬스체크

```bash
curl http://localhost:8003/health
# {"status":"ok"}
```

---

## API 사용법

### 문서 변환 — `/convert`

```bash
# 기본 변환
curl -X POST http://localhost:8003/convert -F "file=@document.docx"
# {"job_id":"uuid","status":"queued"}

# 결과 조회
curl http://localhost:8003/result/{job_id}

# 마크다운 텍스트만
curl http://localhost:8003/result/{job_id}?format=text

# 경로 강제 지정 (extract | vlm | docling)
curl -X POST "http://localhost:8003/convert?route=docling" -F "file=@document.pdf"

# LightRAG/Cortex callback 포함
curl -X POST "http://localhost:8003/convert?callback_url=http://lightrag:9621/documents/text" \
  -F "file=@document.pdf"

# 도메인 태그 포함 (callback payload에 전달됨)
curl -X POST "http://localhost:8003/convert?callback_url=...&domain=finance" \
  -F "file=@report.pdf"
```

### 배치 변환 — `/batch`

```bash
curl -X POST http://localhost:8003/batch \
  -F "files=@doc1.docx" \
  -F "files=@doc2.pdf" \
  -F "files=@doc3.hwpx"
```

### 역문서 생성 — `/reverse-doc`

소스 코드(PL/SQL, Python, SQL 등)를 업로드하면 VLM이 업무 명세 Markdown을 생성한다.

```bash
# 소스 코드 업로드 → 역문서 생성 (비동기)
curl -X POST http://localhost:8003/reverse-doc \
  -F "file=@procedure.pkb"
# {"job_id":"uuid","status":"queued"}

# 결과 조회
curl http://localhost:8003/result/{job_id}?format=text

# callback URL 포함 (LightRAG 자동 주입)
curl -X POST http://localhost:8003/reverse-doc \
  -F "file=@procedure.pkb" \
  -F "callback_url=http://lightrag:9621/documents/text"
```

생성된 역문서는 7개 섹션(업무목적 · 처리흐름 · 입력/출력 · 규칙/예외 · 근거 · 추적성 · 관련업무)을 포함하며,
gate 통과 후 최대 3회 refinement를 거쳐 반환된다.

> **제한**: 최대 200KB (일반 /convert의 100MB와 별개)

### MD 정제 — `/refine`

기존 Markdown을 6단계 규칙 기반으로 정제한다. 동기 응답.

```bash
# 파일로 전달
curl -X POST http://localhost:8003/refine \
  -F "file=@draft.md"

# 텍스트로 전달
curl -X POST http://localhost:8003/refine \
  -F "text=## 제목\n\n본문..."
```

응답 예시:
```json
{
  "refined_text": "## 제목\n\n본문...",
  "report": {"applied_rules": [...], "skipped_rules": [...]},
  "quality": {"score": 0.92, ...},
  "rule_versions": {"heading_normalize": "1.0", ...}
}
```

---

## 관리 API

관리 API는 `X-Forge-Key` 인증 필요 (`.env`에 `FORGE_API_KEY` 설정):

```bash
# Job 목록
curl -H "X-Forge-Key: key" http://localhost:8003/jobs

# 필터
curl -H "X-Forge-Key: key" "http://localhost:8003/jobs?status=completed&source_format=pdf"

# 단건 상세
curl -H "X-Forge-Key: key" http://localhost:8003/jobs/{id}

# 메타 수정
curl -X PATCH -H "X-Forge-Key: key" -H "Content-Type: application/json" \
  -d '{"category":"수정됨"}' http://localhost:8003/jobs/{id}/meta

# 메타 재추출
curl -X POST -H "X-Forge-Key: key" http://localhost:8003/jobs/{id}/retry

# 삭제 (soft delete)
curl -X DELETE -H "X-Forge-Key: key" http://localhost:8003/jobs/{id}

# 일별 통계
curl -H "X-Forge-Key: key" "http://localhost:8003/stats/daily?from=2026-04-07&to=2026-04-09"

# 비용 집계
curl -H "X-Forge-Key: key" "http://localhost:8003/stats/cost?from=2026-04-07&to=2026-04-09"

# 모델별 통계
curl -H "X-Forge-Key: key" http://localhost:8003/stats/models
```

---

## 프롬프트 관리

코드 배포 없이 VLM 프롬프트를 교체할 수 있다.

```bash
# 프롬프트 목록 (버전 이력)
curl -H "X-Forge-Key: key" http://localhost:8003/prompts

# 활성 프롬프트 조회
curl -H "X-Forge-Key: key" http://localhost:8003/prompts/semantic/active

# 새 프롬프트 등록
curl -X POST -H "X-Forge-Key: key" -H "Content-Type: application/json" \
  -d '{"type":"semantic","text":"새 프롬프트..."}' http://localhost:8003/prompts
```

프롬프트 타입: `semantic` (문서 변환용), `meta_extract` (메타 추출용), `reverse_doc` (역문서 생성용)

---

## Swagger UI

```
http://localhost:8003/docs
```

---

## Docker

```bash
docker build -t forge .
docker run -p 8003:8003 --env-file .env forge
```

---

## 환경변수 전체

| 변수 | 기본값 | 설명 |
|------|--------|------|
| VLM_URL | http://localhost:11434/v1/chat/completions | VLM 엔드포인트 |
| VLM_MODEL | qwen2-vl:7b | VLM 모델 |
| VLM_API_KEY | | VLM API 키 |
| VLM_TIMEOUT | 120 | VLM 타임아웃 (초) |
| VLM_CONCURRENCY | 3 | VLM 동시 호출 수 |
| VLM_BATCH_SIZE | 5 | semantic 배치당 페이지 수 |
| HOST | 0.0.0.0 | 서버 호스트 |
| PORT | 8003 | 서버 포트 |
| MAX_FILE_SIZE | 104857600 | 최대 파일 크기 (100MB) |
| DATABASE_URL | | PostgreSQL DSN (미설정 시 InMemory) |
| FORGE_API_KEY | | 관리 API 인증 키 (빈 값이면 비활성화) |
| META_LLM_URL | | 메타 추출 LLM URL (미설정 시 VLM fallback) |
| META_LLM_MODEL | | 메타 추출 모델 |
| META_LLM_API_KEY | | 메타 추출 API 키 |
| REVDOC_MODEL | | 역문서 전용 모델 (미설정 시 VLM_MODEL fallback) |
| DOCLING_SERVE_URL | | docling-serve HTTP URL (HWPX/Docling 경로 필요) |
| DOCLING_API_KEY | | docling-serve API 키 |
| CALLBACK_API_KEY | | callback POST 시 X-API-Key 헤더 값 |
| CALLBACK_FIELD_MAP | | callback payload 필드명 rename (JSON 문자열) |
| CALLBACK_KEEP_UNMAPPED | true | false 시 rename되지 않은 필드 제거 |

### CALLBACK_FIELD_MAP 예시

LightRAG `/documents/text`는 `text`와 `file_source` 필드를 요구한다:

```env
CALLBACK_FIELD_MAP={"content": "text", "file_name": "file_source"}
CALLBACK_KEEP_UNMAPPED=false
```

이 설정으로 Forge 기본 payload의 `content` → `text`, `file_name` → `file_source`로 rename되고,
나머지 Forge 전용 필드(`forge_job_id`, `domain` 등)는 제거된다.

---

## LightRAG 연동

Forge → LightRAG 자동 인제스트 파이프라인:

```
파일 또는 소스코드
  → Forge /convert 또는 /reverse-doc
    (callback_url=http://lightrag:9621/documents/text)
  → 변환/역문서 생성 + 메타 추출
  → callback POST (CALLBACK_FIELD_MAP으로 payload rename)
  → LightRAG /documents/text 인제스트
  → 그래프 인덱싱 → 검색 가능
```

`.env` 설정:
```env
CALLBACK_FIELD_MAP={"content": "text", "file_name": "file_source"}
CALLBACK_KEEP_UNMAPPED=false
CALLBACK_API_KEY=           # LightRAG auth_mode=disabled 이면 불필요
```

변환 요청:
```bash
curl -X POST "http://localhost:8003/convert?callback_url=http://193.168.195.222:9621/documents/text" \
  -F "file=@manual.pdf"

curl -X POST http://localhost:8003/reverse-doc \
  -F "file=@procedure.pkb" \
  -F "callback_url=http://193.168.195.222:9621/documents/text"
```

---

## Cortex 연동

Forge → Cortex 자동 파이프라인:

```
파일 → Forge /convert?callback_url=http://cortex/v1/ingest
  → 변환 + 메타 추출
  → callback POST (pre_converted=true, X-API-Key)
  → Cortex ingest → 청킹 → 검색 가능
```

상세: `hist/2026-04-09-cortex-integration-guide.md`

---

## 테스트

```bash
python -m pytest tests/ -v
# 275+ passed
# 예상 실패: LibreOffice 미설치 시 test_office.py 2건
```

---

## Docling-Serve 연동

HWPX 파일 또는 `?route=docling`을 사용하려면 docling-serve가 필요하다.

```env
DOCLING_SERVE_URL=http://your-server:5001
DOCLING_API_KEY=             # 필요 시
```

로컬에 직접 설치하거나 Docker로 별도 구동한 뒤 URL을 지정한다.
설정하지 않으면 docling 경로 요청 시 500 에러가 반환된다.
