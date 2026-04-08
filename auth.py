from fastapi import Header, HTTPException

from config import Config


def verify_api_key(config: Config):
    """API 키 인증 dependency 팩토리. config.forge_api_key가 빈 값이면 인증 비활성화."""
    def _verify(x_forge_key: str | None = Header(None)):
        if not config.forge_api_key:
            return None
        if x_forge_key != config.forge_api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return None
    return _verify
