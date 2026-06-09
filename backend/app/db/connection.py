"""Postgres connection helpers."""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from app.core.config import settings


def connect() -> psycopg.Connection:
    return psycopg.connect(settings.database_url, row_factory=dict_row)


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    with connect() as conn:
        with conn.transaction():
            yield conn
