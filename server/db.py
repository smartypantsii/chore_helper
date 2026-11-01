from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from server.config import DB_PATH, ensure_data_dir


class Base(DeclarativeBase):
    pass


engine = None
SessionLocal = None


def init_engine():
    global engine, SessionLocal
    ensure_data_dir()
    engine = create_engine(
        f"sqlite:///{DB_PATH}",
        connect_args={"check_same_thread": False},
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine


def migrate_schema(eng) -> None:
    """Widen existing SQLite tables for newer columns."""
    insp = inspect(eng)
    tables = insp.get_table_names()
    if "assignments" in tables:
        cols = {c["name"] for c in insp.get_columns("assignments")}
        if "stars" not in cols:
            with eng.begin() as conn:
                conn.execute(text("ALTER TABLE assignments ADD COLUMN stars INTEGER"))
        try:
            with eng.begin() as conn:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ux_assignment_day_chore "
                        "ON assignments(day, chore_id) WHERE state != 'cancelled'"
                    )
                )
        except OperationalError:
            pass
    if "ledger_entries" not in tables:
        return
    cols = {c["name"]: c for c in insp.get_columns("ledger_entries")}
    needs = "redemption_id" not in cols or not cols["assignment_id"]["nullable"]
    if not needs:
        return
    with eng.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE ledger_entries_v2 (
                    id INTEGER PRIMARY KEY,
                    child_id INTEGER NOT NULL,
                    assignment_id INTEGER,
                    redemption_id INTEGER,
                    stars INTEGER NOT NULL,
                    created_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO ledger_entries_v2
                    (id, child_id, assignment_id, redemption_id, stars, created_at)
                SELECT id, child_id, assignment_id, NULL, stars, created_at
                FROM ledger_entries
                """
            )
        )
        conn.execute(text("DROP TABLE ledger_entries"))
        conn.execute(text("ALTER TABLE ledger_entries_v2 RENAME TO ledger_entries"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_ledger_assignment "
                "ON ledger_entries(assignment_id) WHERE assignment_id IS NOT NULL"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_ledger_redemption "
                "ON ledger_entries(redemption_id) WHERE redemption_id IS NOT NULL"
            )
        )


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
