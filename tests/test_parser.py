from __future__ import annotations

import json
from pathlib import Path

import pytest
import click

from twitter_cleaner.archive.parser import (
    LikeRecord,
    TweetRecord,
    TweetType,
    _classify,
    _load_js_file,
    _strip_js_wrapper,
    parse_likes,
    parse_tweets,
)


# ---------------------------------------------------------------------------
# _strip_js_wrapper
# ---------------------------------------------------------------------------

class TestStripJsWrapper:
    def test_tweets_part0(self):
        raw = "window.YTD.tweets.part0 = [{...}]"
        assert _strip_js_wrapper(raw) == "[{...}]"

    def test_tweets_part1(self):
        raw = "window.YTD.tweets.part1 = []"
        assert _strip_js_wrapper(raw) == "[]"

    def test_like(self):
        raw = "window.YTD.like.part0 = []"
        assert _strip_js_wrapper(raw) == "[]"

    def test_no_wrapper(self):
        raw = '[{"tweet": {}}]'
        assert _strip_js_wrapper(raw) == raw

    def test_leading_whitespace(self):
        raw = "  window.YTD.tweets.part0 = []"
        assert _strip_js_wrapper(raw) == "[]"

    def test_arbitrary_varname(self):
        raw = "window.YTD.somedata.part99 = {}"
        assert _strip_js_wrapper(raw) == "{}"


# ---------------------------------------------------------------------------
# _load_js_file
# ---------------------------------------------------------------------------

class TestLoadJsFile:
    def test_valid(self, tmp_path):
        data = [{"tweet": {"id": "1"}}]
        p = tmp_path / "tweets.js"
        p.write_text(f"window.YTD.tweets.part0 = {json.dumps(data)}", encoding="utf-8")
        result = _load_js_file(p)
        assert result == data

    def test_raw_json_no_wrapper(self, tmp_path):
        data = [{"id": "1"}]
        p = tmp_path / "tweets.js"
        p.write_text(json.dumps(data), encoding="utf-8")
        assert _load_js_file(p) == data

    def test_invalid_json_raises(self, tmp_path):
        p = tmp_path / "tweets.js"
        p.write_text("window.YTD.tweets.part0 = {broken", encoding="utf-8")
        with pytest.raises(click.ClickException, match="invalid JSON"):
            _load_js_file(p)

    def test_unicode_error_raises(self, tmp_path):
        p = tmp_path / "tweets.js"
        p.write_bytes(b"\xff\xfe invalid")
        with pytest.raises(click.ClickException, match="not valid UTF-8"):
            _load_js_file(p)

    def test_empty_array(self, tmp_path):
        p = tmp_path / "tweets.js"
        p.write_text("window.YTD.tweets.part0 = []", encoding="utf-8")
        assert _load_js_file(p) == []


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_retweet(self):
        assert _classify({"full_text": "RT @someone: nice"}) == TweetType.RETWEET

    def test_plain_tweet(self):
        assert _classify({"full_text": "hello world", "entities": {"urls": []}}) == TweetType.TWEET

    def test_reply_via_user_id(self):
        t = {"full_text": "reply text", "in_reply_to_user_id": "456", "entities": {"urls": []}}
        assert _classify(t) == TweetType.REPLY

    def test_quote_via_is_quote_status_string(self):
        t = {"full_text": "my take", "is_quote_status": "true", "entities": {"urls": []}}
        assert _classify(t) == TweetType.QUOTE

    def test_quote_via_is_quote_status_bool(self):
        t = {"full_text": "my take", "is_quote_status": True, "entities": {"urls": []}}
        assert _classify(t) == TweetType.QUOTE

    def test_quote_via_quoted_status_id(self):
        t = {"full_text": "quote", "quoted_status_id": "999", "entities": {"urls": []}}
        assert _classify(t) == TweetType.QUOTE

    def test_quote_via_quoted_status_id_str(self):
        t = {"full_text": "quote", "quoted_status_id_str": "999", "entities": {"urls": []}}
        assert _classify(t) == TweetType.QUOTE

    def test_quote_via_twitter_url(self):
        t = {
            "full_text": "check this",
            "entities": {"urls": [{"expanded_url": "https://twitter.com/user/status/123"}]},
        }
        assert _classify(t) == TweetType.QUOTE

    def test_quote_via_x_url(self):
        t = {
            "full_text": "check this",
            "entities": {"urls": [{"expanded_url": "https://x.com/user/status/123"}]},
        }
        assert _classify(t) == TweetType.QUOTE

    def test_non_status_url_is_not_quote(self):
        t = {
            "full_text": "check this",
            "entities": {"urls": [{"expanded_url": "https://example.com/page"}]},
        }
        assert _classify(t) == TweetType.TWEET

    def test_reply_takes_precedence_over_plain_when_no_quote(self):
        t = {
            "full_text": "hi",
            "in_reply_to_user_id": "1",
            "is_quote_status": "false",
            "entities": {"urls": []},
        }
        assert _classify(t) == TweetType.REPLY

    def test_missing_entities_key(self):
        # entities may be absent
        assert _classify({"full_text": "hello"}) == TweetType.TWEET

    def test_rt_prefix_wins_over_quote_fields(self):
        t = {"full_text": "RT @other: text", "is_quote_status": True}
        assert _classify(t) == TweetType.RETWEET


# ---------------------------------------------------------------------------
# parse_tweets
# ---------------------------------------------------------------------------

class TestParseTweets:
    def _write(self, path: Path, varname: str, entries: list) -> None:
        path.write_text(
            f"window.YTD.{varname}.part0 = {json.dumps(entries)}", encoding="utf-8"
        )

    def test_basic_parse(self, archive_dir):
        entries = [
            {"tweet": {"id": "10", "full_text": "hello", "created_at": "Mon Jan 01 00:00:00 +0000 2022", "entities": {"urls": []}}}
        ]
        self._write(archive_dir / "tweets.js", "tweets", entries)
        records = list(parse_tweets(archive_dir))
        assert len(records) == 1
        assert records[0].id == "10"
        assert records[0].tweet_type == TweetType.TWEET
        assert records[0].text == "hello"

    def test_retweet_classified(self, archive_dir):
        entries = [
            {"tweet": {"id": "20", "full_text": "RT @x: text", "created_at": "", "entities": {}}}
        ]
        self._write(archive_dir / "tweets.js", "tweets", entries)
        assert list(parse_tweets(archive_dir))[0].tweet_type == TweetType.RETWEET

    def test_multiple_part_files(self, archive_dir):
        e1 = [{"tweet": {"id": "1", "full_text": "a", "created_at": "", "entities": {}}}]
        e2 = [{"tweet": {"id": "2", "full_text": "b", "created_at": "", "entities": {}}}]
        (archive_dir / "tweets.js").write_text(
            f"window.YTD.tweets.part0 = {json.dumps(e1)}", encoding="utf-8"
        )
        (archive_dir / "tweets-part1.js").write_text(
            f"window.YTD.tweets.part1 = {json.dumps(e2)}", encoding="utf-8"
        )
        ids = [r.id for r in parse_tweets(archive_dir)]
        assert set(ids) == {"1", "2"}

    def test_entry_without_tweet_wrapper(self, archive_dir):
        # Some archive versions omit the {"tweet": {...}} wrapper
        entries = [{"id": "30", "full_text": "direct", "created_at": "", "entities": {}}]
        self._write(archive_dir / "tweets.js", "tweets", entries)
        records = list(parse_tweets(archive_dir))
        assert records[0].id == "30"

    def test_missing_id_field_raises(self, archive_dir):
        entries = [{"tweet": {"full_text": "no id", "created_at": ""}}]
        self._write(archive_dir / "tweets.js", "tweets", entries)
        with pytest.raises(click.ClickException, match="missing field"):
            list(parse_tweets(archive_dir))

    def test_no_tweet_files_yields_nothing(self, archive_dir):
        assert list(parse_tweets(archive_dir)) == []

    def test_empty_file_yields_nothing(self, archive_dir):
        self._write(archive_dir / "tweets.js", "tweets", [])
        assert list(parse_tweets(archive_dir)) == []

    def test_missing_created_at_defaults_empty(self, archive_dir):
        entries = [{"tweet": {"id": "5", "full_text": "hi", "entities": {}}}]
        self._write(archive_dir / "tweets.js", "tweets", entries)
        records = list(parse_tweets(archive_dir))
        assert records[0].created_at == ""


# ---------------------------------------------------------------------------
# parse_likes
# ---------------------------------------------------------------------------

class TestParseLikes:
    def _write_like(self, path: Path, entries: list) -> None:
        path.write_text(
            f"window.YTD.like.part0 = {json.dumps(entries)}", encoding="utf-8"
        )

    def test_basic_like(self, archive_dir):
        entries = [{"like": {"tweetId": "77", "fullText": "liked text"}}]
        self._write_like(archive_dir / "like.js", entries)
        records = list(parse_likes(archive_dir))
        assert len(records) == 1
        assert records[0].id == "77"
        assert records[0].text == "liked text"

    def test_missing_tweet_id_raises(self, archive_dir):
        entries = [{"like": {"fullText": "no id"}}]
        self._write_like(archive_dir / "like.js", entries)
        with pytest.raises(click.ClickException, match="missing field"):
            list(parse_likes(archive_dir))

    def test_no_like_files_yields_nothing(self, archive_dir):
        assert list(parse_likes(archive_dir)) == []

    def test_multiple_like_parts(self, archive_dir):
        e1 = [{"like": {"tweetId": "1", "fullText": "a"}}]
        e2 = [{"like": {"tweetId": "2", "fullText": "b"}}]
        (archive_dir / "like.js").write_text(
            f"window.YTD.like.part0 = {json.dumps(e1)}", encoding="utf-8"
        )
        (archive_dir / "like-part1.js").write_text(
            f"window.YTD.like.part1 = {json.dumps(e2)}", encoding="utf-8"
        )
        ids = {r.id for r in parse_likes(archive_dir)}
        assert ids == {"1", "2"}

    def test_missing_full_text_defaults_empty(self, archive_dir):
        entries = [{"like": {"tweetId": "88"}}]
        self._write_like(archive_dir / "like.js", entries)
        records = list(parse_likes(archive_dir))
        assert records[0].text == ""
