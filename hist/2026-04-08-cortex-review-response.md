# Cortex 클코 검수 결과 → Forge 대응 (2026-04-08)

## Critical

### 1. 자동 ingest 없음 (push-on-complete)

**Cortex 의견:** Forge 변환 완료 후 Cortex `/v1/ingest`로 push하는 코드 없음. 호출자가 poll → reshape → POST 직접 해야 함.

**Forge 대응: 수용. 하지만 Forge가 할 일이 아닐 수 있음.**

Forge는 "변환 엔진"이지 "Cortex 클라이언트"가 아닙니다. push-on-complete를 Forge에 넣으면 Cortex 의존성이 생기고, CLAUDE.md C1("Cortex 코드 수정 금지, 완전 독립 서비스 원칙")의 역방향 위반입니다.

**3가지 방안:**

| 방안 | 설명 | Forge 의존성 |
|------|------|-------------|
| A) Forge에 callback_url 추가 | `POST /convert?callback_url=http://cortex/v1/ingest` → 완료 시 POST | Cortex 무관, 범용 |
| B) Cortex가 poll | Cortex `ingest/file`에서 Forge `/convert` → poll → `/v1/ingest` | Forge 변경 없음 |
| C) Forge에 CORTEX_URL 하드코딩 | Cortex 의견대로 | **독립성 깨짐 — 비추** |

**추천: A) callback_url.** 범용적이고 Forge 독립성 유지. TODO에 이미 있음. 또는 B)로 Cortex가 주도.

---

### 2. 필드명 불일치 (result.text vs content)

**Cortex 의견:** Forge는 `.result.text`, Cortex는 `content` 필드.

**Forge 대응: 이건 연동 시 호출자가 매핑하는 게 맞음.**

Forge의 응답 스키마(`ConvertResult.text`)는 범용 변환 결과이고, Cortex의 `content`는 Cortex 내부 스키마입니다. Forge가 Cortex 스키마에 맞추면 다른 소비자가 생길 때 또 바꿔야 합니다.

**방안:**
- callback_url 방식이면 Forge가 body를 구성할 때 매핑 가능 (callback payload 커스터마이징)
- Cortex poll 방식이면 Cortex 쪽에서 `response["result"]["text"]` → `content`로 매핑
- 어느 쪽이든 1줄 매핑이라 큰 이슈 아님

---

## Important

### 3. 파일 크기 제한 불일치 (Forge 100MB vs Cortex 50MB)

**Cortex 의견:** Forge에서 100MB 파일 변환 성공해도 Cortex에서 거절.

**Forge 대응: 맞는 지적. 하지만 Forge가 Cortex 제한을 알 필요는 없음.**

Forge는 범용 변환 서비스. Cortex 외에도 다른 소비자가 있을 수 있고, 100MB PDF가 50MB 마크다운이 되지는 않음 (보통 원본보다 훨씬 작음).

**방안:**
- Cortex가 Forge에 파일 보내기 전에 자체 크기 체크 (이미 하고 있을 것)
- 변환 결과(마크다운 텍스트)는 원본보다 훨씬 작으므로 Cortex 50MB 제한에 걸릴 가능성 낮음
- 필요하면 Cortex 제한 올리는 게 맞음 (Forge가 낮출 이유 없음)

---

### 4. PPTX route=extract KeyError

**Cortex 의견:** `?route=extract`로 PPTX 보내면 `extractors/__init__.py`에 pptx 없어서 KeyError.

**Forge 대응: 맞는 버그. 수정 필요.**

v2에서 PPTX를 VLM으로 옮기면서 `EXTRACTORS` dict에서 제거했는데, `?route=extract` 강제 지정 시 fallback이 없음. 두 가지 방안:

| 방안 | 설명 |
|------|------|
| A) PPTX extract 복원 | `extractors/__init__.py`에 pptx extractor 다시 등록. 텍스트만 나오지만 에러는 안 남 |
| B) 400 에러 반환 | router에서 PPTX+extract 조합일 때 "PPTX는 VLM만 지원" 에러 |

**추천: B) 명시적 에러.** PPTX extract는 품질이 안 나오는 걸 수동 테스트로 확인했으므로, 허용하면 안 됨.

---

### 5. 변환 API 인증 없음

**Cortex 의견:** `/convert`, `/batch`에 auth 미적용.

**Forge 대응: 의도된 설계.**

변환 API는 내부 네트워크에서 Cortex가 호출. 관리 API만 인증 적용한 이유:
- 변환 API는 파일 넣고 결과 받는 단순 파이프라인 — 인증 오버헤드 불필요
- 관리 API는 삭제/수정/통계 등 위험한 작업 — 인증 필요

**필요하면 추가 가능.** `auth.py`의 `verify_api_key` 패턴 그대로 적용하면 됨. 환경변수 하나(`FORGE_CONVERT_AUTH=true`) 추가로 on/off.

---

### 6. 메타데이터 이중 추출

**Cortex 의견:** Forge가 메타 뽑는데 Cortex에 안 넘기면 Cortex가 또 LLM 돌림.

**Forge 대응: 완전 동의. TODO에 이미 있음.**

이건 아까 Cortex 연동 리뷰에서 "결정 필요 #1"로 잡아뒀음. Forge 메타를 Cortex `metadata` 파라미터로 함께 전달하면 Cortex의 LLM 메타 추출을 스킵 가능. callback_url 방식이면 Forge가 meta를 body에 포함.

---

## 종합 평가

| # | 이슈 | Cortex 맞음? | Forge 액션 |
|---|------|-------------|-----------|
| 1 | push-on-complete | 부분적 | callback_url 추가 (범용) — TODO에 있음 |
| 2 | 필드명 불일치 | 맞음 | 호출자 매핑 (Forge 변경 불필요) |
| 3 | 파일 크기 | 맞음 | Cortex 쪽 조정 권장 |
| 4 | PPTX extract KeyError | **맞음 — 버그** | 400 에러 반환으로 수정 필요 |
| 5 | 변환 API 인증 | 의도됨 | 필요 시 추가 가능 |
| 6 | 메타 이중 추출 | 맞음 | callback에 meta 포함 — TODO에 있음 |

**4번만 즉시 수정 필요. 나머지는 연동 시점에 결정.**
