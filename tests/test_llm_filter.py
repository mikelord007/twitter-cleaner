from __future__ import annotations

import json
import urllib.error
import urllib.request
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
import click

from twitter_cleaner.filters.llm_filter import (
    AnthropicFilter,
    KeywordFilter,
    OpenAIFilter,
    OpenRouterFilter,
    build_llm_filter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_ctx(body: bytes) -> MagicMock:
    m = MagicMock()
    m.read.return_value = body
    m.__enter__ = lambda s: s
    m.__exit__ = MagicMock(return_value=False)
    return m


def _openai_resp(answer: str) -> MagicMock:
    body = json.dumps({"choices": [{"message": {"content": answer}}]}).encode()
    return _mock_ctx(body)


def _anthropic_resp(answer: str) -> MagicMock:
    body = json.dumps({"content": [{"text": answer}]}).encode()
    return _mock_ctx(body)


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url="", code=code, msg="err", hdrs=None, fp=BytesIO())


# ---------------------------------------------------------------------------
# KeywordFilter
# ---------------------------------------------------------------------------

class TestKeywordFilter:
    def test_match(self):
        assert KeywordFilter(["crypto"]).classify_batch(["buy crypto now"], "") == [True]

    def test_no_match(self):
        assert KeywordFilter(["crypto"]).classify_batch(["good morning"], "") == [False]

    def test_case_insensitive(self):
        assert KeywordFilter(["Crypto"]).classify_batch(["CRYPTO moon"], "") == [True]

    def test_multiple_keywords_any_match(self):
        f = KeywordFilter(["nft", "crypto"])
        assert f.classify_batch(["buy an nft"], "") == [True]
        assert f.classify_batch(["crypto only"], "") == [True]

    def test_batch_mixed(self):
        f = KeywordFilter(["nft"])
        assert f.classify_batch(["nft drop", "good morning", "nft sale"], "") == [True, False, True]

    def test_empty_keywords_never_match(self):
        assert KeywordFilter([]).classify_batch(["anything"], "") == [False]

    def test_empty_tweet_text(self):
        assert KeywordFilter(["hi"]).classify_batch([""], "") == [False]

    def test_description_param_ignored(self):
        # description is unused by KeywordFilter — should not error
        KeywordFilter(["x"]).classify_batch(["x"], "some description")

    def test_partial_word_match(self):
        # substring match — "crypto" inside "cryptocurrency"
        assert KeywordFilter(["crypto"]).classify_batch(["cryptocurrency"], "") == [True]

    def test_empty_batch(self):
        assert KeywordFilter(["x"]).classify_batch([], "") == []


# ---------------------------------------------------------------------------
# OpenAIFilter
# ---------------------------------------------------------------------------

class TestOpenAIFilter:
    def _f(self, model=None):
        return OpenAIFilter("fake-key", model=model)

    def test_yes(self):
        with patch("urllib.request.urlopen", return_value=_openai_resp("yes")):
            assert self._f().classify_batch(["tweet"], "desc") == [True]

    def test_no(self):
        with patch("urllib.request.urlopen", return_value=_openai_resp("no")):
            assert self._f().classify_batch(["tweet"], "desc") == [False]

    def test_yes_with_trailing_text(self):
        with patch("urllib.request.urlopen", return_value=_openai_resp("Yes, absolutely.")):
            assert self._f().classify_batch(["tweet"], "desc") == [True]

    def test_uppercase_yes(self):
        with patch("urllib.request.urlopen", return_value=_openai_resp("YES")):
            assert self._f().classify_batch(["tweet"], "desc") == [True]

    def test_401_raises_click_exception(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(401)):
            with pytest.raises(click.ClickException, match="authentication failed"):
                self._f().classify_batch(["t"], "d")

    def test_429_warns_and_skips(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(429)):
            with pytest.warns(UserWarning, match="rate limit"):
                assert self._f().classify_batch(["t"], "d") == [False]

    def test_500_warns_and_skips(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(500)):
            with pytest.warns(UserWarning):
                assert self._f().classify_batch(["t"], "d") == [False]

    def test_url_error_warns_and_skips(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            with pytest.warns(UserWarning, match="unreachable"):
                assert self._f().classify_batch(["t"], "d") == [False]

    def test_bad_json_warns_and_skips(self):
        with patch("urllib.request.urlopen", return_value=_mock_ctx(b"not-json")):
            with pytest.warns(UserWarning, match="unexpected format"):
                assert self._f().classify_batch(["t"], "d") == [False]

    def test_missing_choices_key_warns_and_skips(self):
        body = json.dumps({"error": "oops"}).encode()
        with patch("urllib.request.urlopen", return_value=_mock_ctx(body)):
            with pytest.warns(UserWarning, match="unexpected format"):
                assert self._f().classify_batch(["t"], "d") == [False]

    def test_default_model(self):
        assert OpenAIFilter("k")._model == "gpt-4o-mini"

    def test_custom_model(self):
        assert OpenAIFilter("k", model="gpt-4o")._model == "gpt-4o"

    def test_sends_bearer_auth_header(self):
        captured = []

        def fake_open(req, timeout=None):
            captured.append(req)
            return _openai_resp("no")

        with patch("urllib.request.urlopen", side_effect=fake_open):
            self._f().classify_batch(["tweet"], "desc")

        assert captured[0].get_header("Authorization") == "Bearer fake-key"

    def test_sends_content_type_json(self):
        captured = []

        def fake_open(req, timeout=None):
            captured.append(req)
            return _openai_resp("no")

        with patch("urllib.request.urlopen", side_effect=fake_open):
            self._f().classify_batch(["tweet"], "desc")

        assert captured[0].get_header("Content-type") == "application/json"

    def test_batch_makes_one_call_per_tweet(self):
        call_count = [0]

        def fake_open(req, timeout=None):
            call_count[0] += 1
            return _openai_resp("no")

        with patch("urllib.request.urlopen", side_effect=fake_open):
            self._f().classify_batch(["a", "b", "c"], "d")

        assert call_count[0] == 3


# ---------------------------------------------------------------------------
# OpenRouterFilter
# ---------------------------------------------------------------------------

class TestOpenRouterFilter:
    def test_yes(self):
        with patch("urllib.request.urlopen", return_value=_openai_resp("yes")):
            assert OpenRouterFilter("k").classify_batch(["t"], "d") == [True]

    def test_sends_x_title_header(self):
        captured = []

        def fake_open(req, timeout=None):
            captured.append(req)
            return _openai_resp("no")

        with patch("urllib.request.urlopen", side_effect=fake_open):
            OpenRouterFilter("k").classify_batch(["t"], "d")

        assert captured[0].get_header("X-title") == "twitter-cleaner"

    def test_default_model_contains_llama(self):
        assert "llama" in OpenRouterFilter("k")._model.lower()

    def test_uses_openrouter_base_url(self):
        assert "openrouter.ai" in OpenRouterFilter._base_url

    def test_401_raises(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(401)):
            with pytest.raises(click.ClickException, match="authentication failed"):
                OpenRouterFilter("k").classify_batch(["t"], "d")


# ---------------------------------------------------------------------------
# AnthropicFilter
# ---------------------------------------------------------------------------

class TestAnthropicFilter:
    def _f(self):
        return AnthropicFilter("fake-key")

    def test_yes(self):
        with patch("urllib.request.urlopen", return_value=_anthropic_resp("yes")):
            assert self._f().classify_batch(["t"], "d") == [True]

    def test_no(self):
        with patch("urllib.request.urlopen", return_value=_anthropic_resp("no")):
            assert self._f().classify_batch(["t"], "d") == [False]

    def test_yes_uppercase(self):
        with patch("urllib.request.urlopen", return_value=_anthropic_resp("Yes.")):
            assert self._f().classify_batch(["t"], "d") == [True]

    def test_401_raises_with_anthropic_message(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(401)):
            with pytest.raises(click.ClickException, match="ANTHROPIC_API_KEY"):
                self._f().classify_batch(["t"], "d")

    def test_429_warns_and_skips(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(429)):
            with pytest.warns(UserWarning):
                assert self._f().classify_batch(["t"], "d") == [False]

    def test_url_error_warns_and_skips(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no network")):
            with pytest.warns(UserWarning, match="unreachable"):
                assert self._f().classify_batch(["t"], "d") == [False]

    def test_bad_json_warns_and_skips(self):
        with patch("urllib.request.urlopen", return_value=_mock_ctx(b"{}")):
            with pytest.warns(UserWarning, match="unexpected format"):
                assert self._f().classify_batch(["t"], "d") == [False]

    def test_default_model_contains_haiku(self):
        assert "haiku" in AnthropicFilter("k")._model.lower()

    def test_sends_api_key_header(self):
        captured = []

        def fake_open(req, timeout=None):
            captured.append(req)
            return _anthropic_resp("no")

        with patch("urllib.request.urlopen", side_effect=fake_open):
            self._f().classify_batch(["tweet"], "desc")

        assert captured[0].get_header("X-api-key") == "fake-key"


# ---------------------------------------------------------------------------
# build_llm_filter factory
# ---------------------------------------------------------------------------

class TestBuildLlmFilter:
    def test_openai(self):
        assert isinstance(build_llm_filter("openai", "k"), OpenAIFilter)

    def test_anthropic(self):
        assert isinstance(build_llm_filter("anthropic", "k"), AnthropicFilter)

    def test_claude_alias(self):
        assert isinstance(build_llm_filter("claude", "k"), AnthropicFilter)

    def test_openrouter(self):
        assert isinstance(build_llm_filter("openrouter", "k"), OpenRouterFilter)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            build_llm_filter("gemini", "k")

    def test_case_insensitive_openai(self):
        assert isinstance(build_llm_filter("OpenAI", "k"), OpenAIFilter)

    def test_case_insensitive_anthropic(self):
        assert isinstance(build_llm_filter("ANTHROPIC", "k"), AnthropicFilter)

    def test_passes_model_to_filter(self):
        f = build_llm_filter("openai", "k", model="gpt-4o")
        assert f._model == "gpt-4o"

    def test_default_model_when_none(self):
        f = build_llm_filter("openai", "k", model=None)
        assert f._model == "gpt-4o-mini"
