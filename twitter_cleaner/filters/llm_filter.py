from __future__ import annotations

import json
import urllib.error
import urllib.request
import warnings
from typing import Protocol

import click


class LLMClient(Protocol):
    def classify_batch(self, tweets: list[str], description: str) -> list[bool]:
        """Return a bool per tweet: True = matches description, False = skip."""
        ...


class _OpenAICompatibleFilter:
    """Base for any provider that speaks the OpenAI chat completions API."""

    _base_url: str
    _default_model: str

    def __init__(self, api_key: str, model: str | None = None) -> None:
        self._api_key = api_key
        self._model = model or self._default_model

    def _extra_headers(self) -> dict[str, str]:
        return {}

    def classify_batch(self, tweets: list[str], description: str) -> list[bool]:
        return [self._classify_one(tweet, description) for tweet in tweets]

    def _classify_one(self, tweet: str, description: str) -> bool:
        prompt = (
            f"Does the following tweet match this description: \"{description}\"?\n\n"
            f"Tweet: {tweet}\n\n"
            "Answer with only 'yes' or 'no'."
        )
        payload = json.dumps({
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 5,
            "temperature": 0,
        }).encode()

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            **self._extra_headers(),
        }
        req = urllib.request.Request(self._base_url, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            answer = data["choices"][0]["message"]["content"].strip().lower()
            return answer.startswith("yes")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise click.ClickException(
                    f"LLM API authentication failed (401).\n"
                    f"Check that your API key is correct and has not expired."
                )
            if e.code == 429:
                warnings.warn(
                    "LLM API rate limit hit (429) — tweet will be skipped. "
                    "Slow down or upgrade your API plan.",
                    stacklevel=2,
                )
                return False
            warnings.warn(f"LLM API error {e.code}: {e.reason} — tweet will be skipped.", stacklevel=2)
            return False
        except urllib.error.URLError as e:
            warnings.warn(f"LLM API unreachable: {e.reason} — tweet will be skipped.", stacklevel=2)
            return False
        except (KeyError, json.JSONDecodeError) as e:
            warnings.warn(f"LLM API response unexpected format: {e} — tweet will be skipped.", stacklevel=2)
            return False


class OpenAIFilter(_OpenAICompatibleFilter):
    """OpenAI chat completions API."""
    _base_url = "https://api.openai.com/v1/chat/completions"
    _default_model = "gpt-4o-mini"


class OpenRouterFilter(_OpenAICompatibleFilter):
    """OpenRouter — gives access to hundreds of models with one API key."""
    _base_url = "https://openrouter.ai/api/v1/chat/completions"
    _default_model = "meta-llama/llama-3.1-8b-instruct:free"

    def _extra_headers(self) -> dict[str, str]:
        return {"X-Title": "twtr-cleaner"}


class AnthropicFilter:
    """Anthropic Messages API."""

    _default_model = "claude-haiku-4-5-20251001"

    def __init__(self, api_key: str, model: str | None = None) -> None:
        self._api_key = api_key
        self._model = model or self._default_model

    def classify_batch(self, tweets: list[str], description: str) -> list[bool]:
        return [self._classify_one(tweet, description) for tweet in tweets]

    def _classify_one(self, tweet: str, description: str) -> bool:
        prompt = (
            f"Does the following tweet match this description: \"{description}\"?\n\n"
            f"Tweet: {tweet}\n\n"
            "Answer with only 'yes' or 'no'."
        )
        payload = json.dumps({
            "model": self._model,
            "max_tokens": 5,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            answer = data["content"][0]["text"].strip().lower()
            return answer.startswith("yes")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise click.ClickException(
                    "Anthropic API authentication failed (401).\n"
                    "Check that your ANTHROPIC_API_KEY is correct and has not expired."
                )
            if e.code == 429:
                warnings.warn(
                    "Anthropic API rate limit hit (429) — tweet will be skipped.",
                    stacklevel=2,
                )
                return False
            warnings.warn(f"Anthropic API error {e.code}: {e.reason} — tweet will be skipped.", stacklevel=2)
            return False
        except urllib.error.URLError as e:
            warnings.warn(f"Anthropic API unreachable: {e.reason} — tweet will be skipped.", stacklevel=2)
            return False
        except (KeyError, json.JSONDecodeError) as e:
            warnings.warn(f"Anthropic API response unexpected format: {e} — tweet will be skipped.", stacklevel=2)
            return False


class KeywordFilter:
    """Simple keyword/substring filter — no API needed."""

    def __init__(self, keywords: list[str]) -> None:
        self._keywords = [k.lower() for k in keywords]

    def classify_batch(self, tweets: list[str], description: str) -> list[bool]:
        return [
            any(kw in tweet.lower() for kw in self._keywords)
            for tweet in tweets
        ]


def build_llm_filter(provider: str, api_key: str, model: str | None = None) -> LLMClient:
    provider = provider.lower()
    if provider == "openai":
        return OpenAIFilter(api_key, model)
    elif provider in ("anthropic", "claude"):
        return AnthropicFilter(api_key, model)
    elif provider == "openrouter":
        return OpenRouterFilter(api_key, model)
    raise ValueError(f"Unknown LLM provider: {provider!r}. Choose 'openai', 'anthropic', or 'openrouter'.")
