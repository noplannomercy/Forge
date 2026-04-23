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

    # REVDOC dedicated model. None → fallback to vlm_model.
    revdoc_model: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
