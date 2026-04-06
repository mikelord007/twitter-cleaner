from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterator


class TweetType(str, Enum):
    TWEET = "tweet"
    REPLY = "reply"
    RETWEET = "retweet"
    QUOTE = "quote"


@dataclass
class TweetRecord:
    id: str
    tweet_type: TweetType
    text: str
    created_at: str


@dataclass
class LikeRecord:
    id: str
    text: str


def _strip_js_wrapper(text: str) -> str:
    return re.sub(r"^window\.YTD\.\w+\.part\d+\s*=\s*", "", text.strip())


def _load_js_file(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    return json.loads(_strip_js_wrapper(text))


def _classify(tweet: dict) -> TweetType:
    text = tweet.get("full_text", "")
    if text.startswith("RT @"):
        return TweetType.RETWEET
    # Explicit quote fields (present in some archive versions)
    is_quote = tweet.get("is_quote_status")
    if is_quote in ("true", True) or tweet.get("quoted_status_id") or tweet.get("quoted_status_id_str"):
        return TweetType.QUOTE
    # Fallback: quote tweets always embed a link to another tweet in their entities
    for url in tweet.get("entities", {}).get("urls", []):
        expanded = url.get("expanded_url", "")
        if ("/status/" in expanded) and ("twitter.com" in expanded or "x.com" in expanded):
            return TweetType.QUOTE
    if tweet.get("in_reply_to_user_id"):
        return TweetType.REPLY
    return TweetType.TWEET


def parse_tweets(archive_dir: Path) -> Iterator[TweetRecord]:
    # Discover all tweet part files: tweets.js, tweets-part1.js, etc.
    parts = sorted(archive_dir.glob("tweets*.js"))
    for path in parts:
        entries = _load_js_file(path)
        for entry in entries:
            tweet = entry.get("tweet", entry)
            yield TweetRecord(
                id=tweet["id"],
                tweet_type=_classify(tweet),
                text=tweet.get("full_text", ""),
                created_at=tweet.get("created_at", ""),
            )


def parse_likes(archive_dir: Path) -> Iterator[LikeRecord]:
    parts = sorted(archive_dir.glob("like*.js"))
    for path in parts:
        entries = _load_js_file(path)
        for entry in entries:
            like = entry.get("like", entry)
            yield LikeRecord(
                id=like["tweetId"],
                text=like.get("fullText", ""),
            )
