import asyncio
import base64
import time

import httpx

from config import Config
from models import DocumentResult

MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]


SEMANTIC_PROMPT = """이 문서 페이지들을 분석해서 의미 중심으로 재구성해.

규칙:
- 페이지별로 나누지 말고, 내용을 주제별로 묶어서 구조화
- 배경 이미지, 장식, 페이지 번호 등 의미 없는 요소는 무시
- 다이어그램/흐름도는 텍스트로 설명
- 표/비교 데이터는 마크다운 표로 재구성
- 핵심 정보만 추출해서 간결한 마크다운 문서로 만들어
- 한국어로 작성"""


class BatchResult:
    def __init__(
        self, batch_num: int, text: str, success: bool,
        error: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
    ):
        self.batch_num = batch_num
        self.text = text
        self.success = success
        self.error = error
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.latency_ms = latency_ms


class VLMClient:
    def __init__(self, config: Config, prompt: str | None = None):
        self.config = config
        self.prompt = prompt or SEMANTIC_PROMPT
        self.client = httpx.AsyncClient(timeout=config.vlm_timeout)
        self.semaphore = asyncio.Semaphore(config.vlm_concurrency)

    async def process_batch(self, images: list[bytes], batch_num: int) -> BatchResult:
        """N장 이미지를 묶어서 semantic 프롬프트로 1회 VLM 호출. 3회 retry."""
        async with self.semaphore:
            last_error = None
            for attempt in range(MAX_RETRIES):
                try:
                    start_time = time.monotonic()
                    content = [{"type": "text", "text": self.prompt}]
                    for img in images:
                        b64 = base64.b64encode(img).decode("utf-8")
                        content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        })

                    payload = {
                        "model": self.config.vlm_model,
                        "messages": [{"role": "user", "content": content}],
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
                    elapsed_ms = int((time.monotonic() - start_time) * 1000)
                    usage = data.get("usage", {})
                    return BatchResult(
                        batch_num=batch_num, text=text, success=True,
                        input_tokens=usage.get("prompt_tokens"),
                        output_tokens=usage.get("completion_tokens"),
                        latency_ms=elapsed_ms,
                    )

                except Exception as e:
                    last_error = e
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAYS[attempt])

            start_page = (batch_num - 1) * self.config.vlm_batch_size + 1
            end_page = start_page + len(images) - 1
            return BatchResult(
                batch_num=batch_num,
                text=f"[변환 실패: 페이지 {start_page}-{end_page}]",
                success=False,
                error=str(last_error),
            )

    async def process_text(
        self,
        text: str,
        prompt: str,
        purpose: str,
        model: str | None = None,
    ) -> str:
        """텍스트 전용 LLM 호출 (비전 없음). Semaphore + 3회 retry를 재사용.

        Args:
            text: user 메시지 본문 (분석 대상 코드/문서).
            prompt: system 프롬프트.
            purpose: 로깅 용도 (예: "reverse_doc"). 현재는 future-log hook.
            model: 모델 오버라이드. 미지정 시 ``config.vlm_model`` 사용.

        Returns:
            LLM이 반환한 텍스트 응답.

        Raises:
            RuntimeError: 3회 retry 이후에도 실패한 경우. process_batch와 달리
                placeholder를 반환하지 않고 예외를 올려 호출자(=generator)가
                gate 흐름 밖의 실패로 구분해 처리할 수 있게 한다.
        """
        chosen_model = model or self.config.vlm_model
        async with self.semaphore:  # S1
            last_error: Exception | None = None
            for attempt in range(MAX_RETRIES):
                try:
                    payload = {
                        "model": chosen_model,
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": text},
                        ],
                        "max_tokens": 4096,
                    }
                    headers = {"Content-Type": "application/json"}
                    if self.config.vlm_api_key:
                        headers["Authorization"] = f"Bearer {self.config.vlm_api_key}"

                    response = await self.client.post(
                        self.config.vlm_url, json=payload, headers=headers,
                    )
                    response.raise_for_status()
                    data = response.json()
                    return data["choices"][0]["message"]["content"]

                except Exception as e:
                    last_error = e
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAYS[attempt])

            raise RuntimeError(
                f"process_text failed after {MAX_RETRIES} attempts "
                f"(purpose={purpose}, model={chosen_model}): {last_error}"
            )

    async def process_document(self, images: list[bytes]) -> tuple[DocumentResult, list[BatchResult]]:
        """전체 이미지를 batch_size씩 나눠서 semantic 처리. (DocumentResult, batch_results) 반환."""
        batch_size = self.config.vlm_batch_size
        batches = [images[i:i + batch_size] for i in range(0, len(images), batch_size)]

        tasks = [
            self.process_batch(batch, batch_num=i + 1)
            for i, batch in enumerate(batches)
        ]
        batch_results = await asyncio.gather(*tasks)

        text = "\n\n---\n\n".join(r.text for r in batch_results)
        failed = [r for r in batch_results if not r.success]

        doc_result = DocumentResult(
            text=text,
            total_pages=len(images),
            failed_pages=0,
            confidence="high" if not failed else "partial",
            total_batches=len(batches),
            failed_batches=len(failed),
        )
        return doc_result, list(batch_results)

    async def close(self):
        await self.client.aclose()
