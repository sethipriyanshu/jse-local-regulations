"""LLM access behind a small interface so the model/provider can be swapped by config
(PLAN.md D5). Every call is recorded in ai_runs with tokens and estimated cost."""

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import AiRun


class LLMNotConfigured(RuntimeError):
    pass


@dataclass
class LLMResult:
    data: dict[str, Any]
    input_tokens: int
    output_tokens: int
    model: str


class LLMProvider(Protocol):
    name: str

    def structured(
        self, system: str, user: str, schema_name: str, schema: dict[str, Any],
        max_output_tokens: int = 4000,
    ) -> LLMResult: ...


class AzureOpenAIProvider:
    name = "azure-openai"

    def __init__(self, settings: Settings) -> None:
        from openai import AzureOpenAI

        if not (settings.azure_openai_endpoint and settings.azure_openai_api_key
                and settings.azure_openai_deployment):
            raise LLMNotConfigured("Set AZURE_OPENAI_ENDPOINT, _API_KEY and _DEPLOYMENT")
        self.deployment = settings.azure_openai_deployment
        self.client = AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            timeout=120,
            max_retries=4,
        )

    def structured(
        self, system: str, user: str, schema_name: str, schema: dict[str, Any],
        max_output_tokens: int = 4000,
    ) -> LLMResult:
        res = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
            temperature=0,
            max_tokens=max_output_tokens,
        )
        content = res.choices[0].message.content or "{}"
        usage = res.usage
        return LLMResult(
            data=json.loads(content),
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=res.model or self.deployment,
        )


def get_provider() -> LLMProvider:
    return AzureOpenAIProvider(get_settings())


def run_structured(
    session: Session, provider: LLMProvider, *, kind: str, prompt_version: str, system: str,
    user: str, schema_name: str, schema: dict[str, Any], ref_type: str | None = None,
    ref_id: int | None = None, max_output_tokens: int = 4000,
) -> LLMResult:
    """Call the provider and log an ai_runs row whether or not the call succeeds."""
    s = get_settings()
    run = AiRun(kind=kind, provider=provider.name, model="?", prompt_version=prompt_version,
                ref_type=ref_type, ref_id=ref_id)
    start = time.monotonic()
    try:
        result = provider.structured(system, user, schema_name, schema, max_output_tokens)
        run.model = result.model
        run.input_tokens = result.input_tokens
        run.output_tokens = result.output_tokens
        run.cost_usd = round(
            result.input_tokens / 1e6 * s.llm_price_in_per_m
            + result.output_tokens / 1e6 * s.llm_price_out_per_m, 6
        )
        return result
    except Exception:
        run.ok = False
        raise
    finally:
        run.latency_ms = int((time.monotonic() - start) * 1000)
        session.add(run)
        session.commit()
