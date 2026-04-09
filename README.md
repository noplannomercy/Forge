# Forge — Document Converter Service

다양한 포맷(PDF, DOCX, PPTX, XLSX, HWPX, 이미지)을 Markdown으로 변환하는 비동기 REST 마이크로서비스.

## 지원 포맷

| 포맷 | 경로 | 방식 |
|------|------|------|
| DOCX | extract | python-docx 텍스트+표 |
| XLSX | extract | openpyxl 시트별 표 |
| HWPX | extract | ZIP+XML hp:t 텍스트+표 |
| PDF (텍스트) | extract | pypdfium2 텍스트 추출 |
| PDF (이미지/스캔) | vlm | semantic 배치 VLM 재구성 |
| PPTX | vlm | LibreOffice→PDF→VLM |
| JPG/PNG/TIFF/BMP | vlm | VLM 직접 |

## 퀵스타트

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

PPTX VLM 경로를 사용하려면 LibreOffice도 필요:
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
```
VLM_URL=https://openrouter.ai/api/v1/chat/completions
VLM_MODEL=google/gemini-2.0-flash-001
VLM_API_KEY=sk-or-v1-xxx
```

PostgreSQL 사용 시 (프로덕션):
```
DATABASE_URL=postgresql://user:pass@localhost:5432/dbname
```

Cortex callback 사용 시:
```
CALLBACK_API_KEY=cortex-api-key
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

## API 사용법

### 문서 변환

```bash
# 기본 변환
curl -X POST http://localhost:8003/convert -F "file=@document.docx"
# {"job_id":"uuid","status":"queued"}

# 결과 조회
curl http://localhost:8003/result/{job_id}

# 마크다운 텍스트만
curl http://localhost:8003/result/{job_id}?format=text

# 경로 강제 지정
curl -X POST "http://localhost:8003/convert?route=vlm" -F "file=@document.pdf"

# Cortex callback 포함
curl -X POST "http://localhost:8003/convert?callback_url=http://cortex:9000/v1/ingest" -F "file=@document.pdf"
```

### 배치 변환

```bash
curl -X POST http://localhost:8003/batch \
  -F "files=@doc1.docx" \
  -F "files=@doc2.pdf" \
  -F "files=@doc3.hwpx"
```

### 관리 API

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

### 프롬프트 관리

```bash
# 프롬프트 목록 (버전 이력)
curl -H "X-Forge-Key: key" http://localhost:8003/prompts

# 활성 프롬프트 조회
curl -H "X-Forge-Key: key" http://localhost:8003/prompts/semantic/active

# 새 프롬프트 등록 (코드 배포 없이 교체)
curl -X POST -H "X-Forge-Key: key" -H "Content-Type: application/json" \
  -d '{"type":"semantic","text":"새 프롬프트..."}' http://localhost:8003/prompts
```

## Swagger UI

```
http://localhost:8003/docs
```

## Docker

```bash
docker build -t forge .
docker run -p 8003:8003 --env-file .env forge
```

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
| META_LLM_URL | | 메타 추출 LLM URL (미설정 시 VLM fallback) |
| META_LLM_MODEL | | 메타 추출 모델 |
| META_LLM_API_KEY | | 메타 추출 API 키 |
| FORGE_API_KEY | | 관리 API 인증 키 (빈 값이면 비활성화) |
| CALLBACK_API_KEY | | callback 시 X-API-Key 헤더 값 |

## 테스트

```bash
python -m pytest tests/ -v
# 145+ passed
```

## Cortex 연동

Forge → Cortex 자동 파이프라인:

```
파일 → Forge /convert?callback_url=http://cortex/v1/ingest
  → 변환 + 메타 추출
  → callback POST (pre_converted=true, X-API-Key)
  → Cortex ingest → 청킹 → 검색 가능
```

상세: `hist/2026-04-09-cortex-integration-guide.md`
