"""Alembic 실행 환경 — 점검 업무 DB(workflow). 설정은 workflow.migrate 가 코드로 넘긴다."""
from alembic import context

from workflow.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        from sqlalchemy import create_engine
        connectable = create_engine(config.get_main_option("sqlalchemy.url"))
        with connectable.connect() as connection:
            _run(connection)
    else:
        _run(connectable)


def _run(connection) -> None:
    # SQLite 는 ALTER 가 제한적이므로 batch(테이블 재생성) 모드로 실행한다. PostgreSQL 은 일반 ALTER.
    context.configure(connection=connection, target_metadata=target_metadata,
                      render_as_batch=connection.dialect.name == "sqlite", compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("오프라인(SQL 출력) 모드는 사용하지 않습니다.")
run_migrations_online()
