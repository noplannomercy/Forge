import asyncio
import base64

import httpx

from config import Config
from models import DocumentResult, PageResult

MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # 지수 백오프


VLM_PROMPT = """이 문서 페이지의 내용을 Markdown으로 변환해.

규칙:
- 모든 텍스트를 레이아웃 순서대로 추출
- 표는 마크다운 표 형식으로 변환
- 이미지/도형은 [이미지: 설명] 형태로 기술
- 제목/소제목은 마크다운 헤딩(#, ##)으로
- 원본 내용을 빠뜨리지 말 것"""


class VLMClient:
    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.AsyncClient(timeout=config.vlm_timeout)
        self.semaphore = asyncio.Semaphore(config.vlm_concurrency)

    async def process_page(self, image_bytes: bytes, page_num: int) -> PageResult:
        """단일 페이지 VLM 호출. 3회 retry 후 실패 시 예외 안 던짐."""
        async with self.semaphore:
            last_error = None
            for attempt in range(MAX_RETRIES):
                try:
                    b64_image = base64.b64encode(image_bytes).decode("utf-8")
                    payload = {
                        "model": self.config.vlm_model,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": VLM_PROMPT},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/png;base64,{b64_image}"
                                        },
                                    },
                                ],
                            }
                        ],
                        "max_tokens": 4096,
                    }

                    headers = {"Content-Type": "application/json"}
                    if self.config.vlm_api_key:
                        headers["Authorization"] = f"Bearer {self.config.vlm_api_key}"

                    response = await self.client.post(
                        self.config.vlm_url, json=payload, headers=headers
                    )
                    response.raise_for_status()
                    data = response.json()
                    text = data["choices"][0]["message"]["content"]
                    return PageResult(page=page_num, text=text, success=True)

                except Exception as e:
                    last_error = e
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAYS[attempt])

            return PageResult(
                page=page_num,
                text=f"[변환 실패: 페이지 {page_num}]",
                success=False,
                error=str(last_error),
            )

    async def process_document(self, images: list[bytes]) -> DocumentResult:
        """전체 페이지 동시 처리 (Semaphore로 제한)"""
        tasks = [self.process_page(img, i + 1) for i, img in enumerate(images)]
        results = await asyncio.gather(*tasks)

        text = "\n\n".join(r.text for r in results)
        failed = [r for r in results if not r.success]

        return DocumentResult(
            text=text,
            total_pages=len(results),
            failed_pages=len(failed),
            confidence="high" if not failed else "partial",
        )

    async def close(self):
        await self.client.aclose()
