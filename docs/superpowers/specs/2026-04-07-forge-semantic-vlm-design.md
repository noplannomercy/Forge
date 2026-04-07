# Forge Semantic VLM Mode — Design Spec

> 2026-04-07 | Forge v2

## 배경

Forge v1 수동 테스트에서 PPTX/이미지 PDF의 extract 경로 한계가 확인됨:
- PPTX: 이미지/도표/다이어그램 위주 → extract로 텍스트만 나오고 핵심 내용 누락
- 이미지 PDF (안산시 제안서 64p): 페이지별 OCR → `"02"`, `"03"` 같은 쓰레기 텍스트만 추출

PoC 결과: 안산시 PDF 5페이지를 Gemini semantic 프롬프트로 보냈더니 108줄짜리 구조화된 마크다운 문서로 변환됨. 사업 개요, KPI, 추진 체계까지 의미 단위 재구성 확인.

## 목표

이미지 위주 문서(PPTX, 스캔 PDF)를 **의미 기반으로 재구성**하여 Cortex가 LLM에 넘길 수 있는 품질의 마크다운을 생성한다.

## 설계 결정사항

| 결정 | 선택 | 이유 |
|------|------|------|
| 기존 OCR 모드 | 제거, semantic으로 통합 | OCR은 쓸모없는 결과를 냄 |
| 배치 사이즈 | 설정 가능 (기본 5, `VLM_BATCH_SIZE`) | PoC에서 5장 검증됨, 모델에 따라 조절 |
| PPTX 처리 | LibreOffice headless → PDF → 이미지 → semantic VLM | 기존 PDF 파이프라인 재사용 |
| DOCX VLM | 스코프 외 | extract가 쓸만함, 필요시 추후 추가 |
| PDF 분기 기준 | 자동 감지 유지 (chars_per_mb < 100) + `?route=` 파라미터로 강제 지정 | 자동 + 수동 선택 |
| 프롬프트 전략 | 페이지별 추출이 아닌 배치 단위 의미 재구성 | PoC에서 검증 |

## 라우팅

```
모든 포맷 공통: ?route=extract|vlm 파라미터로 강제 지정 가능

PPTX       → 기본 vlm (semantic)
이미지 PDF → 자동 감지 (chars_per_mb < 100) → vlm (semantic)
텍스트 PDF → 자동 감지 → extract
DOCX/XLSX  → 기본 extract
이미지     → vlm (semantic, 단건)
```

## 처리 흐름

### PPTX
```
PPTX 업로드
  → router: vlm 경로
  → worker: LibreOffice headless로 PPTX→PDF 변환
  → pypdfium2로 PDF→페이지별 이미지
  → 5장씩 묶어서 semantic 프롬프트로 VLM 호출
  → 배치 결과 이어붙여서 ConvertResult 생성
```

### 이미지 PDF
```
PDF 업로드
  → router: chars_per_mb < 100 → vlm 경로
  → worker: pypdfium2로 PDF→페이지별 이미지
  → 5장씩 묶어서 semantic 프롬프트로 VLM 호출
  → 배치 결과 이어붙여서 ConvertResult 생성
```

### 이미지 (단건)
```
이미지 업로드
  → router: vlm 경로
  → worker: 이미지 1장 → semantic 프롬프트로 VLM 호출 (배치 아닌 단건)
```

### DOCX/XLSX/텍스트 PDF — 변경 없음

## VLM 변경

### 기존 (제거)
- `process_page()` — 페이지 1장씩 OCR 프롬프트
- `process_document()` — 페이지별 개별 호출 후 이어붙이기

### 변경
- `process_batch(images: list[bytes], batch_num: int)` — N장 묶어서 semantic 프롬프트로 1회 호출
- `process_document(images: list[bytes])` — 전체 페이지를 `VLM_BATCH_SIZE`장씩 청크로 나눠서 `process_batch()` 반복

### Semantic 프롬프트
```
이 문서 페이지들을 분석해서 의미 중심으로 재구성해.

규칙:
- 페이지별로 나누지 말고, 내용을 주제별로 묶어서 구조화
- 배경 이미지, 장식, 페이지 번호 등 의미 없는 요소는 무시
- 다이어그램/흐름도는 텍스트로 설명
- 표/비교 데이터는 마크다운 표로 재구성
- 핵심 정보만 추출해서 간결한 마크다운 문서로 만들어
- 한국어로 작성
```

### retry / semaphore
- 배치 단위로 적용 (3회 retry, 지수 백오프 1s/2s/4s)
- `VLM_CONCURRENCY` Semaphore로 동시 배치 수 제한

### 부분 실패
- 배치 하나가 실패하면 해당 배치만 `[변환 실패: 페이지 N-M]` placeholder
- 나머지 배치는 보존

## LibreOffice 래퍼

### `extractors/office.py` (신규)
```python
async def pptx_to_pdf(file_bytes: bytes) -> bytes:
    # 임시 파일로 PPTX 저장
    # libreoffice --headless --convert-to pdf --outdir {tmpdir} {input_file}
    # PDF bytes 반환
    # 임시 파일 정리
```

### 의존성
- Docker: `Dockerfile`에 `apt-get install -y libreoffice-core` 추가
- 로컬 개발: 수동 설치 필요

## Quality 메타 개선

### 기존
```json
{"total_chars": 1077, "chars_per_page": 16.8, "total_pages": 64, "failed_pages": 64, "confidence": "partial"}
```

### 변경
```json
{
  "total_chars": 2167,
  "chars_per_page": 433.4,
  "total_pages": 64,
  "failed_pages": 0,
  "failed_batches": 0,
  "total_batches": 13,
  "confidence": "high",
  "route": "vlm",
  "method": "semantic"
}
```

### 추가 필드
- `total_batches` / `failed_batches` — 배치 단위 성공/실패
- `method` — `"semantic"` | `"extract"` — 변환 방식

### Cortex 판단 기준
- `confidence == "high"` + `failed_batches == 0` → 신뢰
- 아니면 재처리 또는 사람 확인

## API 변경

### `POST /convert`
- 기존: `file` 파라미터만
- 변경: `file` + `route` 쿼리 파라미터 (optional, `extract` | `vlm`)
- `route` 미지정 시 자동 감지 (기존 로직)

### `POST /batch`
- 동일하게 `route` 쿼리 파라미터 추가 (배치 내 모든 파일에 동일 적용)

## 환경변수 추가

```
VLM_BATCH_SIZE=5    # semantic 배치당 페이지 수
```

## 파일 변경 요약

| 파일 | 변경 |
|------|------|
| `config.py` | `vlm_batch_size: int = 5` 추가 |
| `router.py` | PPTX를 VLM으로 이동, `route` 파라미터 지원 |
| `vlm.py` | `process_page` → `process_batch` (멀티 이미지 + semantic), `process_document` 배치 청크 |
| `worker.py` | PPTX일 때 `pptx_to_pdf` → `pdf_to_images` → VLM |
| `extractors/office.py` | 신규 — LibreOffice headless 래퍼 |
| `extractors/__init__.py` | PPTX extractor 제거 |
| `app.py` | `route` 쿼리 파라미터 추가 |
| `models.py` | Quality에 `total_batches`, `failed_batches`, `method` 추가 |
| `.env.example` | `VLM_BATCH_SIZE=5` 추가 |
| `Dockerfile` | `libreoffice-core` 설치 추가 |

## 스코프 외

- DOCX VLM 경로 (필요시 추후)
- 중간 진행 상태 조회
- 프롬프트 커스터마이징
- 변환 결과 캐싱
