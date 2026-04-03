from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Protocol


class LLMClient(Protocol):
    def classify_batch(self, tweets: list[str], description: str) -> list[bool]:
        """Return a bool per tweet: True = matches description, False = skip."""
        ...


class OpenAIFilter:
    """Classify tweets using the OpenAI chat completions API."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._api_key = api_key
        self._model = model

    def classify_batch(self, tweets: list[str], description: str) -> list[bool]:
        results: list[bool] = []
        for tweet in tweets:
            results.append(self._classify_one(tweet, description))
        return results

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

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            answer = data["choices"][0]["message"]["content"].strip().lower()
            return answer.startswith("yes")
        except (urllib.error.URLError, KeyError, json.JSONDecodeError):
            return False


class AnthropicFilter:
    """Classify tweets using the Anthropic Messages API."""

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001") -> None:
        self._api_key = api_key
        self._model = model

    def classify_batch(self, tweets: list[str], description: str) -> list[bool]:
        results: list[bool] = []
        for tweet in tweets:
            results.append(self._classify_one(tweet, description))
        return results

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
        except (urllib.error.URLError, KeyError, json.JSONDecodeError):
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


def build_llm_filter(provider: str, api_key: str) -> LLMClient:
    provider = provider.lower()
    if provider == "openai":
        return OpenAIFilter(api_key)
    elif provider in ("anthropic", "claude"):
        return AnthropicFilter(api_key)
    raise ValueError(f"Unknown LLM provider: {provider!r}. Choose 'openai' or 'anthropic'.")
