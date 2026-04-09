import asyncio
import json

import httpx

from config import Config

MAX_RETRIES = 2
RETRY_DELAY = 1

META_PROMPT = """이 문서를 분석해서 JSON으로 메타데이터를 추출해.

반드시 포함: category, title, summary(2줄), keywords(5개)
가능하면 포함: client, author, date, budget, project_name

JSON만 반환. 다른 텍스트 없이."""

MAX_INPUT_CHARS = 3000


class MetaExtractor:
    def __init__(self, config: Config, prompt: str | None = None):
        self.prompt = prompt or META_PROMPT
        self.url = config.meta_llm_url or config.vlm_url
        self.model = config.meta_llm_model or config.vlm_model
        api_key = config.meta_llm_api_key or config.vlm_api_key
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        self.client = httpx.AsyncClient(timeout=60)

    async def extract(self, text: str) -> dict:
        """변환된 텍스트에서 메타데이터 추출. 2회 retry. 실패 시 빈 dict 반환."""
        truncated = text[:MAX_INPUT_CHARS]
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": f"{self.prompt}\n\n---\n\n{truncated}"}
            ],
            "max_tokens": 1024,
            "temperature": 0,
        }

        for attempt in range(MAX_RETRIES):
            try:
                response = await self.client.post(self.url, json=payload, headers=self.headers)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]

                # JSON 파싱 (다양한 LLM 응답 형식 대응)
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1]
                    content = content.rsplit("```", 1)[0]
                start = content.find("{")
                end = content.rfind("}")
                if start != -1 and end != -1:
                    content = content[start:end + 1]

                return json.loads(content.strip())
            except Exception:
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
        return {}

    async def close(self):
        await self.client.aclose()
