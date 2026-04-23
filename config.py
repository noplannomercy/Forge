import json

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    vlm_url: str = "http://localhost:11434/v1/chat/completions"
    vlm_model: str = "qwen2-vl:7b"
    vlm_api_key: str = ""
    vlm_timeout: int = 120
    vlm_concurrency: int = 3
    vlm_batch_size: int = 5
    host: str = "0.0.0.0"
    port: int = 8003
    max_file_size: int = 104_857_600  # 100MB

    # DB
    database_url: str = ""

    # 메타 추출 LLM (미설정 시 VLM 설정 fallback)
    meta_llm_url: str = ""
    meta_llm_model: str = ""
    meta_llm_api_key: str = ""

    # 관리 API 인증
    forge_api_key: str = ""

    # Callback 인증 (Cortex X-API-Key)
    callback_api_key: str = ""

    # Callback payload field rename (consumer-agnostic).
    # JSON string, e.g. {"content":"text","file_name":"file_source"}.
    callback_field_map: str | None = None
    callback_keep_unmapped: bool = False

    # REVDOC 전용 모델 (미설정 시 VLM_MODEL fallback)
    revdoc_model: str | None = None

    # Docling-Serve (remote HTTP) — see docs/plans Late Update for rationale
    docling_serve_url: str | None = None  # e.g. "http://193.168.195.222:5001"
    docling_api_key: str | None = None    # optional; docling-serve's X-Api-Key header

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("callback_field_map")
    @classmethod
    def _validate_callback_field_map(cls, v: str | None) -> str | None:
        """CALLBACK_FIELD_MAP 사전 검증 — 시동 시점에 실패시켜 런타임 콜백 누락을 방지."""
        if v is None or v == "":
            return None
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError as exc:
            raise ValueError(f"CALLBACK_FIELD_MAP must be valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("CALLBACK_FIELD_MAP must be a JSON object")
        if not all(isinstance(k, str) and isinstance(val, str) for k, val in parsed.items()):
            raise ValueError("CALLBACK_FIELD_MAP must be a JSON object mapping string→string")
        return v
