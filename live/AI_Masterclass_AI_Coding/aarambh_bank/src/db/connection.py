"""Database connection module. Reads MySQL config from environment variables.

Fails fast if security-critical variables (DB_USER, DB_PASSWORD) are absent.
"""

import os

import mysql.connector
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "aarambh_bank")

# Fail fast: do not silently fall back to empty credentials.
DB_USER = os.environ.get("DB_USER")
DB_PASSWORD = os.environ.get("DB_PASSWORD")

if DB_USER is None:
    raise RuntimeError("DB_USER environment variable is not set. Check your .env file.")
if DB_PASSWORD is None:
    raise RuntimeError("DB_PASSWORD environment variable is not set. Check your .env file.")


def fun_get_connection():
    """Return a new MySQL connection using environment-variable config.

    Returns:
        mysql.connector.connection.MySQLConnection: open connection to the database.
    """
    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        autocommit=False,
    )


def fun_get_server_connection():
    """Return a MySQL connection without selecting a database (used for schema bootstrap).

    Returns:
        mysql.connector.connection.MySQLConnection: server-level connection.
    """
    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        autocommit=True,
    )
