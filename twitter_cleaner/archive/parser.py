from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterator

import click


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
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise click.ClickException(
            f"Could not read {path.name}: file is not valid UTF-8.\n"
            "Re-download your Twitter archive and try again."
        )
    try:
        return json.loads(_strip_js_wrapper(text))
    except json.JSONDecodeError as e:
        raise click.ClickException(
            f"Could not parse {path.name}: invalid JSON at line {e.lineno}.\n"
            "The archive file may be corrupted. Re-download your Twitter archive and try again."
        )


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
        for i, entry in enumerate(entries):
            tweet = entry.get("tweet", entry)
            try:
                yield TweetRecord(
                    id=tweet["id"],
                    tweet_type=_classify(tweet),
                    text=tweet.get("full_text", ""),
                    created_at=tweet.get("created_at", ""),
                )
            except KeyError as e:
                raise click.ClickException(
                    f"Unrecognised format in {path.name} (entry {i}): missing field {e}.\n"
                    "Make sure you're using an official Twitter/X data export."
                )


def parse_likes(archive_dir: Path) -> Iterator[LikeRecord]:
    parts = sorted(archive_dir.glob("like*.js"))
    for path in parts:
        entries = _load_js_file(path)
        for i, entry in enumerate(entries):
            like = entry.get("like", entry)
            try:
                yield LikeRecord(
                    id=like["tweetId"],
                    text=like.get("fullText", ""),
                )
            except KeyError as e:
                raise click.ClickException(
                    f"Unrecognised format in {path.name} (entry {i}): missing field {e}.\n"
                    "Make sure you're using an official Twitter/X data export."
                )
