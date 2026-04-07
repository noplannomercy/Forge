# Forge — Document Converter Service v2 Design Spec

## 한줄 요약

다양한 포맷(스캔 PDF, DOCX, PPTX, XLSX, 이미지)을 Markdown으로 변환하는 독립 마이크로서비스. 포맷별 최적 경로(추출 vs VLM)로 처리하며, 비동기 Job 기반으로 동작한다.

---

## 설계 결정 요약

| 결정 | 선택 | 이유 |
|------|------|------|
| Job 처리 | 인메모리 + JobStore 인터페이스 분리 | Redis 전환 대비. v2에서는 인메모리로 충분 |
| 스택 | Python 3.11 + FastAPI + uvicorn | Cortex와 동일 스택, 유지보수 통일 |
| VLM 동시성 | asyncio.Semaphore (기본 3) | 순차는 너무 느림, 10줄 추가로 실용성 확보 |
| HWPX | v2 제외 | 추후 API 기반 추가 |
| 에러 처리 | 페이지 레벨 부분 실패 허용 | 한 페이지 실패로 전체 실패 방지 |
| 아키텍처 | 단일 프로세스 모놀리스 | Redis 도입 전까지 프로세스 분리는 오버엔지니어링 |

---

## 프로젝트 구조

```
Forge/
├── app.py                  # FastAPI — /convert, /result/{job_id}, /batch, /health
├── router.py               # 포맷 감지 + 경로 결정 (extract vs vlm)
├── vlm.py                  # VLM 클라이언트 (httpx async, OpenAI-compatible)
├── job_store.py            # JobStore ABC + InMemoryJobStore
├── worker.py               # 비동기 변환 워커 (asyncio.create_task)
├── config.py               # 환경변수 (pydantic-settings)
├── models.py               # Pydantic 모델 (Job, ConvertResult, PageResult, Quality)
├── extractors/
│   ├── __init__.py
│   ├── pdf.py              # pypdfium2 — 텍스트 추출 판별 + 이미지 변환
│   ├── docx.py             # python-docx → md
│   ├── pptx.py             # python-pptx → md
│   ├── xlsx.py             # openpyxl → md
│   └── image.py            # 이미지 → VLM 전달
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## 비동기 Job 흐름

```
POST /convert
  → router.detect_route(file) → "vlm" | "extract"
  → job_store.create(file_name, format) → Job(status=queued)
  → asyncio.create_task(worker.process(job, file_bytes, route))
  → 즉시 {"job_id": "...", "status": "queued"} 반환

worker.process():
  → job_store.update_status(job_id, "processing")
  → route == "vlm"   → vlm.py (Semaphore 동시 3)
     route == "extract" → extractors/*.py
  → 성공: job_store.save_result(job_id, result)
     실패: job_store.save_error(job_id, error)

GET /result/{job_id}
  → job_store.get(job_id)
  → status + result (completed일 때만)
```

### Job 상태 전이

```
queued → processing → completed
                    → failed
```

### JobStore 인터페이스

```python
class JobStore(ABC):
    async def create(self, file_name: str, source_format: str, route: str) -> Job
    async def get(self, job_id: str) -> Job | None
    async def update_status(self, job_id: str, status: str) -> None
    async def save_result(self, job_id: str, result: ConvertResult) -> None
    async def save_error(self, job_id: str, error: str) -> None
```

InMemoryJobStore → 나중에 RedisJobStore로 교체. app.py, router.py, extractors 코드 변경 없음.

---

## 포맷 감지 + 라우팅

```python
EXTRACT_FORMATS = {".docx", ".pptx", ".xlsx"}
VLM_FORMATS = {".jpg", ".jpeg", ".png", ".tiff", ".bmp"}

def detect_route(file_name, file_bytes) -> tuple[str, str]:
    ext = Path(file_name).suffix.lower()
    if ext in EXTRACT_FORMATS: return ("extract", ext[1:])
    if ext in VLM_FORMATS: return ("vlm", ext[1:])
    if ext == ".pdf":
        chars_per_mb = try_extract_pdf_text(file_bytes)
        return ("vlm" if chars_per_mb < 100 else "extract", "pdf")
    raise UnsupportedFormatError(ext)
```

---

## VLM 클라이언트

- OpenAI-compatible `/v1/chat/completions` 엔드포인트 호출
- httpx.AsyncClient 사용
- asyncio.Semaphore로 동시 호출 제한 (기본 3, VLM_CONCURRENCY 환경변수)

### 페이지 레벨 부분 실패

```python
async def process_page(self, image: bytes, page_num: int) -> PageResult:
    """실패 시 예외 안 던짐 — placeholder 텍스트 반환"""
    async with self.semaphore:
        try:
            response = await self.client.post(url, json={...})
            return PageResult(page=page_num, text=..., success=True)
        except Exception as e:
            return PageResult(page=page_num, text=f"[변환 실패: 페이지 {page_num}]", success=False, error=str(e))

async def process_document(self, images: list[bytes]) -> DocumentResult:
    tasks = [self.process_page(img, i+1) for i, img in enumerate(images)]
    results = await asyncio.gather(*tasks)
    text = "\n\n".join(r.text for r in results)
    failed = [r for r in results if not r.success]
    return DocumentResult(
        text=text,
        total_pages=len(results),
        failed_pages=len(failed),
        confidence="high" if not failed else "partial"
    )
```

---

## Extractors

각 extractor는 동일 시그니처의 함수:

```python
async def extract(file_bytes: bytes, file_name: str) -> ConvertResult
```

| 모듈 | 라이브러리 | 변환 |
|------|-----------|------|
| docx.py | python-docx | 텍스트 + 표 → md |
| pptx.py | python-pptx | 슬라이드별 텍스트 → md |
| xlsx.py | openpyxl | 시트별 데이터 → md 표 |
| pdf.py | pypdfium2 | 텍스트 추출 (extract 경로) 또는 이미지 변환 (vlm 경로) |
| image.py | Pillow | 이미지 전처리 → VLMClient 전달 |

worker.py에서 라우팅:

```python
async def process(job, file_bytes, route):
    if route == "extract":
        result = await EXTRACTORS[job.source_format](file_bytes, job.file_name)
    elif route == "vlm":
        images = await to_images(file_bytes, job.source_format)
        result = await vlm_client.process_document(images)
```

---

## API 엔드포인트

| Method | URL | 설명 |
|--------|-----|------|
| POST | `/convert` | 파일 업로드 → job_id 반환 |
| GET | `/result/{job_id}` | 변환 결과 조회 |
| POST | `/batch` | 다중 파일 → job_id 리스트 반환 |
| GET | `/health` | 헬스체크 |

### POST /convert 응답

```json
{"job_id": "uuid", "status": "queued"}
```

### GET /result/{job_id} 응답 (completed)

```json
{
  "status": "completed",
  "result": {
    "text": "# 제목\n\n본문...",
    "format": "md",
    "pages": 45,
    "file_name": "제안서.pdf",
    "source_format": "pdf",
    "route": "vlm",
    "quality": {
      "total_chars": 15000,
      "chars_per_page": 333,
      "total_pages": 45,
      "failed_pages": 2,
      "confidence": "partial"
    }
  }
}
```

---

## Config

```python
class Config(BaseSettings):
    vlm_url: str = "http://localhost:11434/v1/chat/completions"
    vlm_model: str = "qwen2-vl:7b"
    vlm_api_key: str = ""
    vlm_timeout: int = 120
    vlm_concurrency: int = 3
    host: str = "0.0.0.0"
    port: int = 8003
    model_config = SettingsConfigDict(env_file=".env")
```

---

## 의존성

```
# 코어
fastapi
uvicorn
httpx
pydantic-settings

# VLM 경로
pypdfium2
Pillow

# 추출 경로
python-docx
python-pptx
openpyxl

# 테스트
pytest
pytest-asyncio
```

- LibreOffice 불필요
- GPU 불필요 (VLM은 외부 서버 호출)

---

## 배포

- 포트 8003 (Cortex :8000과 분리)
- Docker 단독 컨테이너
- Cortex 코드 수정 0 — 완전 독립

---

## 범위 외 (v2)

- HWPX 지원 (추후 API 기반 추가)
- 변환 결과 캐싱
- VLM 비용 추적
- 혼합 모드 (일부 페이지만 VLM)
- 추출 경로에 VLM 보정
- 인증/인가
- Redis 기반 Job Store (인터페이스 준비만)

---

## 이전 스펙과의 관계

| 스펙 | 상태 |
|------|------|
| 2026-04-05-parse-api-vlm.md | 대체됨 |
| 2026-04-06-document-converter-service.md | 대체됨 |
| 2026-04-07-document-converter-service-v2.md | office-hours 결과 (이 스펙의 입력) |
| 이 문서 | 현행 — 구현 기준 |
