# Forge Redis 도입 보류 결정 (2026-04-09)

## Cortex 전달용

**결론: Forge에 Redis 안 넣습니다. Cortex Redis와 독립.**

## 이유

Cortex는 in-memory task store밖에 없어서 Redis 교체가 필요했지만, Forge는 상황이 다름:

| 항목 | Cortex | Forge |
|------|--------|-------|
| Job 저장 | in-memory dict → Redis 필요 | **PostgreSQL에 이미 영속화** |
| 서버 재시작 | Job 날아감 | **DB에 보존됨** |
| 결과 캐싱 | 없음 | **DB에 result_text 저장** |
| 스케일 아웃 | 필요할 수 있음 | **인제스트라 순차 처리 OK** |

## Redis가 필요해지는 시점

- 동시 변환 요청이 수십 건 이상 들어오는 경우 (큐잉)
- 여러 워커 프로세스로 분리해야 하는 경우 (스케일 아웃)

현재는 `asyncio.create_task`로 충분하고, 인제스트 특성상 실시간 처리 불필요.

## Cortex 영향

- Cortex Redis 도입 시 Forge는 영향 없음
- Forge는 PostgreSQL만 사용 (Cortex와 같은 DB, forge_ 접두사로 분리)
- 인프라 공유는 PostgreSQL만
