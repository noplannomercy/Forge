# Forge 환경변수 설정 가이드

> 이 문서는 `.env` 파일의 모든 환경변수를 하나씩 설명하고,
> 시나리오별(로컬 Ollama / OpenRouter / Bedrock / 사내 vLLM) 설정 예시를 제공한다.

---

## 설정 구조

Forge의 설정은 `.env` 파일 하나로 관리된다.

```
.env           실제 설정값 (git에 올리지 않음, .gitignore 대상)
.env.example   템플릿 (git에 올림, 플레이스홀더 값)
config.py      .env → Python 객체 변환 (pydantic-settings)
```

### 우선순위

```
시스템 환경변수  >  .env 파일  >  코드 기본값 (config.py)
```

Docker compose의 `environment:` 블록은 시스템 환경변수로 주입되므로 `.env`보다 우선.
이 원리로 integration compose에서 `DATABASE_URL`을 override한다.

### 설정이 적용되는 시점

서버 기동 시 `Config()` 객체가 한 번 생성되며, 이때 `.env`를 읽는다.
런타임에 `.env`를 수정해도 반영되지 않는다. **서버 재시작 필요.**

---

## 환경변수 전체 목록

### VLM (비전 언어 모델)

```env
VLM_URL=http://localhost:11434/v1/chat/completions
```
**VLM API 엔드포인트 주소.**

OpenAI-compatible `/v1/chat/completions` 형식을 지원하는 서버면 뭐든 된다.
기본값은 로컬 Ollama 주소. 실제 환경에서는 반드시 변경.

| 환경 | 값 |
|------|-----|
| 로컬 Ollama | `http://localhost:11434/v1/chat/completions` |
| OpenRouter | `https://openrouter.ai/api/v1/chat/completions` |
| 사내 vLLM | `http://10.0.1.50:8000/v1/chat/completions` |
| API Gateway+Bedrock | `https://xxx.execute-api.ap-northeast-2.amazonaws.com/v1/chat/completions` |
| LiteLLM 프록시 | `http://litellm:4000/v1/chat/completions` |

---

```env
VLM_MODEL=qwen2-vl:7b
```
**VLM 모델명.** API 요청의 `"model"` 필드에 들어가는 값.

| 환경 | 값 |
|------|-----|
| 로컬 Ollama | `qwen2-vl:7b` |
| OpenRouter | `google/gemini-2.0-flash-001` |
| 사내 vLLM | `Qwen/Qwen2-VL-7B-Instruct` |
| Bedrock (API GW) | `gpt-4o` 또는 `anthropic.claude-3-5-sonnet` |

---

```env
VLM_API_KEY=
```
**VLM API 인증 키.** 요청 헤더 `Authorization: Bearer {이 값}`으로 전송.

빈 값이면 Authorization 헤더를 아예 안 붙인다 (Ollama는 키 불필요).
OpenRouter는 `sk-or-v1-xxx`, API Gateway는 Gateway API Key.

---

```env
VLM_TIMEOUT=120
```
**VLM 호출 타임아웃 (초).** 기본 120초(2분).

큰 배치(이미지 5장)는 1분 이상 걸릴 수 있다. 너무 짧으면 타임아웃 실패 증가.
너무 길면 장애 시 감지가 느려진다. 120초가 적정값.

---

```env
VLM_CONCURRENCY=3
```
**VLM 동시 호출 수.** Semaphore로 제한.

64페이지 PDF → 13배치인데, 동시에 3개만 VLM에 보낸다.
나머지는 대기. API rate limit이나 서버 과부하를 방지한다.

올리면: 처리 속도 빨라짐, 서버/API 부하 증가.
줄이면: 안정적이지만 느림.

---

```env
VLM_BATCH_SIZE=5
```
**VLM 한 번 호출에 보낼 페이지 수.** 기본 5장.

64페이지 PDF → ceil(64/5) = 13배치.
올리면: 호출 횟수 감소, 한 번에 보내는 이미지 많아져서 토큰 비용 증가 + 타임아웃 위험.
줄이면: 호출 횟수 증가, 안정적이지만 느리고 오버헤드 증가.

---

### 서버

```env
HOST=0.0.0.0
```
**서버 바인딩 주소.** `0.0.0.0`이면 모든 네트워크 인터페이스에서 접근 가능.
Docker 컨테이너에서는 반드시 `0.0.0.0` (아니면 외부에서 접근 불가).

---

```env
PORT=8003
```
**서버 포트.** Forge 전용. Cortex는 9000.

---

```env
MAX_FILE_SIZE=104857600
```
**업로드 최대 파일 크기 (바이트).** 기본 100MB (104,857,600 bytes).
초과하면 HTTP 413 반환. 메모리에서 처리하므로 너무 크면 OOM 위험.

---

### 데이터베이스

```env
DATABASE_URL=
```
**PostgreSQL 연결 문자열.** 형식: `postgresql://USER:PASS@HOST:PORT/DBNAME`

| 상황 | 값 |
|------|-----|
| 빈 값 | InMemoryJobStore 사용 (서버 끄면 데이터 사라짐) |
| 로컬 개발 | `postgresql://postgres:postgres@localhost:5556/graphrag` |
| Docker integration | `postgresql://hc:hc_dev@postgres:5432/hc_rag` (compose가 override) |
| AWS RDS | `postgresql://hc:xxx@rds-endpoint.ap-northeast-2.rds.amazonaws.com:5432/hc_rag` |

InMemory는 개발/테스트 편의용. 프로덕션에서는 반드시 PostgreSQL.

---

### 메타 추출 LLM

```env
META_LLM_URL=
META_LLM_MODEL=
META_LLM_API_KEY=
```
**메타데이터 추출 전용 LLM 설정.** 셋 다 비면 VLM 설정을 fallback으로 사용.

왜 분리했나: VLM은 비전 모델(이미지 처리, 비쌈). 메타 추출은 텍스트만 처리하므로
저렴한 텍스트 전용 모델을 쓸 수 있다.

| 시나리오 | META_LLM_URL | META_LLM_MODEL |
|----------|-------------|----------------|
| VLM과 동일 모델 | (빈값) | (빈값) |
| 저렴한 모델 분리 | OpenRouter URL | `openai/gpt-4o-mini` |
| 사내 별도 서버 | `http://10.0.1.51:8000/...` | `Qwen/Qwen2.5-7B-Instruct` |

---

### 인증

```env
FORGE_API_KEY=
```
**관리 API 인증 키.** `/jobs`, `/stats`, `/prompts` 등 관리 엔드포인트 접근 시 필요.
요청 헤더: `X-Forge-Key: {이 값}`

빈 값이면 관리 API가 완전히 비활성화된다 (404 반환).
프로덕션에서는 반드시 설정 권장.

---

```env
CALLBACK_API_KEY=
```
**callback POST 시 X-API-Key 헤더 값.**

Forge가 변환 완료 후 Cortex에 callback을 보낼 때 이 값을 `X-API-Key` 헤더에 붙인다.
Cortex의 `CORTEX_API_KEY`와 동일해야 인증이 통과된다.

```
Forge callback POST:
  Header: X-API-Key: {CALLBACK_API_KEY}

Cortex ingest 수신:
  검증: X-API-Key == CORTEX_API_KEY ?
```

양쪽 `.env`에 같은 값을 넣어야 한다. 로컬/개발 기본값: `test`.

---

## 시나리오별 .env 예시

### 시나리오 1: 로컬 Ollama (무료, 오프라인)

```env
VLM_URL=http://localhost:11434/v1/chat/completions
VLM_MODEL=qwen2-vl:7b
VLM_API_KEY=
DATABASE_URL=
```

기본값 그대로. `.env` 파일 없어도 동작 (InMemory 모드).
`ollama pull qwen2-vl:7b` 로 모델만 받으면 됨.

---

### 시나리오 2: OpenRouter (클라우드, 유료)

```env
VLM_URL=https://openrouter.ai/api/v1/chat/completions
VLM_MODEL=google/gemini-2.0-flash-001
VLM_API_KEY=sk-or-v1-xxx
DATABASE_URL=postgresql://postgres:postgres@localhost:5556/graphrag
CALLBACK_API_KEY=test
FORGE_API_KEY=my-admin-key
```

현재 개발 환경에서 사용 중인 구성.

---

### 시나리오 3: AWS Bedrock + API Gateway

```env
VLM_URL=https://xxx.execute-api.ap-northeast-2.amazonaws.com/v1/chat/completions
VLM_MODEL=gpt-4o
VLM_API_KEY=api-gateway-key-xxx
DATABASE_URL=postgresql://hc:xxx@rds-endpoint:5432/hc_rag
CALLBACK_API_KEY=production-secret
FORGE_API_KEY=admin-secret

META_LLM_URL=https://xxx.execute-api.ap-northeast-2.amazonaws.com/v1/chat/completions
META_LLM_MODEL=gpt-4o-mini
META_LLM_API_KEY=api-gateway-key-xxx
```

API Gateway가 SigV4 인증을 처리하므로 Forge는 일반 API Key만 사용.
메타 추출은 저렴한 gpt-4o-mini로 분리.

---

### 시나리오 4: 사내 폐쇄망 vLLM

```env
VLM_URL=http://10.0.1.50:8000/v1/chat/completions
VLM_MODEL=Qwen/Qwen2-VL-7B-Instruct
VLM_API_KEY=
DATABASE_URL=postgresql://hc:hc_dev@10.0.1.100:5432/hc_rag
CALLBACK_API_KEY=internal-secret

META_LLM_URL=http://10.0.1.51:8000/v1/chat/completions
META_LLM_MODEL=Qwen/Qwen2.5-7B-Instruct
META_LLM_API_KEY=
```

외부 인터넷 불필요. VLM과 메타 LLM을 사내 GPU 서버에서 각각 운영.

---

### 시나리오 5: LiteLLM 프록시 (Bedrock 비전 지원)

```env
VLM_URL=http://litellm:4000/v1/chat/completions
VLM_MODEL=forge-vlm
VLM_API_KEY=dummy
DATABASE_URL=postgresql://hc:hc_dev@postgres:5432/hc_rag
CALLBACK_API_KEY=test

META_LLM_URL=http://litellm:4000/v1/chat/completions
META_LLM_MODEL=forge-meta
META_LLM_API_KEY=dummy
```

LiteLLM이 Bedrock/Azure/OpenAI 등 다양한 백엔드를 OpenAI 형식으로 래핑.
`forge-vlm`, `forge-meta`는 LiteLLM config에서 정의한 모델 alias.

---

## 설정 변경 반영 방법

| 실행 모드 | 방법 |
|-----------|------|
| 로컬 호스트 | `.env` 수정 → 서버 재시작 (Ctrl+C → `uvicorn app:app`) |
| Docker 단독 | `.env` 수정 → `docker compose restart` |
| Docker integration | `.env` 수정 → `docker compose -f docker-compose.integration.yml restart` |

`docker compose restart`는 컨테이너를 재생성하지 않고 프로세스만 재시작한다.
환경변수가 완전히 바뀌려면 `docker compose down && docker compose up -d` 권장.
