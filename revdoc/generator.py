"""Reverse-doc generator (REVDOC-01/04/06/08).

Glues together the reverse_doc prompt (PromptStore), the LLM call
(``VLMClient.process_text`` — S7 compliant), the structural gate
(:class:`revdoc.gate.RevdocGate`), and the Markdown refiner
(:class:`refine.Refiner`) into a single ``generate()`` coroutine.

Workflow:

1. Load the active ``reverse_doc`` prompt from the ``PromptStore``.
2. Call ``VLMClient.process_text(source_code, prompt)`` — S7.
3. Run :meth:`RevdocGate.check` on the result.
4. **Pass** → run :meth:`Refiner.refine` on the result, return.
5. **Fail** → append ``gate.feedback`` under a ``## 재시도 피드백``
   header to the prompt, retry (up to ``max_retries`` extra attempts).
6. Retries exhausted → return the *last* generation with the failed
   gate verdict and ``refine_report=None``.

Design notes:

* The Gate short-circuits on the first failing check (sections >
  traceability > length). Its feedback string carries an actionable,
  Korean hint suitable for direct re-injection into the LLM prompt.
* :meth:`Refiner.refine` is synchronous per T4, so it's called
  without ``await``. The refined text replaces the raw LLM output in
  the final result so downstream consumers see the canonicalised MD.
* The generator does **not** log failed attempts to ``forge_vlm_logs``
  — that belongs to the worker (T10 will wire it).
* No ``lightrag`` / Cortex imports (C1, C6 — consumer-agnostic).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .gate import GateVerdict, RevdocGate


@dataclass
class RevdocResult:
    """Outcome of a :meth:`ReverseDocGenerator.generate` call.

    Attributes:
        result_text: final MD — refined on pass, raw (last) generation on fail.
        prompt_version: ``"reverse_doc-v<N>"`` — the prompt version consumed.
        gate: ``{"passed": bool, "details": dict, "reason": str|None}`` from
            the LAST gate check performed (i.e. the check that decided the
            outcome — pass on success, final-attempt fail on retries exhausted).
        refine_report: :attr:`refine.RefineResult.report` on pass, ``None``
            on fail (Refiner is not run for failing outputs — they may be
            structurally malformed in ways that trip the stages).
        attempts: number of LLM calls made (1..max_retries+1).
    """

    result_text: str
    prompt_version: str
    gate: dict
    refine_report: dict | None
    attempts: int


class ReverseDocGenerator:
    """Gate-driven reverse-doc LLM orchestrator with retry + Refine.

    Parameters:
        vlm: :class:`vlm.VLMClient` — must expose ``process_text``.
        prompt_store: :class:`job_store.PromptStore` /
            :class:`job_store.InMemoryPromptStore` — must expose async
            ``get_active(type) -> dict|None`` with at least ``text`` and
            ``version`` keys.
        refiner: :class:`refine.Refiner` — ``refine(str) -> RefineResult``
            called synchronously on gate pass.
        gate: :class:`RevdocGate` (optional — defaults to ``RevdocGate()``
            with the standard 800-char min length).
        max_retries: additional attempts after the first. Default 2 →
            worst case 3 total LLM calls.
        model: optional model override passed to ``vlm.process_text``. If
            ``None``, the VLM client's own default (``config.vlm_model``)
            is used. Wire ``config.revdoc_model`` here at construction
            time when set.
    """

    def __init__(
        self,
        vlm,  # VLMClient — duck-typed for test AsyncMock substitution
        prompt_store,  # PromptStore / InMemoryPromptStore
        refiner,  # Refiner
        gate: RevdocGate | None = None,
        max_retries: int = 2,
        model: str | None = None,
    ):
        self.vlm = vlm
        self.prompt_store = prompt_store
        self.refiner = refiner
        self.gate = gate or RevdocGate()
        self.max_retries = max_retries
        self.model = model

    async def generate(self, source_code: str, file_name: str) -> RevdocResult:
        """Generate a reverse-doc MD for ``source_code``.

        ``file_name`` is accepted for future logging hooks; it's not used
        in prompt construction (the prompt itself contains all required
        instructions — the source code is the sole user-message body).
        """
        prompt_row = await self.prompt_store.get_active("reverse_doc")
        if prompt_row is None:
            raise LookupError("no active reverse_doc prompt")

        # PromptStore (Postgres) and InMemoryPromptStore both return dict,
        # but we defer-accept row-like objects for forward-compat.
        base_prompt = (
            prompt_row["text"] if isinstance(prompt_row, dict) else prompt_row.text
        )
        version = (
            prompt_row["version"]
            if isinstance(prompt_row, dict)
            else prompt_row.version
        )
        prompt_version = f"reverse_doc-v{version}"

        feedback: str | None = None
        attempts = 0
        verdict: GateVerdict | None = None
        generated: str = ""

        for _ in range(self.max_retries + 1):
            attempts += 1
            full_prompt = base_prompt
            if feedback:
                # Korean retry-feedback header matches the spec exactly.
                full_prompt += f"\n\n## 재시도 피드백\n\n{feedback}"

            generated = await self.vlm.process_text(
                text=source_code,
                prompt=full_prompt,
                purpose="reverse_doc",
                model=self.model,
            )

            verdict = self.gate.check(generated)
            if verdict.passed:
                refined = self.refiner.refine(generated)
                return RevdocResult(
                    result_text=refined.text,
                    prompt_version=prompt_version,
                    gate={
                        "passed": True,
                        "details": verdict.details,
                        "reason": None,
                    },
                    refine_report=refined.report,
                    attempts=attempts,
                )

            feedback = verdict.feedback

        # Retries exhausted — return last generation unrefined.
        # `verdict` is guaranteed non-None because the loop body ran ≥ 1 time.
        assert verdict is not None  # loop invariant
        return RevdocResult(
            result_text=generated,
            prompt_version=prompt_version,
            gate={
                "passed": False,
                "details": verdict.details,
                "reason": verdict.reason,
            },
            refine_report=None,
            attempts=attempts,
        )


__all__: list[str] = ["ReverseDocGenerator", "RevdocResult"]
