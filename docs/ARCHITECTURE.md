# Forge 아키텍처

> 이 문서는 Forge의 전체 구조, 요청 처리 흐름, 핵심 설계 결정을 설명한다.
> 처음 코드를 접하는 사람이 "이게 뭐고 어떻게 돌아가는지" 파악하는 것이 목적.

---

## Forge가 하는 일

Forge는 파일을 받아서 마크다운으로 변환하는 REST API 서비스다.

```
입력: PDF, DOCX, PPTX, XLSX, HWPX, JPG/PNG/TIFF/BMP
출력: 구조화된 Markdown 텍스트 + 자동 추출 메타데이터
```

RAG(검색 증강 생성) 파이프라인에서 Forge의 위치:

```
[원본 문서]  →  [Forge: 변환]  →  [Cortex: 청킹+임베딩]  →  [사용자: 검색+질의]
```

원본 문서를 LLM이 이해할 수 있는 텍스트로 바꾸는 첫 번째 단계를 담당한다.
Cortex(포트 9000)와 완전 독립. 같은 DB를 공유하지만 코드 의존성은 0.

---

## 파일 구조

```
Forge/
│
│  [진입점]
├── app.py              FastAPI 앱. 엔드포인트 정의 + 라이프사이클 관리
├── worker.py           비동기 변환 워커. 실제 처리 로직의 중심
├── router.py           "이 파일을 어떻게 처리할까" 결정 (extract vs vlm)
│
│  [외부 호출]
├── vlm.py              VLM(비전 언어 모델) 클라이언트. 이미지 → 마크다운
├── meta.py             메타데이터 자동 추출 (LLM 호출)
│
│  [저장]
├── job_store.py        DB 추상화 (InMemory / PostgreSQL)
├── schema.sql          PostgreSQL 테이블 정의
│
│  [설정/모델]
├── config.py           환경변수 로드 (.env → Python 객체)
├── models.py           데이터 구조 (Job, ConvertResult, Quality 등)
│
│  [관리]
├── admin.py            관리 API (통계, 프롬프트 관리, Job 조회)
├── auth.py             API 키 인증
│
│  [포맷별 추출기]
├── extractors/
│   ├── pdf.py          PDF 텍스트 추출 + 이미지 변환
│   ├── docx.py         DOCX → 마크다운 (텍스트 + 표)
│   ├── pptx.py         PPTX → 마크다운 (extract 경로용)
│   ├── xlsx.py         XLSX → 마크다운 (시트별 표)
│   ├── hwpx.py         HWPX → 마크다운 (ZIP+XML 파싱)
│   ├── image.py        이미지 전처리 (PNG 변환)
│   └── office.py       LibreOffice headless (PPTX→PDF 변환)
│
│  [인프라]
├── Dockerfile
├── docker-compose.yml
├── docker-compose.integration.yml
├── .env.example
└── requirements.txt
```

---

## 핵심 개념: 두 가지 변환 경로

파일이 들어오면 `router.py`가 **extract** 또는 **vlm** 중 하나를 선택한다.
이 결정이 Forge의 가장 중요한 설계 판단이다.

### Extract 경로 (빠르고 무료)

```
대상: DOCX, XLSX, HWPX, 텍스트가 충분한 PDF
방식: Python 라이브러리로 텍스트+표를 직접 추출
비용: 0원 (외부 API 호출 없음)
속도: 수초
```

python-docx가 DOCX를 파싱하고, openpyxl이 XLSX를 파싱하고,
xml.etree가 HWPX를 파싱해서 마크다운으로 변환한다.
텍스트가 정확히 추출되는 포맷에서는 VLM을 돌릴 이유가 없다.

### VLM 경로 (느리지만 똑똑)

```
대상: PPTX, 스캔 PDF, 이미지 (JPG/PNG/TIFF/BMP)
방식: 페이지를 이미지로 만들고 → VLM에 보내서 의미 중심으로 재구성
비용: VLM API 토큰 비용 발생
속도: 수십초 ~ 수분 (페이지 수에 비례)
```

PPTX는 이미지/도표 위주라 텍스트 추출로는 의미 있는 결과가 안 나온다.
스캔 PDF도 마찬가지 (텍스트 레이어 없음).
이런 문서는 페이지를 이미지로 렌더링한 후 VLM이 "이 이미지를 보고 마크다운으로 재구성"한다.

### PDF의 경로 자동 판별

PDF만 특수하다. 텍스트가 있을 수도 있고 없을 수도 있어서.

```python
# router.py의 판별 로직
chars = extract_text_chars(pdf_bytes)
chars_per_mb = chars / (file_size_mb)

if chars_per_mb >= 100:
    route = "extract"    # 텍스트 충분 → 추출
else:
    route = "vlm"        # 스캔본 → VLM
```

100 chars/MB 미만이면 스캔본으로 간주한다.
사용자가 `?route=vlm` 또는 `?route=extract`로 강제 지정할 수도 있다.

### 경로 매핑 전체

| 포맷 | 기본 경로 | 방식 |
|------|----------|------|
| DOCX | extract | python-docx 텍스트+표 |
| XLSX | extract | openpyxl 시트별 표 |
| HWPX | extract | ZIP+XML hp:t 텍스트+표 |
| PDF (텍스트) | extract | pypdfium2 텍스트 추출 |
| PDF (스캔) | vlm | pypdfium2 이미지 변환 → VLM semantic |
| PPTX | vlm | LibreOffice → PDF → 이미지 → VLM semantic |
| JPG/PNG/TIFF/BMP | vlm | 이미지 → VLM 직접 |

---

## 요청 처리 흐름

### 1단계: 요청 수신 (app.py)

```
POST /convert -F "file=@문서.docx"
```

1. 파일 bytes 읽기
2. 크기 체크 (100MB 초과 → HTTP 413)
3. `router.detect_route()` 호출 → 포맷 + 경로 결정
4. `store.create()` → Job 생성 (status: queued)
5. `asyncio.create_task(_safe_process(...))` → 백그라운드 처리 시작
6. `{"job_id": "abc", "status": "queued"}` 즉시 반환

핵심: **요청은 즉시 반환된다.** 변환은 백그라운드에서 진행.

### 2단계: 변환 처리 (worker.py)

```
worker.process_job() 이 비동기로 실행됨
```

**Extract 경로:**
1. 포맷별 추출기 호출 (docx.extract, xlsx.extract 등)
2. ConvertResult 생성 (마크다운 텍스트 + Quality 메트릭)
3. DB 저장

**VLM 경로:**
1. 이미지 준비
   - PPTX → LibreOffice로 PDF 변환 → PDF를 이미지로 변환
   - PDF → 직접 이미지로 변환
   - 이미지 → PNG 변환
2. VLM semantic 배치 처리
   - 이미지를 vlm_batch_size(기본 5)장씩 묶음
   - 배치별로 VLM API 호출 (Semaphore로 동시 3개 제한)
   - 실패한 배치는 placeholder 남기고 성공 배치는 보존
3. 배치 결과 조립 → ConvertResult 생성
4. DB 저장

### 3단계: 메타 추출 (meta.py)

변환이 끝나면 (extract든 vlm이든) 결과 텍스트의 앞부분(3000자)을 LLM에 보내서
자동으로 메타데이터를 추출한다.

```
입력: "현대케피코 LLM 거버넌스 제안서 (v0.1) 목표: 폐쇄망 환경에서..."
출력: {
    "category": "LLM 거버넌스",
    "title": "현대케피코 LLM 거버넌스 제안서",
    "summary": "폐쇄망 환경에서 LLM 서비스를 안전하게 운영하기 위한 제안",
    "keywords": ["LLM", "거버넌스", "폐쇄망", "OpenWebUI", "vLLM"]
}
```

코드 배포 없이 프롬프트를 교체할 수 있도록 DB(forge_prompts)에서 프롬프트를 관리한다.

### 4단계: Callback (worker.py)

요청에 `?callback_url=http://cortex:9000/v1/ingest`가 포함돼 있었으면,
변환 완료 후 결과를 자동으로 POST 한다.

```
Forge → POST http://cortex:9000/v1/ingest
{
    "content": "# 제목\n\n본문...",        ← 변환된 마크다운
    "file_name": "문서.docx",
    "domain": "general",                   ← 분류 (쿼리파라미터로 지정)
    "metadata": {"category": "...", ...},  ← 자동 추출 메타
    "pre_converted": true,                 ← Cortex에게 "이미 변환됨" 알림
    "forge_job_id": "abc-123"              ← 추적용
}
```

3회 retry (1초, 2초, 4초 간격). 전부 실패해도 변환 결과 자체는 DB에 보존.

### 5단계: 결과 조회 (app.py)

```
GET /result/abc-123
```

DB에서 Job을 조회해서 status, result(마크다운), meta, error를 반환한다.
`?format=text` 추가하면 Content-Type: text/markdown으로 본문만 반환.

---

## 비동기 처리 모델

Forge는 동기 API가 아니다. "넣고 기다리는" 구조.

```
시간축 →

클라이언트    POST /convert ─── 200 {job_id} ────────── GET /result ── 200 {completed}
                                │                         ▲
서버                            │ create_task             │
                                ▼                         │
워커                        [변환 처리중...]  ──── DB 저장 ┘
                            (수초 ~ 수분)
```

이렇게 한 이유:
- VLM 경로는 수분 걸릴 수 있음 (64페이지 PDF → 13배치 VLM 호출)
- HTTP 요청을 수분간 열어두면 타임아웃, 리소스 낭비
- 비동기면 여러 변환을 동시에 처리 가능

---

## 주요 설계 패턴

### JobStore 추상화

```
JobStore (추상 클래스, ABC)
    ├── InMemoryJobStore   개발/테스트용. 딕셔너리에 저장.
    └── PostgresJobStore   프로덕션. asyncpg로 forge_jobs 테이블 사용.
```

worker.py, app.py는 `store.create()`, `store.get()` 만 호출한다.
DB가 InMemory인지 PostgreSQL인지 모른다.
나중에 Redis나 다른 DB로 바꿔도 새 구현체만 추가하면 된다.

### VLM Semaphore + Retry

```
Semaphore(3)  →  동시에 최대 3개 VLM 호출만 허용
Retry(3회)    →  실패 시 1초 → 2초 → 4초 간격 재시도
부분 실패     →  실패 배치는 placeholder, 성공 배치는 보존
```

64페이지 PDF를 처리할 때 13개 배치가 동시에 VLM을 호출하면
서버가 과부하되거나 rate limit에 걸린다. Semaphore가 이를 방지.

### Fire-and-Forget 안전 래퍼

```python
# 모든 create_task 호출은 _safe_process를 거침
asyncio.create_task(_safe_process(job, file_bytes, ...))
```

asyncio.create_task는 예외가 발생해도 조용히 삼킨다.
_safe_process가 try/except로 감싸서 반드시 로그를 남긴다.
이 래퍼 없이 create_task를 직접 호출하는 것은 금지 (제약 C4).

### 프롬프트 외부화

VLM 프롬프트와 메타 추출 프롬프트를 DB(forge_prompts)에 저장한다.

```
기동 시:    DB에 기본 프롬프트 seed (없으면 생성)
변환 시:    DB에서 active 프롬프트 로드 (캐시됨)
교체 시:    POST /prompts → 새 버전 생성, 기존 비활성화
기록:      어떤 프롬프트 버전으로 변환했는지 forge_vlm_logs에 저장
```

코드 배포 없이 프롬프트 튜닝/교체가 가능하다.

---

## 제약 사항 (CLAUDE.md에서 발췌)

| # | 규칙 | 이유 |
|---|------|------|
| C1 | Cortex 코드 수정 금지 | 완전 독립 서비스 원칙 |
| C2 | DOCX/XLSX/HWPX는 extract, PPTX/이미지는 vlm | 포맷 특성에 맞는 경로 |
| C3 | JobStore 인터페이스 우회 금지 | DB 전환 시 변경 최소화 |
| C4 | create_task는 _safe_process 래퍼 필수 | 예외 삼킴 방지 |
| C5 | API 키/시크릿 하드코딩 금지 | .env 또는 환경변수로 관리 |

---

## 코드 규모

| 구분 | 라인 수 | 파일 수 |
|------|---------|---------|
| 코어 앱 | 1,309 | 10 |
| 추출기 | 444 | 8 |
| 테스트 | 1,929 | 21 (147개 함수) |
| 인프라 (SQL/Docker) | 166 | 4 |

앱 전체 약 1,750줄. 작고 집중된 서비스.
