"""Wire formats for the providers an admin can configure.

- anthropic: the official Anthropic SDK (Messages API).
- openai / openai_compatible: the Chat Completions format, which OpenAI, Google Gemini,
  OpenRouter, Groq, Together, Mistral and local Ollama/LM Studio servers all accept.

Messages arrive in one neutral shape: {"role": "user"|"assistant", "content": [part, ...]}
with parts {"type": "text", "text": ...} or {"type": "image", "media_type": ..., "data": <base64>}.
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

import anthropic
import httpx

# Claude models that accept the server-side refusal fallback (`fallbacks: "default"`).
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Effort values the Chat Completions `reasoning_effort` field accepts ("max" is Claude only).
_REASONING_EFFORTS = {"none", "low", "medium", "high", "xhigh"}


class ProviderError(RuntimeError):
    """A provider call failed in a way worth showing to the admin."""


class IncompleteAnswer(ProviderError):
    """The model answered, but not in a usable shape: invalid JSON, or cut off at max tokens.
    Asking again usually works."""


@dataclass
class ProviderConfig:
    kind: str
    api_key: str
    base_url: str
    model: str
    effort: str = ""
    max_tokens: int = 4096
    temperature: float | None = None  # None: the provider's default
    timeout: float = 180.0

# OpenAI-compatible servers that rejected response_format json_schema (base URL -> False): they get
# json_object plus the schema in the prompt from then on.
_SCHEMA_SUPPORT: dict[str, bool] = {}


@dataclass
class Completion:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw_stop: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


async def complete(
    cfg: ProviderConfig,
    *,
    system: str,
    messages: list[dict[str, Any]],
    json_schema: dict[str, Any] | None,
) -> Completion:
    if cfg.kind == "anthropic":
        return await _anthropic(cfg, system, messages, json_schema)
    if cfg.kind in ("openai", "openai_compatible"):
        return await _chat_completions(cfg, system, messages, json_schema)
    raise ProviderError(f"Unknown provider kind: {cfg.kind}")


# --- Anthropic -------------------------------------------------------------------------


def _anthropic_content(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for p in parts:
        if p["type"] == "text":
            out.append({"type": "text", "text": p["text"]})
        elif p["type"] == "image":
            out.append({"type": "image", "source": {"type": "base64", "media_type": p["media_type"], "data": p["data"]}})
    return out


async def _anthropic(cfg: ProviderConfig, system: str, messages: list[dict[str, Any]], json_schema: dict[str, Any] | None) -> Completion:
    client = anthropic.AsyncAnthropic(api_key=cfg.api_key, base_url=cfg.base_url or None, timeout=cfg.timeout, max_retries=2)
    output_config: dict[str, Any] = {}
    if cfg.effort and cfg.effort != "none":
        output_config["effort"] = cfg.effort
    if json_schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": json_schema}
    kwargs: dict[str, Any] = {
        "model": cfg.model,
        "max_tokens": cfg.max_tokens,
        "messages": [{"role": m["role"], "content": _anthropic_content(m["content"])} for m in messages],
    }
    if system:
        kwargs["system"] = system
    if output_config:
        kwargs["output_config"] = output_config
    try:
        if cfg.model in _FALLBACK_MODELS and not cfg.base_url:
            # A safety-classifier decline is retried server-side on the recommended model.
            resp = await client.beta.messages.create(betas=[_FALLBACK_BETA], fallbacks="default", **kwargs)
        else:
            resp = await client.messages.create(**kwargs)
    except anthropic.AuthenticationError as exc:
        raise ProviderError("Anthropic rejected the API key") from exc
    except anthropic.NotFoundError as exc:
        raise ProviderError(f"Unknown model or endpoint: {cfg.model}") from exc
    except anthropic.RateLimitError as exc:
        raise ProviderError("Anthropic rate limit hit; try again shortly") from exc
    except anthropic.BadRequestError as exc:
        raise ProviderError(f"Anthropic rejected the request: {exc.message}") from exc
    except anthropic.APIStatusError as exc:
        raise ProviderError(f"Anthropic error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise ProviderError("Could not reach the Anthropic API") from exc
    finally:
        await client.close()

    if resp.stop_reason == "refusal":
        category = getattr(resp.stop_details, "category", None) if resp.stop_details else None
        raise ProviderError(f"The model declined this request (category: {category or 'unspecified'})")
    text = "".join(b.text for b in resp.content if b.type == "text")
    if resp.stop_reason == "max_tokens" and json_schema is not None:
        raise IncompleteAnswer("The answer hit max_tokens before it was complete; raise max tokens for this task")
    return Completion(text=text, input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens, raw_stop=resp.stop_reason)


# --- OpenAI-style Chat Completions -----------------------------------------------------


def _chat_content(parts: list[dict[str, Any]]) -> list[dict[str, Any]] | str:
    if all(p["type"] == "text" for p in parts):
        return "\n\n".join(p["text"] for p in parts)
    out: list[dict[str, Any]] = []
    for p in parts:
        if p["type"] == "text":
            out.append({"type": "text", "text": p["text"]})
        elif p["type"] == "image":
            out.append({"type": "image_url", "image_url": {"url": f"data:{p['media_type']};base64,{p['data']}"}})
    return out


async def _chat_completions(cfg: ProviderConfig, system: str, messages: list[dict[str, Any]], json_schema: dict[str, Any] | None) -> Completion:
    base = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")
    if cfg.kind == "openai_compatible" and json_schema is not None and _SCHEMA_SUPPORT.get(base, True):
        # Many compatible servers (vLLM, Ollama, LiteLLM...) enforce a JSON Schema too, which keeps
        # small models on the exact keys. Those that refuse it are remembered and get json_object.
        try:
            return await _chat_once(cfg, base, system, messages, json_schema, strict_schema=True)
        except _SchemaRejected:
            _SCHEMA_SUPPORT[base] = False
    return await _chat_once(cfg, base, system, messages, json_schema, strict_schema=cfg.kind == "openai")


class _SchemaRejected(Exception):
    pass


async def _chat_once(cfg: ProviderConfig, base: str, system: str, messages: list[dict[str, Any]], json_schema: dict[str, Any] | None,
                     strict_schema: bool) -> Completion:
    body: dict[str, Any] = {"model": cfg.model}
    body["max_completion_tokens" if cfg.kind == "openai" else "max_tokens"] = cfg.max_tokens
    if json_schema is not None:
        if strict_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "result", "schema": json_schema, "strict": True}}
        else:
            body["response_format"] = {"type": "json_object"}
        if cfg.kind != "openai":
            # Also in the prompt: servers that accept response_format but ignore the schema still follow it.
            schema_note = "Reply with one JSON object only, matching this JSON Schema:\n" + json.dumps(json_schema)
            system = f"{system}\n\n{schema_note}" if system else schema_note
    if cfg.temperature is not None:
        body["temperature"] = cfg.temperature
    if cfg.effort in _REASONING_EFFORTS:
        # Ollama maps this to its `think` switch: "none" turns Qwen3's thinking off.
        body["reasoning_effort"] = cfg.effort
    chat = [{"role": "system", "content": system}] if system else []
    chat += [{"role": m["role"], "content": _chat_content(m["content"])} for m in messages]
    body["messages"] = chat
    headers = {"content-type": "application/json"}
    if cfg.api_key:
        headers["authorization"] = f"Bearer {cfg.api_key}"
    try:
        async with httpx.AsyncClient(timeout=cfg.timeout) as client:
            resp = await client.post(f"{base}/chat/completions", headers=headers, json=body)
    except httpx.TimeoutException as exc:
        raise ProviderError(f"{base} took longer than {cfg.timeout:g} s to answer") from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"Could not reach {base}: {exc.__class__.__name__}") from exc
    if resp.status_code in (400, 422) and strict_schema and cfg.kind == "openai_compatible":
        raise _SchemaRejected()
    if resp.status_code >= 400:
        raise ProviderError(f"Provider error {resp.status_code}: {_error_message(resp)}")
    data = resp.json()
    try:
        choice = data["choices"][0]
        # Local reasoning models (Qwen3 on Ollama) may put their thinking in the answer.
        text = re.sub(r"<think>.*?</think>", "", choice["message"].get("content") or "", flags=re.S).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("The provider returned an unexpected response shape") from exc
    if choice.get("message", {}).get("refusal"):
        raise ProviderError(f"The model declined this request: {choice['message']['refusal']}")
    if choice.get("finish_reason") == "length" and json_schema is not None:
        raise IncompleteAnswer("The answer hit max_tokens before it was complete; raise max tokens for this task")
    usage = data.get("usage") or {}
    return Completion(
        text=text,
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
        raw_stop=choice.get("finish_reason"),
    )


@dataclass
class Embeddings:
    vectors: list[list[float]]
    input_tokens: int | None = None


_clients: dict[int, httpx.AsyncClient] = {}


def _embed_client() -> httpx.AsyncClient:
    """One client per event loop: a search embeds a query on every request, and a new client
    (its TLS setup) costs more than the embedding itself."""
    loop = id(asyncio.get_running_loop())
    client = _clients.get(loop)
    if client is None or client.is_closed:
        client = _clients[loop] = httpx.AsyncClient(timeout=60.0)
    return client


async def embed(cfg: ProviderConfig, texts: list[str]) -> Embeddings:
    """Vectors for texts, in the OpenAI /embeddings format (OpenAI, Ollama, LM Studio, most gateways)."""
    if cfg.kind not in ("openai", "openai_compatible"):
        raise ProviderError("This provider has no embeddings. Choose an OpenAI or OpenAI-compatible provider (e.g. local Ollama).")
    base = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")
    headers = {"content-type": "application/json"}
    if cfg.api_key:
        headers["authorization"] = f"Bearer {cfg.api_key}"
    try:
        resp = await _embed_client().post(f"{base}/embeddings", headers=headers, json={"model": cfg.model, "input": texts})
    except httpx.HTTPError as exc:
        raise ProviderError(f"Could not reach {base}: {exc.__class__.__name__}") from exc
    if resp.status_code >= 400:
        raise ProviderError(f"Provider error {resp.status_code}: {_error_message(resp)}")
    data = resp.json()
    try:
        rows = sorted(data["data"], key=lambda r: r.get("index", 0))
        vectors = [[float(x) for x in r["embedding"]] for r in rows]
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderError("The provider returned an unexpected embeddings shape") from exc
    if len(vectors) != len(texts):
        raise ProviderError("The provider returned the wrong number of embeddings")
    return Embeddings(vectors=vectors, input_tokens=(data.get("usage") or {}).get("prompt_tokens"))


def _error_message(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err)[:300]
        if err:
            return str(err)[:300]
    except ValueError:
        pass
    return resp.text[:300]


def parse_json(text: str) -> Any:
    """Parse a JSON answer, tolerating code fences or prose around it (compatible providers)."""
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except ValueError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except ValueError:
            pass
    raise IncompleteAnswer("The model did not return valid JSON")
