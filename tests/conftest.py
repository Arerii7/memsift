from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from memsift import db
from memsift.config import Config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture()
def cfg(home: Path) -> Config:
    config = Config(home=home)
    config.ensure_dirs()
    config.save()
    return config


@pytest.fixture()
def conn(cfg: Config):
    connection = db.connect(cfg.db_path)
    yield connection
    connection.close()


@pytest.fixture()
def dirty_project(tmp_path: Path) -> Path:
    target = tmp_path / "dirty"
    shutil.copytree(FIXTURES / "dirty", target)
    return target


@pytest.fixture()
def clean_project(tmp_path: Path) -> Path:
    target = tmp_path / "clean"
    shutil.copytree(FIXTURES / "clean", target)
    return target


@pytest.fixture()
def opencode_db(tmp_path: Path) -> Path:
    return make_opencode_db(tmp_path / "opencode.db")


def make_opencode_db(path: Path) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE session_v2 (
            id TEXT PRIMARY KEY,
            directory TEXT NOT NULL,
            title TEXT,
            time_created INTEGER NOT NULL
        );
        CREATE TABLE session_message (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            type TEXT NOT NULL,
            seq INTEGER NOT NULL,
            time_created INTEGER NOT NULL,
            data TEXT NOT NULL
        );
        """
    )
    connection.execute(
        "INSERT INTO session_v2 VALUES (?, ?, ?, ?)",
        ("ses_one", "/tmp/project", "Test session", 1_700_000_000_000),
    )
    messages = [
        (
            "msg_user",
            "ses_one",
            "user",
            1,
            1_700_000_001_000,
            '{"text":"remember: Use Postgres for the database.\\nThe weather is nice."}',
        ),
        (
            "msg_assistant",
            "ses_one",
            "assistant",
            2,
            1_700_000_002_000,
            '{"content":[{"type":"text","text":"Decision: use SQLite.\\nremember: Auth is Clerk."},'
            '{"type":"tool","name":"read"}]}',
        ),
        (
            "msg_other",
            "ses_two",
            "user",
            3,
            1_700_000_003_000,
            '{"text":"remember: This belongs to another project."}',
        ),
    ]
    connection.executemany(
        "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?)",
        messages,
    )
    connection.execute(
        "INSERT INTO session_v2 VALUES (?, ?, ?, ?)",
        ("ses_two", "/tmp/other", "Other", 1_700_000_000_000),
    )
    connection.commit()
    connection.close()
    return path
