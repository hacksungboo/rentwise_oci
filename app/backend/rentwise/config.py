from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    # 운영: oracle+oracledb://user:pw@db:1521/?service_name=FREEPDB1 / 로컬·테스트: sqlite:///./dev.db
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite:///./rentwise-dev.db"))
    db_wait_seconds: int = field(default_factory=lambda: int(_env("DB_WAIT_SECONDS", "0")))
    engine_mode: str = field(default_factory=lambda: _env("ENGINE_MODE", "mock"))
    session_secret: str = field(default_factory=lambda: _env("SESSION_SECRET", "dev-only-change-me"))
    cookie_secure: bool = field(default_factory=lambda: _env("COOKIE_SECURE", "false").lower() == "true")
    allowed_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        o.strip() for o in _env("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:4173,http://localhost:8080,http://127.0.0.1:8080").split(",") if o.strip()))
    # 데모 계정: "아이디:비밀번호:역할:이름:직원ID" 를 ; 로 구분
    demo_accounts: str = field(default_factory=lambda: _env(
        "DEMO_ACCOUNTS",
        "admin:rentwise2026:ADMIN:운영책임자:;e1:rentwise2026:STAFF:김현우:E1;"
        "e2:rentwise2026:STAFF:이서연:E2;e3:rentwise2026:STAFF:박준호:E3"))
    seed_path: Path = field(default_factory=lambda: Path(_env(
        "SEED_PATH", str(Path(__file__).resolve().parents[2] / "fixtures" / "v1" / "seed.json"))))
    auto_seed: bool = field(default_factory=lambda: _env("AUTO_SEED", "true").lower() == "true")
    build_sha: str = field(default_factory=lambda: _env("BUILD_SHA", "local"))
    image_tag: str = field(default_factory=lambda: _env("IMAGE_TAG", "local"))
    server_label: str = field(default_factory=lambda: _env("SERVER_LABEL", ""))


settings = Settings()
