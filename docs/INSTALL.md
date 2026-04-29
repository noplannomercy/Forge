# Forge 설치 매뉴얼

> 포트: 8003 | 역할: PDF, DOCX, PPTX, XLSX, HWPX, 이미지 → Markdown 변환 비동기 서비스

---

## 1. 사전 조건

- Docker, Docker Compose 설치
- 외부 PostgreSQL 접근 가능 (Hostinger DB)
- OpenAI-compatible VLM API 키 (이미지/PPTX 변환에 필요)

---

## 2. 설치

```bash
# 1. 클론
git clone https://github.com/noplannomercy/Forge.git
cd Forge

# 2. 환경변수 설정
cp .env.example .env
vi .env
```

### .env 필수 항목

| 변수 | 필수 | 설명 |
|------|------|------|
| `DATABASE_URL` | ✓ | Hostinger PostgreSQL DSN |
| `VLM_URL` | ✓ | VLM API 엔드포인트 |
| `VLM_MODEL` | ✓ | 모델명 |
| `VLM_API_KEY` | ✓ | VLM API 키 |
| `CALLBACK_API_KEY` | | 콜백 수신 서비스(Pylon 등)의 API 키 |
| `FORGE_API_KEY` | | 관리 API 인증 키 (미설정 시 비활성) |
| `DOCLING_SERVE_URL` | | Docling 서버 URL (미설정 시 pypdfium2 fallback) |

```bash
# 3. 빌드 + 기동
docker compose up -d --build

# 4. 헬스체크
curl http://localhost:8003/health
# 예상: {"status":"ok"}
```

> DB 스키마(`forge_jobs` 등)는 기동 시 자동 생성됨 (CREATE IF NOT EXISTS).
> LibreOffice는 이미지에 포함되어 있음 — 별도 설치 불필요.

---

## 3. 주요 명령어

```bash
# 로그 확인
docker compose logs -f forge

# 재시작
docker compose restart forge

# 재빌드 후 교체
docker compose up -d --build

# 정지
docker compose down
```

---

## 4. 트러블슈팅

| 증상 | 원인 | 조치 |
|------|------|------|
| PPTX 변환 실패 | LibreOffice 오류 | `docker exec forge which soffice` 확인 |
| VLM 호출 실패 | API 키/URL 오류 | `VLM_API_KEY`, `VLM_URL` 확인 |
| DB 연결 실패 | DSN 오류 | `DATABASE_URL` 확인 |
| 콜백 401 | API 키 불일치 | `CALLBACK_API_KEY` ↔ Pylon의 `FORGE_API_KEY` 일치 확인 |

---

## 5. 상세 매뉴얼

운영/배포 전반에 대한 상세 내용은 [`DEPLOYMENT.md`](DEPLOYMENT.md) 참조.
