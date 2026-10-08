"""Multimodal model contract and the OpenAI adapter (ADR 0003).

The pipeline only sees ``MultimodalModel``: a request with instructions, text,
one image and an output schema, and a result with the raw text, token usage and
provider status. Parsing and validation happen outside the adapter, so a
malformed or truncated response is kept and marked instead of being lost.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel


class ProviderError(Exception):
    """A call failed; other figures can still be analysed."""


class ProviderFatalError(ProviderError):
    """A failure that will repeat for every call (auth, quota, unknown model): stop."""


@dataclass(frozen=True)
class ModelRequest:
    instructions: str
    text: str
    image_png: bytes
    output_schema: type[BaseModel]
    max_output_tokens: int
    image_detail: str = "high"
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class ModelResult:
    raw_text: str | None
    model_version: str | None
    provider_status: str  # completed | incomplete | failed
    incomplete_reason: str | None = None
    refusal: str | None = None
    response_id: str | None = None
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    latency_ms: int = 0


class MultimodalModel(Protocol):
    provider: str
    model: str

    def check(self) -> None:
        """Verify that the model is reachable and available; raise ProviderFatalError."""
        ...

    def generate(self, request: ModelRequest) -> ModelResult: ...


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema for structured outputs: every property required, no extra keys."""
    schema = model.model_json_schema()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            node.pop("default", None)  # defaults only exist to load older stored records
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    return schema


class OpenAIMultimodalModel:
    provider = "openai"

    def __init__(self, model: str, client: Any = None, timeout_s: float = 120.0):
        self.model = model
        if client is None:
            import openai

            # The SDK retries connection errors, 429 and 5xx with backoff.
            client = openai.OpenAI(timeout=timeout_s, max_retries=3)
        self.client = client

    def check(self) -> None:
        import openai

        try:
            self.client.models.retrieve(self.model)
        except openai.NotFoundError as exc:
            raise ProviderFatalError(f"Model {self.model!r} is not available: {exc}") from exc
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            raise ProviderFatalError(f"OpenAI rejected the API key: {exc}") from exc
        except openai.APIError as exc:
            raise ProviderFatalError(f"Cannot reach OpenAI: {exc}") from exc

    def generate(self, request: ModelRequest) -> ModelResult:
        import openai

        image_url = "data:image/png;base64," + base64.b64encode(request.image_png).decode()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": request.instructions,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": request.text},
                        {
                            "type": "input_image",
                            "image_url": image_url,
                            "detail": request.image_detail,
                        },
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": request.output_schema.__name__,
                    "schema": strict_json_schema(request.output_schema),
                    "strict": True,
                }
            },
            "max_output_tokens": request.max_output_tokens,
            # Article content is not stored on the provider side beyond what the API requires.
            "store": False,
        }
        if request.reasoning_effort:
            kwargs["reasoning"] = {"effort": request.reasoning_effort}

        started = time.perf_counter()
        try:
            response = self.client.responses.create(**kwargs)
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            raise ProviderFatalError(f"OpenAI rejected the API key: {exc}") from exc
        except openai.NotFoundError as exc:
            raise ProviderFatalError(f"Model {self.model!r} is not available: {exc}") from exc
        except openai.RateLimitError as exc:
            if getattr(exc, "code", None) == "insufficient_quota":
                raise ProviderFatalError(f"OpenAI quota exhausted: {exc}") from exc
            raise ProviderError(f"Rate limited: {exc}") from exc
        except openai.APIError as exc:
            raise ProviderError(f"{type(exc).__name__}: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        refusal = None
        texts = []
        for item in response.output or []:
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", None) == "refusal":
                    refusal = part.refusal
                elif getattr(part, "type", None) == "output_text":
                    texts.append(part.text)
        usage = response.usage
        input_details = getattr(usage, "input_tokens_details", None)
        output_details = getattr(usage, "output_tokens_details", None)
        incomplete = getattr(response, "incomplete_details", None)
        return ModelResult(
            raw_text="".join(texts) or None,
            model_version=response.model,
            provider_status=response.status or "completed",
            incomplete_reason=getattr(incomplete, "reason", None),
            refusal=refusal,
            response_id=response.id,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            cached_input_tokens=getattr(input_details, "cached_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            reasoning_tokens=getattr(output_details, "reasoning_tokens", 0) or 0,
            latency_ms=latency_ms,
        )
