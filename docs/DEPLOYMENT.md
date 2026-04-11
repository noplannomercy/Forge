# Forge 배포/운영 매뉴얼

> 최종 업데이트: 2026-04-11
> 대상: Forge(Document Converter) + Cortex(RAG) 연계 환경

---

## 1. 아키텍처 개요

```
[업로더(직원/시스템)]
        │
        ▼
┌──────────────┐
│  S3 (원본)   │  ← 단일 진실 공급원 (미구현, n8n 경유 예정)
└──────┬───────┘
       │ n8n 오케스트레이터 (미구현)
       ▼
┌──────────────┐   callback    ┌──────────────┐
│    Cortex    │ ◄──────────── │    Forge     │
│  (port 9000) │ ─────────────►│  (port 8003) │
└──────┬───────┘   위임        └──────┬───────┘
       │                              │
       └──────────────┬───────────────┘
                      ▼
            ┌──────────────────┐
            │  Postgres + Redis │
            │  (RDS/ElastiCache │
            │   in prod)        │
            └──────────────────┘
```

**책임 분리:**
- **Forge**: 파일 → 마크다운 변환 (extract 또는 VLM semantic) + 메타 자동 추출
- **Cortex**: 마크다운 청킹 + 임베딩 + 검색 + 그래프(AGE)
- **infra**: Postgres(pgvector+AGE) + Redis (로컬에서만 compose, AWS는 관리형 서비스)

---

## 2. 환경별 실행 가이드

Forge는 3가지 모드로 실행 가능:

| 모드 | 언제 쓰나 | DB | Cortex 연동 |
|------|----------|----|-----|
| **로컬 호스트** | 개발자 혼자 디버깅 | 외부 Postgres (로컬/원격) 또는 InMemory | 수동 callback URL |
| **Docker 단독** | 격리된 환경에서 Forge만 | 외부 Postgres 필수 | 수동 callback URL |
| **Docker integration** | Cortex와 통합 테스트 | infra compose의 Postgres (서비스명) | 서비스명 기반 자동 |

### 2.1 로컬 호스트 모드

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. LibreOffice (PPTX 경로 쓸 때만)
# Windows: winget install TheDocumentFoundation.LibreOffice
# Linux: apt install libreoffice-impress

# 3. .env 준비
cp .env.example .env
# VLM_URL, VLM_MODEL, VLM_API_KEY, DATABASE_URL 채우기

# 4. 기동
uvicorn app:app --port 8003
```

### 2.2 Docker 단독 모드

```bash
# 1. .env 준비 (로컬과 동일, DATABASE_URL은 host.docker.internal:<PORT> 사용)
cp .env.example .env
# DATABASE_URL=postgresql://user:pass@host.docker.internal:5432/forge

# 2. 빌드 + 기동
docker compose up -d

# 3. 로그 확인
docker compose logs -f forge

# 4. 정리
docker compose down
```

### 2.3 Docker integration 모드 (Cortex + infra 통합)

**디렉토리 구조 전제:**
```
workspace/
├── infra/                              ← Postgres + Redis
│   └── docker-compose.yml
├── cortex/                             ← Cortex (포트 9000)
│   └── docker-compose.integration.yml
└── Forge/                              ← Forge (포트 8003)
    └── docker-compose.integration.yml
```

**실행 순서:**
```bash
# 0. 네트워크 생성 (최초 1회)
docker network create hc-rag-network 2>/dev/null || true

# 1. infra 기동 (Postgres pgvector+AGE, Redis)
cd workspace/infra
docker compose up -d
# 확인: docker ps --filter name=hc-rag

# 2. Cortex 기동
cd ../cortex
docker compose -f docker-compose.integration.yml up -d

# 3. Forge 기동
cd ../Forge
docker compose -f docker-compose.integration.yml up -d

# 4. 헬스체크
curl http://localhost:9000/v1/health  # Cortex
curl http://localhost:8003/health     # Forge
```

**정리 순서 (역순 권장):**
```bash
cd Forge && docker compose -f docker-compose.integration.yml down
cd ../cortex && docker compose -f docker-compose.integration.yml down
cd ../infra && docker compose down
# 데이터까지 날리려면: docker compose down -v
```

### 2.4 Docker 파일 상세 가이드

#### 2.4.1 Dockerfile — 이미지 빌드 레시피

```dockerfile
FROM python:3.11-slim
```
베이스 이미지. Python 3.11이 깔린 경량 리눅스(Debian).

```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libreoffice-impress \
        libreoffice-core \
        curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
```
시스템 패키지 설치:
- `libreoffice-impress` + `libreoffice-core` — PPTX→PDF 변환에 필요 (이미지 크기 ~800MB의 주범)
- `curl` — healthcheck에서 `/health` 호출할 때 사용
- 마지막 줄은 apt 캐시 정리 (이미지 크기 절약)

```dockerfile
RUN groupadd --system forge && useradd --system --gid forge --create-home forge
```
보안용 non-root 사용자 생성. 컨테이너가 침해당해도 시스템 권한 없음.

```dockerfile
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
```
Python 패키지 설치. `requirements.txt`를 **먼저** 복사해서 설치하는 이유: 코드만 바꿨을 때 이 레이어가 캐시돼서 빌드가 빠름 (레이어 캐시 최적화).

```dockerfile
COPY --chown=forge:forge . .
USER forge
```
앱 코드를 forge 유저 소유로 복사하고, 이후 모든 실행은 forge 유저. `.dockerignore`에 의해 `.env`, `tests/`, `docs/`, `.git/` 등은 복사에서 제외됨.

```dockerfile
EXPOSE 8003
```
포트 문서화. 실제 포트 매핑은 docker-compose에서 수행.

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8003/health || exit 1
```
Docker가 30초마다 `/health` 호출하여 컨테이너 생존 체크. 기동 후 20초는 유예. 3회 연속 실패 시 `unhealthy` 상태.

```dockerfile
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003"]
```
컨테이너 시작 명령. uvicorn으로 FastAPI 앱 기동.

#### 2.4.2 .dockerignore — 이미지에 포함하지 않는 파일

`.env`(API 키 등 비밀), `tests/`, `docs/`, `.git/`, `__pycache__/` 등 런타임에 불필요하거나 보안상 위험한 파일을 이미지에서 제외.

**특히 중요:** `.env`가 이미지에 들어가면 API 키가 이미지에 박혀서 ECR 등에 푸시될 때 노출됨. `.dockerignore`가 이를 방지.

#### 2.4.3 docker-compose.yml — Forge 단독 실행

```yaml
services:
  forge:
    build: .              # 현재 디렉토리의 Dockerfile로 빌드
    image: forge:latest   # 빌드된 이미지 이름 태깅
    container_name: forge # 컨테이너 이름 고정
    ports:
      - "8003:8003"       # 호스트 8003 → 컨테이너 8003 매핑
    env_file:
      - .env              # .env를 환경변수로 주입 (이미지에는 없지만 실행 시 읽음)
    restart: unless-stopped  # 크래시 시 자동 재시작, 수동 stop은 존중
    healthcheck: ...      # Dockerfile의 HEALTHCHECK와 동일
```

외부에 DB가 이미 떠있는 상황을 가정. `.env`의 `DATABASE_URL`에 `host.docker.internal:<PORT>` 사용.

#### 2.4.4 docker-compose.integration.yml — Cortex 통합 실행

단독 compose와 차이점 2가지:

**1) `environment:` 블록으로 DATABASE_URL override:**
```yaml
env_file:
  - .env              # 먼저 .env 읽음 (VLM_URL, API_KEY 등)
environment:
  DATABASE_URL: postgresql://hc:hc_dev@postgres:5432/hc_rag  # .env 값을 덮어씀
```
`.env`의 `DATABASE_URL`은 `localhost:5556`(로컬 개발용)이지만, integration에서는 DB가 `postgres`라는 서비스명의 컨테이너에 있으므로 override. `environment:`가 `env_file:`보다 우선.

**2) 공유 네트워크 `hc-rag-network`:**
```yaml
networks:
  - hc-rag-network        # 이 네트워크에 참여

networks:
  hc-rag-network:
    external: true        # compose가 만드는 게 아니라 기존 네트워크 참조
```
같은 네트워크에 있으면 서비스명이 DNS처럼 작동:
- `forge → http://postgres:5432` (DB 접근)
- `forge → http://cortex:9000` (callback)
- `cortex → http://forge:8003` (변환 위임)

#### 2.4.5 네트워크 아키텍처 — 3개 compose가 1개 네트워크 공유

```
docker network create hc-rag-network
         │
    ┌────┴──────────────────────────────────┐
    │          hc-rag-network               │
    │                                       │
    │  ┌─────────┐  infra compose           │
    │  │postgres │  (5432)                  │
    │  │redis    │  (6379)                  │
    │  └─────────┘                          │
    │                                       │
    │  ┌─────────┐  cortex compose          │
    │  │cortex   │  (9000)                  │
    │  └─────────┘                          │
    │                                       │
    │  ┌─────────┐  forge compose           │
    │  │forge    │  (8003)                  │
    │  └─────────┘                          │
    │                                       │
    └───────────────────────────────────────┘
```

핵심: `localhost` 를 사용하지 않고 **서비스명(DNS alias)** 으로 통신. AWS 이관 시 Cloud Map 서비스 디스커버리로 1:1 매핑됨.

#### 2.4.6 자주 쓰는 Docker 명령어

```bash
# 이미지 빌드 (코드 바꿨을 때)
docker compose build

# 빌드 + 기동 (백그라운드)
docker compose up -d

# 로그 실시간 확인
docker compose logs -f forge

# 컨테이너 안에서 디버깅
docker exec -it forge bash

# 컨테이너 상태 확인
docker ps --format "{{.Names}}\t{{.Status}}"

# DB 직접 쿼리 (integration 모드)
docker exec hc-rag-postgres psql -U hc -d hc_rag -c "SELECT COUNT(*) FROM forge_jobs"

# 이미지 다시 빌드 후 교체
docker compose up -d --build

# 정지 + 컨테이너 삭제
docker compose down

# 정지 + 컨테이너 + 볼륨(데이터) 삭제
docker compose down -v

# integration 모드 실행 (파일 지정)
docker compose -f docker-compose.integration.yml up -d
docker compose -f docker-compose.integration.yml down
```

---

## 3. 환경변수 체크리스트

### 필수 (Forge)

| 변수 | 용도 | 로컬 예시 | integration 예시 |
|------|------|----------|-------------------|
| `VLM_URL` | VLM API 엔드포인트 | `https://openrouter.ai/api/v1/chat/completions` | 동일 |
| `VLM_MODEL` | VLM 모델명 | `google/gemini-2.0-flash-001` | 동일 |
| `VLM_API_KEY` | VLM API 키 | OpenRouter 키 | 동일 |
| `DATABASE_URL` | Postgres DSN | `postgresql://postgres:pass@localhost:5556/forge` | `postgresql://hc:hc_dev@postgres:5432/hc_rag` |
| `CALLBACK_API_KEY` | Cortex callback 시 X-API-Key 값 | `test` | `test` (Cortex와 일치) |

### 선택

| 변수 | 기본값 | 용도 |
|------|--------|------|
| `VLM_TIMEOUT` | 120 | VLM 호출 타임아웃(초) |
| `VLM_CONCURRENCY` | 3 | VLM 동시 호출 제한 |
| `VLM_BATCH_SIZE` | 5 | semantic 배치당 페이지 수 |
| `PORT` | 8003 | 서버 포트 |
| `MAX_FILE_SIZE` | 104857600 | 업로드 최대 크기 (100MB) |
| `META_LLM_URL` | (빈값→VLM) | 메타 추출 LLM 별도 지정 시 |
| `META_LLM_MODEL` | (빈값→VLM) | 메타 추출 모델 |
| `META_LLM_API_KEY` | (빈값→VLM) | 메타 추출 키 |
| `FORGE_API_KEY` | (빈값→비활성) | 관리 API (`/jobs`, `/stats`) 인증 키 |

### integration 모드 override

`docker-compose.integration.yml` 의 `environment:` 블록에서 `.env` 값을 덮어쓴다:
```yaml
environment:
  DATABASE_URL: postgresql://hc:hc_dev@postgres:5432/hc_rag
```

이유: `.env`는 로컬 개발용(`localhost`), integration은 서비스명(`postgres`) 기반이라 분리가 필요함.

---

## 4. Cortex 연동 URL 매트릭스

환경별 callback_url 패턴:

| 환경 | Cortex → Forge 호출 | Forge → Cortex callback |
|------|---------------------|------------------------|
| **로컬 (양쪽 host)** | `http://localhost:8003/convert` | `?callback_url=http://localhost:9000/v1/ingest` |
| **Docker (공통 network)** | `http://forge:8003/convert` | `?callback_url=http://cortex:9000/v1/ingest` |
| **Docker (분리)** | `http://host.docker.internal:8003/convert` | `?callback_url=http://host.docker.internal:9000/v1/ingest` |
| **AWS ECS** | `http://forge.internal:8003/convert` (Cloud Map) | `?callback_url=http://cortex.internal:9000/v1/ingest` |

**핵심:** Forge는 자기 URL을 모른다. Cortex가 호출 시 쿼리파라미터로 "어디로 콜백해달라"를 넘겨준다.

---

## 5. DB 스키마 관리

### 현재 방식: Startup auto-apply

각 앱이 기동 시 자기 스키마를 `CREATE IF NOT EXISTS` 로 생성한다.

- **Forge**: `app.py` lifespan → `_apply_schema(pool)` → `schema.sql` 실행
- **Cortex**: lifespan → `init.sql`, `metadata_migration.sql`, `ops_migration.sql` 실행

**장점:**
- 배포 시 수동 `psql -f schema.sql` 불필요
- 볼륨 날려도 다음 기동에 자동 복구
- infra만 먼저 띄우고 Cortex/Forge 기동 순서로 깔끔하게 초기화

**공유 DB 전략:**
- 같은 `hc_rag` 데이터베이스에 양쪽 테이블 공존
- Forge: `forge_jobs`, `forge_vlm_logs`, `forge_prompts` (전부 `forge_` prefix)
- Cortex: `documents`, `document_metadata`, `document_sources`, `memories`, `edge_occurrence`, `domain_rules`, `search_logs`, `cortex_graph` (AGE)
- Prefix 분리로 충돌 없음

---

## 6. 인증

### 관리 API (`/jobs`, `/stats`, `/prompts`)
- `X-Forge-Key` 헤더 필수
- `.env`의 `FORGE_API_KEY` 설정 시 활성화, 빈 값이면 완전 비활성화

### Callback 인증 (Cortex 방향)
- Forge가 callback POST 시 `X-API-Key: {CALLBACK_API_KEY}` 헤더 추가
- Cortex의 `CORTEX_API_KEY` 와 값이 같아야 200 반환
- 로컬/개발에서는 양쪽 `test` 기본값 사용 (integration compose에 박혀있음)
- 프로덕션에서는 AWS Secrets Manager로 같은 값 주입

---

## 7. 하드코딩 튜닝 포인트

코드에 고정된 값들 (필요 시 env화):

| 위치 | 값 | 영향 |
|------|----|----|
| `vlm.py:67` | `max_tokens: 4096` | VLM 배치당 출력 토큰 (긴 문서 짤림 주의) |
| `meta.py:18` | `MAX_INPUT_CHARS = 3000` | 메타 추출 입력 길이 (긴 문서는 앞부분만 반영) |
| `meta.py:30` | `timeout=60` | 메타 LLM 타임아웃 |
| `meta.py:40` | `max_tokens: 1024` | 메타 LLM 출력 |
| `worker.py:24` | `timeout=30` | callback POST 타임아웃 |
| `worker.py:18` | `CALLBACK_RETRIES = 3` | callback 재시도 |
| `worker.py:19` | `CALLBACK_DELAYS = [1, 2, 4]` | callback 백오프 |
| `vlm.py:10-11` | `MAX_RETRIES = 3`, `RETRY_DELAYS = [1, 2, 4]` | VLM 호출 재시도 (S2 준수사항) |

현재 YAGNI로 고정. 운영 중 문제 발견 시 env화 고려.

---

## 8. AWS 이관 시나리오

### 최소 마이그레이션 경로

| 로컬 컴포넌트 | AWS 대체 | 비고 |
|---------------|----------|------|
| `infra/` compose | RDS (Postgres pgvector+AGE) + ElastiCache Redis | Cortex가 주로 사용, Forge는 RDS만 |
| `hc-rag-network` | VPC + Cloud Map 서비스 디스커버리 | service name → `forge.internal`, `cortex.internal` |
| Cortex docker-compose.integration.yml | ECS Task Definition | 같은 환경변수 구조 유지 |
| Forge docker-compose.integration.yml | ECS Task Definition | 동일 |
| `.env` 시크릿 | AWS Secrets Manager | VLM_API_KEY, DATABASE_URL, CALLBACK_API_KEY |
| stdout 로그 | CloudWatch Logs | 자동 수집 |

### ECS 배포 개요
1. 이미지를 ECR에 push (`forge:latest`, `cortex:latest`)
2. RDS 인스턴스 생성 (pgvector + AGE 확장 설치된 Postgres)
3. VPC + 서브넷 + Cloud Map 네임스페이스 `hc-rag.local` 등록
4. ECS 서비스 2개 생성 (cortex, forge) — Cloud Map 연결
5. ALB 앞단에 Cortex 라우팅 (Forge는 내부 전용)
6. Secrets Manager에서 환경변수 주입
7. ECS task 자체에 healthcheck 이미 달려있음 (Dockerfile HEALTHCHECK)

### 주의점
- **LibreOffice 컨테이너 크기**: Forge 이미지 ~879MB. Fargate에서 무방하지만 cold start 10~20초 예상.
- **VLM 호출 비용**: OpenRouter 요금 실시간 모니터링 필요. `vlm_log_store`에 토큰/비용 기록하는 구조 이미 있음 (`forge_vlm_logs`).
- **S3 연동 미구현**: 현재는 multipart 업로드만. S3 경로 기반 엔드포인트는 향후 추가 예정 (`/convert/url`).

---

## 9. 트러블슈팅

### "8003 포트 이미 사용중"
로컬 호스트에 Forge uvicorn이 떠있거나, 이전 컨테이너 잔재.
```bash
# Windows
powershell -Command "Get-NetTCPConnection -LocalPort 8003 -State Listen"
# 프로세스 ID 확인 후 Stop-Process -Id <PID> -Force
```

### "DATABASE_URL 잘못됨"
컨테이너 안에서 `localhost`는 컨테이너 자기 자신이다. 외부 DB 접근 시:
- Docker 단독: `host.docker.internal:<PORT>` (Windows/Mac) 또는 `--add-host=host.docker.internal:host-gateway` (Linux)
- Docker integration: infra compose의 서비스명 `postgres:5432`

### "callback 401 Unauthorized"
- Forge `.env`의 `CALLBACK_API_KEY` 와 Cortex `CORTEX_API_KEY` 가 **정확히 같아야** 함
- 공백/줄바꿈 확인

### "schema.sql 안 적용"
- Forge는 startup 로그에 `schema.sql applied successfully` 찍힘
- 안 찍히면 `DATABASE_URL` 비어있거나(InMemory 모드) 연결 실패
- 확인: `docker exec <container> python -c "from config import Config; print(Config().database_url)"`

### "LibreOffice 변환 실패 (PPTX)"
- 컨테이너 안: `docker exec forge which soffice` 로 `/usr/bin/soffice` 확인
- 로그: `LibreOffice conversion failed` → `libreoffice-impress` 패키지 누락 의심
- Dockerfile에 `libreoffice-impress` 반드시 설치됨 (libreoffice-core만으로는 PPTX 안 됨)

### "VLM 전부 실패"
- `VLM_API_KEY` 확인
- `VLM_URL` 접근 가능한지 (방화벽, 프록시)
- `docker logs forge | grep "Callback attempt"` 또는 `"[변환 실패"`

---

## 10. 운영 체크리스트 (배포 전)

- [ ] `.env` 에 실제 VLM 키 / DB URL / CALLBACK_API_KEY 세팅
- [ ] `docker build` 성공 확인
- [ ] `docker compose up -d` 로 컨테이너 기동 후 `/health` 200 응답
- [ ] DB 연결 확인 (`forge_jobs` 테이블 존재)
- [ ] 실제 DOCX 1개 업로드 → 변환 완료 확인
- [ ] 실제 PPTX 1개 업로드 → LibreOffice 변환 + VLM 호출 확인 (비용 주의)
- [ ] Cortex 연동 테스트 (`POST /v1/ingest/file` → 청크 생성 확인)
- [ ] 메타 추출 결과 확인 (`meta->>'category'`)
- [ ] 로그에 `WARNING`/`ERROR` 없는지 확인
- [ ] 컨테이너 재시작 후에도 정상 기동 (`docker compose restart`)
