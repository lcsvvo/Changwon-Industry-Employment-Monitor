"""점검 업무 DB 스키마 마이그레이션(Alembic) 진입점.

- 새 DB: head 까지 migration 을 적용해 만든다(create_all 을 쓰지 않음).
- Alembic 도입 전 create_all 로 만든 DB(= baseline 구조, alembic_version 없음): baseline 과 구조가 같으면
  baseline 으로 stamp 한 뒤 head 까지 올린다. 구조가 다르면 멈추고 알린다.
"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

MIGRATIONS = Path(__file__).with_name("migrations")
BASELINE = "0001_baseline"
# baseline(Phase 4) 구조의 테이블 → 컬럼. create_all 로 만든 옛 DB 를 식별하는 데만 쓴다.
BASELINE_TABLES = {
    "candidate_reviews", "inspection_cases", "case_check_items", "case_decisions", "case_support_needs",
    "referrals", "quarterly_reviews", "requirement_cards", "audit_log",
}


class MigrationError(RuntimeError):
    pass


def config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def head_revision() -> str:
    return ScriptDirectory.from_config(config("sqlite://")).get_current_head()


def current_revision(engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def upgrade(engine, revision: str = "head") -> None:
    """engine 의 DB 를 revision 까지 올린다."""
    tables = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        cfg = config(str(engine.url))
        cfg.attributes["connection"] = conn
        if "alembic_version" not in tables and tables & BASELINE_TABLES:
            if tables - {"alembic_version"} != BASELINE_TABLES:
                raise MigrationError(f"Alembic 도입 전 DB 의 구조가 baseline 과 다릅니다: {sorted(tables)}")
            command.stamp(cfg, BASELINE)
        command.upgrade(cfg, revision)
