"""Schema bootstrap: creates the database and all tables if they do not exist."""

import logging
import re

from src.db.connection import DB_NAME, fun_get_server_connection

logger = logging.getLogger(__name__)

# Guard against SQL injection via a misconfigured DB_NAME environment variable.
if not re.fullmatch(r"[a-zA-Z0-9_]+", DB_NAME):
    raise ValueError(f"DB_NAME contains invalid characters: {DB_NAME!r}")

CREATE_DATABASE = (
    f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
)

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id            INT           NOT NULL AUTO_INCREMENT,
    username      VARCHAR(64)   NOT NULL,
    email         VARCHAR(255)  NOT NULL,
    phone         VARCHAR(20)   NOT NULL,
    password_hash VARCHAR(255)  NOT NULL,
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_username (username),
    UNIQUE KEY uq_users_email    (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

CREATE_ACCOUNTS = """
CREATE TABLE IF NOT EXISTS accounts (
    id             INT            NOT NULL AUTO_INCREMENT,
    user_id        INT            NOT NULL,
    account_number VARCHAR(20)    NOT NULL,
    balance        DECIMAL(15, 2) NOT NULL DEFAULT 0.00,
    created_at     DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_accounts_user_id        (user_id),
    UNIQUE KEY uq_accounts_account_number (account_number),
    CONSTRAINT fk_accounts_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

CREATE_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS transactions (
    id            INT            NOT NULL AUTO_INCREMENT,
    account_id    INT            NOT NULL,
    type          ENUM('CREDIT', 'DEBIT') NOT NULL,
    amount        DECIMAL(15, 2) NOT NULL,
    category      VARCHAR(64)    NULL,
    note          VARCHAR(255)   NULL,
    created_at    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    balance_after DECIMAL(15, 2) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_transactions_account FOREIGN KEY (account_id) REFERENCES accounts (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

ALL_TABLES = [
    ("users", CREATE_USERS),
    ("accounts", CREATE_ACCOUNTS),
    ("transactions", CREATE_TRANSACTIONS),
]


def fun_init_schema():
    """Create the database and all tables if they do not already exist.

    Creates the database named by DB_NAME, then creates users, accounts,
    and transactions tables in dependency order.

    Returns:
        None
    """
    conn = fun_get_server_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(CREATE_DATABASE)
        cursor.execute(f"USE `{DB_NAME}`")
        for table_name, ddl in ALL_TABLES:
            cursor.execute(ddl)
            logger.info("Table ready: %s", table_name)
    finally:
        cursor.close()
        conn.close()


def fun_get_existing_tables():
    """Return a list of table names that currently exist in the database.

    Returns:
        list[str]: table names present in DB_NAME.
    """
    conn = fun_get_server_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(CREATE_DATABASE)
        cursor.execute(f"USE `{DB_NAME}`")
        cursor.execute("SHOW TABLES")
        return [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fun_init_schema()
    tables = fun_get_existing_tables()
    print("Tables in database:", tables)
