from __future__ import annotations

import json
import logging
import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from models import ConvertResult, Job, JobStatus, Quality

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)


class JobStore(ABC):
    @abstractmethod
    async def create(self, file_name: str, source_format: str, route: str, **kwargs) -> Job: ...

    @abstractmethod
    async def get(self, job_id: str) -> Job | None: ...

    @abstractmethod
    async def update_status(self, job_id: str, status: JobStatus) -> None: ...

    @abstractmethod
    async def save_result(self, job_id: str, result: ConvertResult) -> None: ...

    @abstractmethod
    async def save_error(self, job_id: str, error: str) -> None: ...

    async def save_meta(self, job_id: str, meta: dict, meta_prompt_version: str | None = None) -> None:
        """기본 no-op. 구현체에서 오버라이드."""
        pass


class InMemoryJobStore(JobStore):
    def __init__(self):
        self._jobs: dict[str, Job] = {}

    async def create(self, file_name: str, source_format: str, route: str, **kwargs) -> Job:
        job = Job(
            id=str(uuid.uuid4()),
            status=JobStatus.QUEUED,
            file_name=file_name,
            source_format=source_format,
            route=route,
            **kwargs,
        )
        self._jobs[job.id] = job
        return job

    async def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def update_status(self, job_id: str, status: JobStatus) -> None:
        if job_id in self._jobs:
            self._jobs[job_id].status = status

    async def save_result(self, job_id: str, result: ConvertResult) -> None:
        if job_id in self._jobs:
            job = self._jobs[job_id]
            job.status = JobStatus.COMPLETED
            job.result = result
            job.completed_at = datetime.now(timezone.utc)

    async def save_meta(self, job_id: str, meta: dict, meta_prompt_version: str | None = None) -> None:
        if job_id in self._jobs:
            self._jobs[job_id].meta = meta
            self._jobs[job_id].meta_prompt_version = meta_prompt_version

    async def save_error(self, job_id: str, error: str) -> None:
        if job_id in self._jobs:
            job = self._jobs[job_id]
            job.status = JobStatus.FAILED
            job.error = error
            job.completed_at = datetime.now(timezone.utc)

    async def soft_delete(self, job_id: str) -> bool:
        if job_id in self._jobs:
            del self._jobs[job_id]
            return True
        return False


class PostgresJobStore(JobStore):
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    def _row_to_job(self, row: dict) -> Job:
        # result 재구성 (DB에서 읽을 때)
        result = None
        if row.get("result_text") is not None:
            quality_data = json.loads(row["quality"]) if isinstance(row["quality"], str) else (row["quality"] or {})
            result = ConvertResult(
                text=row["result_text"],
                format="md",
                pages=quality_data.get("total_pages", 0),
                file_name=row["file_name"],
                source_format=row["source_format"],
                route=row["route"],
                quality=Quality(**quality_data) if quality_data else Quality(
                    total_chars=0, chars_per_page=0, total_pages=0, failed_pages=0, confidence="unknown",
                ),
            )

        return Job(
            id=str(row["id"]),
            status=JobStatus(row["status"]),
            file_name=row["file_name"],
            file_size=row["file_size"],
            source_format=row["source_format"],
            route=row["route"],
            method=row.get("method", "extract"),
            requested_by=row["requested_by"],
            result=result,
            meta=json.loads(row["meta"]) if isinstance(row["meta"], str) else (row["meta"] or {}),
            prompt_version=row["prompt_version"],
            meta_prompt_version=row["meta_prompt_version"],
            error=row["error"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            processing_ms=row["processing_ms"],
        )

    async def create(self, file_name: str, source_format: str, route: str, **kwargs) -> Job:
        job_id = str(uuid.uuid4())
        file_size = kwargs.get("file_size")
        method = kwargs.get("method", "extract")
        requested_by = kwargs.get("requested_by")
        row = await self._pool.fetchrow(
            """INSERT INTO forge_jobs (id, file_name, file_size, source_format, route, method, status, requested_by)
               VALUES ($1, $2, $3, $4, $5, $6, 'queued', $7)
               RETURNING *""",
            job_id, file_name, file_size, source_format, route, method, requested_by,
        )
        return self._row_to_job(row)

    async def get(self, job_id: str) -> Job | None:
        try:
            row = await self._pool.fetchrow("SELECT * FROM forge_jobs WHERE id = $1 AND deleted_at IS NULL", job_id)
        except Exception:
            return None
        if row is None:
            return None
        return self._row_to_job(row)

    async def update_status(self, job_id: str, status: JobStatus) -> None:
        if status == JobStatus.PROCESSING:
            await self._pool.execute(
                "UPDATE forge_jobs SET status = $1, started_at = NOW() WHERE id = $2",
                status.value, job_id,
            )
        else:
            await self._pool.execute(
                "UPDATE forge_jobs SET status = $1 WHERE id = $2",
                status.value, job_id,
            )

    async def save_result(self, job_id: str, result: ConvertResult) -> None:
        await self._pool.execute(
            """UPDATE forge_jobs
               SET status = 'completed', result_text = $1, quality = $2,
                   completed_at = NOW(), processing_ms = CAST(EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000 AS INT)
               WHERE id = $3""",
            result.text, json.dumps(result.quality.model_dump()), job_id,
        )

    async def save_meta(self, job_id: str, meta: dict, meta_prompt_version: str | None = None) -> None:
        await self._pool.execute(
            "UPDATE forge_jobs SET meta = $1, meta_prompt_version = $2 WHERE id = $3",
            json.dumps(meta), meta_prompt_version, job_id,
        )

    async def save_error(self, job_id: str, error: str) -> None:
        await self._pool.execute(
            """UPDATE forge_jobs
               SET status = 'failed', error = $1,
                   completed_at = NOW(), processing_ms = CAST(EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000 AS INT)
               WHERE id = $2""",
            error, job_id,
        )

    async def list_jobs(
        self, page: int = 1, size: int = 20,
        status: str | None = None, source_format: str | None = None,
        requested_by: str | None = None,
    ) -> tuple[list[dict], int]:
        conditions = ["deleted_at IS NULL"]
        params = []
        idx = 1
        if status:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if source_format:
            conditions.append(f"source_format = ${idx}")
            params.append(source_format)
            idx += 1
        if requested_by:
            conditions.append(f"requested_by = ${idx}")
            params.append(requested_by)
            idx += 1
        where = " AND ".join(conditions)
        total = await self._pool.fetchval(f"SELECT COUNT(*) FROM forge_jobs WHERE {where}", *params)
        offset = (page - 1) * size
        rows = await self._pool.fetch(
            f"""SELECT id, file_name, status, route, method, source_format,
                       requested_by, meta, processing_ms, created_at, deleted_at
                FROM forge_jobs WHERE {where}
                ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}""",
            *params, size, offset,
        )
        jobs = []
        for row in rows:
            meta = row["meta"]
            if isinstance(meta, str):
                meta = json.loads(meta)
            jobs.append({
                "id": str(row["id"]),
                "file_name": row["file_name"],
                "status": row["status"],
                "route": row["route"],
                "method": row["method"],
                "source_format": row["source_format"],
                "requested_by": row["requested_by"],
                "meta": meta or {},
                "processing_ms": row["processing_ms"],
                "created_at": str(row["created_at"]),
            })
        return jobs, total

    async def soft_delete(self, job_id: str) -> bool:
        try:
            result = await self._pool.execute(
                "UPDATE forge_jobs SET deleted_at = NOW() WHERE id = $1 AND deleted_at IS NULL", job_id,
            )
            return result == "UPDATE 1"
        except Exception:
            return False

    async def update_meta(self, job_id: str, meta_patch: dict) -> dict:
        existing = await self._pool.fetchval("SELECT meta FROM forge_jobs WHERE id = $1 AND deleted_at IS NULL", job_id)
        if existing is None:
            return {}
        current = json.loads(existing) if isinstance(existing, str) else (existing or {})
        current.update(meta_patch)
        await self._pool.execute(
            "UPDATE forge_jobs SET meta = $1 WHERE id = $2", json.dumps(current), job_id,
        )
        return current

    @staticmethod
    def _serialize_row(row) -> dict:
        """DB row를 JSON 직렬화 가능한 dict로 변환 (Decimal→float, date→str)."""
        from decimal import Decimal
        from datetime import date as date_type
        result = {}
        for k, v in dict(row).items():
            if isinstance(v, Decimal):
                result[k] = float(v)
            elif isinstance(v, date_type):
                result[k] = str(v)
            else:
                result[k] = v
        return result

    async def stats_daily(self, from_date: str, to_date: str) -> list[dict]:
        from datetime import date as date_cls
        f = date_cls.fromisoformat(from_date)
        t = date_cls.fromisoformat(to_date)
        rows = await self._pool.fetch(
            """SELECT DATE(created_at) AS day, COUNT(*) AS total,
                      COUNT(*) FILTER (WHERE status = 'completed') AS success,
                      COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                      AVG(processing_ms) AS avg_ms
               FROM forge_jobs
               WHERE created_at >= $1::date AND created_at < ($2::date + interval '1 day') AND deleted_at IS NULL
               GROUP BY DATE(created_at) ORDER BY day""",
            f, t,
        )
        return [self._serialize_row(r) for r in rows]

    async def stats_cost(self, from_date: str, to_date: str) -> list[dict]:
        from datetime import date as date_cls
        f = date_cls.fromisoformat(from_date)
        t = date_cls.fromisoformat(to_date)
        rows = await self._pool.fetch(
            """SELECT DATE(l.created_at) AS day,
                      COALESCE(SUM(l.cost_usd), 0) AS total_cost_usd,
                      COALESCE(SUM(COALESCE(l.input_tokens, 0) + COALESCE(l.output_tokens, 0)), 0) AS total_tokens
               FROM forge_vlm_logs l JOIN forge_jobs j ON l.job_id = j.id
               WHERE l.created_at >= $1::date AND l.created_at < ($2::date + interval '1 day') AND j.deleted_at IS NULL
               GROUP BY DATE(l.created_at) ORDER BY day""",
            f, t,
        )
        return [self._serialize_row(r) for r in rows]

    async def stats_models(self) -> list[dict]:
        rows = await self._pool.fetch(
            """SELECT model, COUNT(*) AS calls, AVG(latency_ms) AS avg_latency_ms,
                      COALESCE(SUM(cost_usd), 0) AS total_cost_usd,
                      COALESCE(SUM(input_tokens), 0) AS total_input_tokens,
                      COALESCE(SUM(output_tokens), 0) AS total_output_tokens
               FROM forge_vlm_logs GROUP BY model ORDER BY calls DESC"""
        )
        return [self._serialize_row(r) for r in rows]


class VLMLogStore:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def log(
        self, job_id: str, batch_num: int, purpose: str,
        model: str, prompt_version: str | None,
        input_tokens: int | None, output_tokens: int | None,
        cost_usd: float | None, latency_ms: int | None,
        success: bool, error: str | None,
    ) -> None:
        await self._pool.execute(
            """INSERT INTO forge_vlm_logs
               (job_id, batch_num, purpose, model, prompt_version,
                input_tokens, output_tokens, cost_usd, latency_ms, success, error)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
            job_id, batch_num, purpose, model, prompt_version,
            input_tokens, output_tokens, cost_usd, latency_ms, success, error,
        )


class PromptStore:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def get_active(self, prompt_type: str) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM forge_prompts WHERE type = $1 AND is_active = TRUE",
            prompt_type,
        )
        if row is None:
            return None
        return dict(row)

    async def list_all(self) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT * FROM forge_prompts ORDER BY type, version DESC"
        )
        return [dict(r) for r in rows]

    async def create_version(self, prompt_type: str, text: str) -> dict:
        max_version = await self._pool.fetchval(
            "SELECT MAX(version) FROM forge_prompts WHERE type = $1",
            prompt_type,
        )
        new_version = (max_version or 0) + 1
        await self._pool.execute(
            "UPDATE forge_prompts SET is_active = FALSE WHERE type = $1 AND is_active = TRUE",
            prompt_type,
        )
        row = await self._pool.fetchrow(
            """INSERT INTO forge_prompts (type, version, text, is_active)
               VALUES ($1, $2, $3, TRUE) RETURNING *""",
            prompt_type, new_version, text,
        )
        return dict(row)

    async def seed_if_empty(self, prompt_type: str, default_text: str) -> None:
        exists = await self._pool.fetchval(
            "SELECT COUNT(*) FROM forge_prompts WHERE type = $1", prompt_type
        )
        if exists == 0:
            await self._pool.fetchrow(
                """INSERT INTO forge_prompts (type, version, text, is_active)
                   VALUES ($1, 1, $2, TRUE) RETURNING *""",
                prompt_type, default_text,
            )


class InMemoryPromptStore:
    """In-memory prompt store — DB 없는 환경(로컬 InMemory, 테스트)용.

    PostgresPromptStore(`PromptStore`)와 동일한 메서드 시그니처를 제공하여
    `seed_prompts()`가 두 구현 모두에 대해 동작하도록 한다 (CF-5).
    """

    def __init__(self):
        # prompt_type -> list of {id, type, version, text, is_active, created_at}, newest first
        self._data: dict[str, list[dict]] = {}
        self._next_id = 1

    async def get_active(self, prompt_type: str) -> dict | None:
        for entry in self._data.get(prompt_type, []):
            if entry["is_active"]:
                return dict(entry)
        return None

    async def list_all(self) -> list[dict]:
        out: list[dict] = []
        for prompt_type in sorted(self._data.keys()):
            for entry in self._data[prompt_type]:
                out.append(dict(entry))
        return out

    async def create_version(self, prompt_type: str, text: str) -> dict:
        versions = self._data.setdefault(prompt_type, [])
        for entry in versions:
            entry["is_active"] = False
        new_version = (max((e["version"] for e in versions), default=0)) + 1
        new_entry = {
            "id": self._next_id,
            "type": prompt_type,
            "version": new_version,
            "text": text,
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
        }
        self._next_id += 1
        versions.insert(0, new_entry)
        return dict(new_entry)

    async def seed_if_empty(self, prompt_type: str, default_text: str) -> None:
        if self._data.get(prompt_type):
            return
        await self.create_version(prompt_type, default_text)


def _normalize_prompt_text(text: str) -> str:
    """줄바꿈·trailing whitespace 차이를 정규화하여 비교 안정성 확보.

    - CRLF → LF (Windows git autocrlf / editor 설정 차이 대응)
    - 파일 끝 trailing whitespace 제거 (editor save 차이 대응)

    `ensure_latest_prompt()`가 파일과 DB 텍스트를 비교할 때 사용하여
    환경 간 autocrlf 차이로 인한 "텍스트 다름" 오판을 방지한다.
    """
    return text.replace("\r\n", "\n").rstrip()


def _load_reverse_doc_prompt() -> str:
    """revdoc/prompts/reverse_doc_v1.md 텍스트를 로드.

    파일 누락 시 RuntimeError. 하드코딩 fallback 없음 — 배포 누락 즉시 감지.
    """
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "revdoc",
        "prompts",
        "reverse_doc_v1.md",
    )
    if not os.path.isfile(path):
        raise RuntimeError(f"reverse_doc prompt file missing: {path}")
    with open(path, encoding="utf-8") as f:
        return f.read()


async def seed_prompts(store) -> None:
    """reverse_doc 프롬프트를 store에 시드 (idempotent, seed_if_empty 기반).

    `PromptStore`(Postgres) / `InMemoryPromptStore` 둘 다 동일 시그니처 수용.
    기존 semantic/meta_extract 시드 호출 뒤에 부르거나, InMemory 분기에서
    단독 호출 가능.
    """
    reverse_doc_text = _load_reverse_doc_prompt()
    await store.seed_if_empty("reverse_doc", reverse_doc_text)


# ---------------------------------------------------------------------------
# RefineRuleStore — v3 LightRAG extension (REFINE-06)
# ---------------------------------------------------------------------------

class RefineRuleStore(ABC):
    @abstractmethod
    async def active(self, stage: str) -> dict:
        """Return the active config dict for a stage, merged with 'version' key.

        Raises LookupError if no active rule exists for the stage.
        """
        ...

    @abstractmethod
    async def upsert(self, stage: str, config: dict) -> int:
        """Insert a new version for `stage`, marking it active and deactivating prior.

        Returns the new version number.
        """
        ...

    @abstractmethod
    async def list_versions(self, stage: str) -> list[dict]:
        """Return all versions for `stage`, newest first.

        Each item: {version, config, is_active, created_at}.
        """
        ...


class InMemoryRefineRuleStore(RefineRuleStore):
    def __init__(self):
        # stage -> list of {version, config, is_active, created_at}, newest first
        self._rules: dict[str, list[dict]] = {}

    async def active(self, stage: str) -> dict:
        versions = self._rules.get(stage, [])
        for entry in versions:
            if entry["is_active"]:
                return {**entry["config"], "version": entry["version"]}
        raise LookupError(f"No active refine rule for stage: {stage}")

    async def upsert(self, stage: str, config: dict) -> int:
        if "version" in config:
            raise ValueError(
                "config must not contain reserved key 'version' — it is store-managed"
            )
        versions = self._rules.setdefault(stage, [])
        # Deactivate prior active
        for entry in versions:
            entry["is_active"] = False
        next_version = (max((e["version"] for e in versions), default=0)) + 1
        versions.insert(0, {
            "version": next_version,
            "config": dict(config),
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
        })
        return next_version

    async def list_versions(self, stage: str) -> list[dict]:
        versions = self._rules.get(stage, [])
        # Already stored newest-first; return shallow copies to prevent mutation leak
        return [dict(entry) for entry in versions]


class PostgresRefineRuleStore(RefineRuleStore):
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    @staticmethod
    def _parse_config(value) -> dict:
        if isinstance(value, str):
            return json.loads(value)
        return value or {}

    async def active(self, stage: str) -> dict:
        row = await self._pool.fetchrow(
            "SELECT version, config FROM forge_refine_rules WHERE stage = $1 AND is_active = TRUE",
            stage,
        )
        if row is None:
            raise LookupError(f"No active refine rule for stage: {stage}")
        config = self._parse_config(row["config"])
        return {**config, "version": row["version"]}

    async def upsert(self, stage: str, config: dict) -> int:
        if "version" in config:
            raise ValueError(
                "config must not contain reserved key 'version' — it is store-managed"
            )
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                max_version = await conn.fetchval(
                    "SELECT MAX(version) FROM forge_refine_rules WHERE stage = $1",
                    stage,
                )
                new_version = (max_version or 0) + 1
                await conn.execute(
                    "UPDATE forge_refine_rules SET is_active = FALSE "
                    "WHERE stage = $1 AND is_active = TRUE",
                    stage,
                )
                await conn.execute(
                    """INSERT INTO forge_refine_rules (stage, version, config, is_active)
                       VALUES ($1, $2, $3::jsonb, TRUE)""",
                    stage, new_version, json.dumps(config),
                )
                return new_version

    async def list_versions(self, stage: str) -> list[dict]:
        rows = await self._pool.fetch(
            """SELECT version, config, is_active, created_at
               FROM forge_refine_rules WHERE stage = $1
               ORDER BY version DESC""",
            stage,
        )
        return [
            {
                "version": r["version"],
                "config": self._parse_config(r["config"]),
                "is_active": r["is_active"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# DoclingLogStore — v3 LightRAG extension (DOCLING-08)
# ---------------------------------------------------------------------------

class DoclingLogStore(ABC):
    @abstractmethod
    async def insert(
        self,
        *,
        job_id,
        pages: int,
        latency_ms: int,
        status_code: int | None,
        fallback: bool,
        reason: str | None,
    ) -> None:
        ...


class InMemoryDoclingLogStore(DoclingLogStore):
    def __init__(self):
        self._rows: list[dict] = []

    async def insert(self, *, job_id, pages, latency_ms, status_code, fallback, reason):
        self._rows.append({
            "job_id": job_id,
            "pages": pages,
            "latency_ms": latency_ms,
            "status_code": status_code,
            "fallback": fallback,
            "fallback_reason": reason,
            "created_at": datetime.now(timezone.utc),
        })

    async def list_all(self) -> list[dict]:
        return [dict(r) for r in self._rows]


class PostgresDoclingLogStore(DoclingLogStore):
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def insert(self, *, job_id, pages, latency_ms, status_code, fallback, reason):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO forge_docling_logs
                       (job_id, pages, latency_ms, status_code, fallback, fallback_reason)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                job_id, pages, latency_ms, status_code, fallback, reason,
            )


REFINE_RULE_DEFAULTS = {
    "encoding": {"try_order": ["utf-8-sig", "utf-8", "cp949", "euc-kr"]},
    "newline": {"patterns": [r"\\r\\n", r"\\n"], "replace_with": "\n"},
    "special_char": {"map": {"~": "∼", "·": "·"}, "normalize_width": True},
    "frontmatter": {"delimiters": ["---", "+++"], "keep_keys": []},
    "codefence": {"strip": False, "keep_lang": True},
    "traceability": {"pattern": r"(\w+)\s*↔\s*(\w+)", "replace": r"\1은 \2에 연결된다."},
    "validator": {
        "require_utf8": True,
        "min_newlines": 1,
        "min_korean_ratio": 0.1,
        "min_length": 100,
    },
}


async def seed_refine_rules(store: RefineRuleStore) -> None:
    """Seed each stage with its default config if no active version exists."""
    for stage, config in REFINE_RULE_DEFAULTS.items():
        try:
            await store.active(stage)
        except LookupError:
            await store.upsert(stage, config)
            logger.info("Seeded default refine rule for stage: %s", stage)
