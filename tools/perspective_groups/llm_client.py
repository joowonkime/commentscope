"""OpenAI and OpenRouter structured-output clients; standard library only."""

import json
import os
import shlex
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = "openai/gpt-4.1-mini"
DEFAULT_OPENAI_MODEL = "gpt-6.2-sol"
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


class ModelError(RuntimeError):
    pass


def read_settings(path: Path = ROOT / ".env") -> dict[str, str]:
    """Read literal dotenv values without executing shell code; environment wins."""
    values = {}
    if path.exists():
        for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            name, sep, value = line.partition("=")
            if not sep or not name.strip().isidentifier():
                raise ValueError(f"Invalid .env assignment at line {line_number} (value hidden)")
            try:
                parts = shlex.split(value, comments=True, posix=True)
            except ValueError:
                raise ValueError(f"Invalid .env quoting at line {line_number} (value hidden)") from None
            values[name.strip()] = " ".join(parts)
    values.update(os.environ)
    return values


class OpenRouterClient:
    use_local_comment_ids = True
    provider = "openrouter"
    label = "OpenRouter"
    key_name = "OPENROUTER_API_KEY"
    endpoint = ENDPOINT

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        if not api_key.strip():
            raise ValueError(f"{self.key_name} is missing. Set it in .env or the environment.")
        self.api_key = api_key.strip()
        self.model = model
        self.requests = 0
        self._request_lock = threading.Lock()

    def structured(self, system: str, payload: dict, schema: dict, name: str) -> dict:
        body = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 10000,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": schema},
            },
            "provider": {"require_parameters": True},
        }
        result = self._post(body)
        try:
            choice = result["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ModelError("Model response incomplete/refused; try a smaller --batch-size.")
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ModelError("Model returned no structured text.")
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ModelError("Model output must be a JSON object.")
        except (KeyError, IndexError, TypeError, ValueError):
            raise ModelError("OpenRouter response has no valid structured result.") from None
        return {"data": data, "model": result.get("model", self.model), "usage": result.get("usage", {})}

    def _post(self, body: dict) -> dict:
        request = urllib.request.Request(
            self.endpoint, data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        for attempt in range(3):
            with self._request_lock:
                self.requests += 1
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    result = json.load(response)
                if not isinstance(result, dict):
                    raise ModelError(f"{self.label} returned a non-object response.")
                return result
            except urllib.error.HTTPError as exc:
                # Never log the request headers, key, or an arbitrary provider error body.
                exc.close()
                if (exc.code == 429 or exc.code >= 500) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise ModelError(f"{self.label} HTTP {exc.code}; check key, credits and model support.") from None
            except (urllib.error.URLError, TimeoutError):
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise ModelError(f"{self.label} connection failed; validated batches can be resumed.") from None
            except (ValueError, UnicodeError):
                raise ModelError(f"{self.label} returned invalid JSON.") from None
        raise ModelError(f"{self.label} request failed.")


class OpenAIClient(OpenRouterClient):
    provider = "openai"
    label = "OpenAI"
    key_name = "OPENAI_API_KEY"
    endpoint = "https://api.openai.com/v1/responses"

    def __init__(self, api_key: str, model: str = DEFAULT_OPENAI_MODEL, reasoning_effort: str = "medium"):
        super().__init__(api_key, model)
        if reasoning_effort not in ("low", "medium", "high"):
            raise ValueError("OPENAI_REASONING_EFFORT must be low, medium or high.")
        self.reasoning_effort = reasoning_effort

    def structured(self, system: str, payload: dict, schema: dict, name: str) -> dict:
        body = {
            "model": self.model,
            "input": [
                {"role": "developer", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "text": {"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}},
            "max_output_tokens": 16000,
            "store": False,
        }
        if self.model.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")):
            body["reasoning"] = {"effort": self.reasoning_effort}
        result = self._post(body)
        if result.get("status") != "completed":
            raise ModelError("OpenAI response incomplete/failed; try a smaller --batch-size.")
        try:
            texts = []
            for item in result["output"]:
                if item.get("type") != "message":
                    continue
                for content in item["content"]:
                    if content.get("type") == "refusal":
                        raise ModelError("OpenAI refused classification; no decisions were accepted.")
                    if content.get("type") == "output_text":
                        texts.append(content["text"])
            data = json.loads("".join(texts))
            if not isinstance(data, dict):
                raise ModelError("OpenAI structured result must be an object.")
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ModelError("OpenAI response has no valid structured result.") from None
        return {"data": data, "model": result.get("model", self.model), "usage": result.get("usage", {})}


def create_client(settings: dict, provider: str | None = None, model: str | None = None):
    selected = provider or settings.get("LLM_PROVIDER") or ("openai" if settings.get("OPENAI_API_KEY", "").strip() else "openrouter")
    if selected == "openai":
        chosen_model = model or settings.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
        if "/" in chosen_model:
            raise ValueError("OpenAI model IDs have no provider/ prefix. Example: gpt-6.2-sol.")
        return OpenAIClient(settings.get("OPENAI_API_KEY", ""), chosen_model,
                            settings.get("OPENAI_REASONING_EFFORT") or "medium")
    if selected == "openrouter":
        return OpenRouterClient(settings.get("OPENROUTER_API_KEY", ""), model or settings.get("OPENROUTER_MODEL") or DEFAULT_MODEL)
    raise ValueError("LLM_PROVIDER must be openai or openrouter.")
