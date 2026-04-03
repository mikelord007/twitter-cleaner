from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    username: str = field(default_factory=lambda: os.environ.get("TWITTER_USERNAME", ""))
    password: str = field(default_factory=lambda: os.environ.get("TWITTER_PASSWORD", ""))
    totp_secret: str = field(default_factory=lambda: os.environ.get("TWITTER_TOTP_SECRET", ""))

    archive_dir: Path = Path("data")
    state_dir: Path = Path(".twitter_cleaner")

    headless: bool = True
    dry_run: bool = False
    min_delay: float = 3.0
    max_delay: float = 6.0

    @property
    def session_file(self) -> Path:
        return self.state_dir / "session.json"

    @property
    def db_file(self) -> Path:
        return self.state_dir / "progress.db"

    def ensure_state_dir(self) -> None:
        self.state_dir.mkdir(exist_ok=True)

    def validate(self) -> None:
        if not self.username:
            raise ValueError("TWITTER_USERNAME is not set")
        if not self.password:
            raise ValueError("TWITTER_PASSWORD is not set")
