# Document Converter Service v2 — Design Spec

## project code name : Forge

## 한줄 요약

다양한 포맷(스캔 PDF, DOCX, PPTX, HWPX, 이미지 등)을 깨끗한 Markdown/텍스트로 변환하는 독립 마이크로서비스. 포맷별 최적 경로로 처리하며, VLM은 이미지 기반 문서에만 사용.

## 포지션

```
[Document Converter]  :8003  (독립 서비스, REST API)
  파일 → 포맷별 최적 경로 → md/txt 반환

[Cortex]              :8000  (독립 서비스, REST API)
  md/txt → 청킹 → 메타데이터 → 임베딩 → 트리플 → DB
```

- 두 서비스 모두 독립 동작, 독립 배포
- Cortex는 Converter 없이 완전히 동작 (텍스트 PDF, md, txt 직접 처리)
- Converter는 Cortex 없이도 단독 사용 가능 (범용 문서 변환기)

## 설계 원칙

**텍스트가 있으면 추출하고, 없으면 VLM으로 읽는다.**

VLM은 비싸고 느리다. 이미 텍스트가 존재하는 DOCX/PPTX/HWPX를 이미지로 렌더링해서 VLM한테 "읽어줘"라고 하는 건 낭비다. 포맷별로 최적 경로를 탄다.

## 포맷별 처리 경로

```
입력 파일
  │
  ├─ 스캔/디자인 PDF ──→ 페이지 이미지 → VLM → md
  ├─ 이미지 (jpg/png) ─→ 바로 VLM → md
  │
  ├─ DOCX ─────────────→ python-docx 텍스트+표 추출 → md
  ├─ PPTX ─────────────→ python-pptx 슬라이드별 추출 → md
  ├─ HWPX ─────────────→ XML 파싱 텍스트+표 추출 → md
  ├─ XLSX ─────────────→ openpyxl 시트별 추출 → md
  │
  └─ 텍스트 PDF ───────→ 여기 안 옴 (Cortex가 직접 처리)
```

### VLM 경로 (이미지 기반 문서만)

```
PDF/이미지
  → pypdfium2로 페이지별 이미지 변환 (PDF인 경우)
  → VLM에 이미지 전송
  → VLM이 텍스트 추출 + 표 분석 + 이미지 설명
  → md 반환
```

### 추출 경로 (텍스트 기반 문서)

```
DOCX/PPTX/HWPX/XLSX
  → Python 라이브러리로 텍스트+표+구조 추출
  → md 포맷으로 정리
  → 반환
```

추출 경로는 레이아웃 분석이 아니다. 텍스트와 표를 뽑아서 md로 정리하는 수준.

## API

### POST /convert

```
Request:
  Content-Type: multipart/form-data
  file: (binary)

Response:
{
  "text": "# 제목\n\n본문 텍스트...\n\n| 표 | 내용 |\n...",
  "format": "md",
  "pages": 45,
  "file_name": "안산시_제안서.pdf",
  "source_format": "pdf",
  "route": "vlm",
  "quality": {
    "total_chars": 15000,
    "chars_per_page": 333,
    "confidence": "high"
  }
}
```

- `route`: 실제 사용된 경로 ("vlm" | "extract")
- `quality`: 변환 품질 지표. 호출자가 결과를 신뢰할지 판단할 수 있음

### GET /health

```
Response: {"status": "ok"}
```

## 포맷 감지 + 경로 결정

```python
def detect_route(file: UploadFile) -> str:
    ext = get_extension(file.filename)

    # 추출 경로: 텍스트가 이미 있는 포맷
    if ext in (".docx", ".pptx", ".hwpx", ".xlsx"):
        return "extract"

    # VLM 경로: 이미지 기반
    if ext in (".jpg", ".jpeg", ".png", ".tiff", ".bmp"):
        return "vlm"

    # PDF: 텍스트 추출 시도 → 실패하면 VLM
    if ext == ".pdf":
        text = try_extract_pdf_text(file)
        chars_per_mb = len(text) / (file.size / 1_000_000)
        if chars_per_mb < 100:  # 디자인/스캔 PDF
            return "vlm"
        else:
            return "extract"  # 텍스트 PDF도 여기서 처리 가능

    raise UnsupportedFormat(ext)
```

## VLM 설정

```
VLM_URL=http://localhost:11434/v1/chat/completions
VLM_MODEL=qwen2-vl:7b
VLM_API_KEY=
VLM_TIMEOUT=120
```

- OpenAI-compatible 엔드포인트 하나로 통일
- Ollama, vLLM, GPT-4o, LiteLLM(Claude/Gemini 프록시) 전부 같은 인터페이스
- URL + MODEL만 바꾸면 provider 교체 완료

## VLM 프롬프트 (페이지별)

```
이 문서 페이지의 내용을 Markdown으로 변환해.

규칙:
- 모든 텍스트를 레이아웃 순서대로 추출
- 표는 마크다운 표 형식으로 변환
- 이미지/도형은 [이미지: 설명] 형태로 기술
- 제목/소제목은 마크다운 헤딩(#, ##)으로
- 원본 내용을 빠뜨리지 말 것
```

## 프로젝트 구조

```
c:\workspace\prj20060203\
├── Cortex/                    # 기존 — 에이전트 인지 인프라
├── document-converter/        # 신규 — 문서 변환 마이크로서비스
│   ├── app.py                 # FastAPI — /convert, /health
│   ├── router.py              # 포맷 감지 + 경로 결정
│   ├── vlm.py                 # VLM 클라이언트 (OpenAI-compatible)
│   ├── extractors/
│   │   ├── pdf.py             # pypdfium2 이미지 변환 + 텍스트 추출 판별
│   │   ├── docx.py            # python-docx → md
│   │   ├── pptx.py            # python-pptx → md
│   │   ├── hwpx.py            # HWPX XML → md
│   │   ├── xlsx.py            # openpyxl → md
│   │   └── image.py           # 이미지 → VLM 전달
│   ├── config.py              # VLM_URL, VLM_MODEL 환경변수
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
└── docs/
```

## 의존성

```
# 코어
fastapi
uvicorn
httpx               # VLM API 호출

# VLM 경로
pypdfium2           # PDF → 페이지 이미지
Pillow              # 이미지 처리

# 추출 경로
python-docx         # DOCX 텍스트+표
python-pptx         # PPTX 슬라이드
openpyxl            # XLSX 시트
lxml                # HWPX XML 파싱
```

- LibreOffice 불필요
- Docling 불필요
- GPU 불필요 (VLM은 외부 서버 호출)

## 사용 흐름

```bash
# 단독 사용: 문서 변환만
curl -X POST http://converter:8003/convert \
  -F "file=@제안서.pdf" | jq -r .text > 제안서.md

# Cortex 연계: convert → ingest
TEXT=$(curl -s -X POST http://converter:8003/convert \
  -F "file=@제안서.pdf" | jq -r .text)
curl -X POST http://cortex:8000/v1/ingest \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"$TEXT\", \"domain\": \"proposal\"}"

# DOCX도 동일
curl -X POST http://converter:8003/convert \
  -F "file=@기획서.docx" | jq -r .text > 기획서.md

# HWPX도 동일
curl -X POST http://converter:8003/convert \
  -F "file=@보고서.hwpx" | jq -r .text > 보고서.md
```

## Cortex 변경사항

**없음.** Converter는 완전 독립 서비스. Cortex 코드 수정 0.

## 범위 외 (v2)

- 페이지 병렬 VLM 호출
- 변환 결과 캐싱 (같은 파일 재변환 방지)
- VLM 비용 추적
- 혼합 모드 (일부 페이지만 VLM)
- 비동기 변환 (대용량 파일 task 폴링)
- 추출 경로 결과에 VLM 보정 (표 정리 등)

## 이전 스펙과의 관계

| 스펙 | 상태 |
|------|------|
| `2026-04-05-parse-api-vlm.md` | **대체됨.** Cortex 내부 /v1/parse → 독립 서비스로 분리 |
| `2026-04-06-document-converter-service.md` | **대체됨.** PDF 전용 → 멀티포맷, 전부 이미지화 → 하이브리드 |
| 이 문서 (v2) | **현행** |




ㅇㅋ 바로 붙여 넣을 수 있게 준다 👇

---

## Async 처리 모델 (v2 추가)

대용량 문서 및 VLM 처리 지연을 고려하여, Converter는 기본적으로 비동기 Job 기반 처리 모델을 지원한다.

```
POST /convert
→ 즉시 job_id 반환
→ 백그라운드에서 변환 수행
→ 결과는 별도 조회 API로 반환
```

### 처리 흐름

```
요청 → Job 생성 → Queue 적재 → Worker 처리 → 결과 저장 → 조회
```

* VLM 경로는 처리 시간이 길기 때문에 sync 처리 금지
* Worker는 수평 확장 가능 (N개 인스턴스)
* 실패 시 retry 가능

---

## API 확장

### POST /convert (Async)

```
Response:
{
  "job_id": "uuid",
  "status": "queued"
}
```

---

### GET /result/{job_id}

```
Response:
{
  "status": "processing | completed | failed",
  "result": { ... }  // 완료 시만 포함
}
```

---

## Batch 처리 (선택)

다수 파일을 한 번에 처리하기 위한 batch API 지원 가능

```
POST /batch
→ 여러 job 생성 후 job_id 리스트 반환
```

---

## 설계 원칙 추가

* Converter는 요청-응답 API가 아닌 **작업 처리 시스템(Job Processor)** 로 간주한다
* 모든 변환 작업은 비동기 처리 기준으로 설계한다
* Sync 모드는 소형 파일 또는 테스트 용도로만 제한적으로 허용한다



