"""Statement feature: filtered transaction history and CSV export.

Satisfies specs/statement.md AC-1 through AC-5.
"""

import csv
import io
import logging
from datetime import date
from decimal import Decimal

from src.db.connection import fun_get_connection

logger = logging.getLogger(__name__)


def fun_get_statement(
    account_id: int,
    from_date: date | None = None,
    to_date: date | None = None,
    tx_type: str | None = None,
) -> dict:
    """Return filtered transaction history for an account, newest first.

    Supports optional filtering by date range (inclusive) and by transaction
    type. Returns an error dict when from_date > to_date. All money fields
    are Decimal. Only transactions belonging to the given account_id are
    returned (user-scoped). Satisfies AC-1, AC-2, AC-3, AC-5.

    Args:
        account_id: Primary key of the account whose history to retrieve.
        from_date:  Inclusive lower bound on the transaction date (optional).
        to_date:    Inclusive upper bound on the transaction date (optional).
        tx_type:    'CREDIT', 'DEBIT', or None to return all types (optional).

    Returns:
        dict: {"ok": True, "rows": list[dict]}   on success.
              Each row has: type, amount (Decimal), category, note,
                            created_at (datetime), balance_after (Decimal).
              {"ok": False, "error": str}          on validation error.
    """
    if from_date is not None and to_date is not None and from_date > to_date:
        return {
            "ok": False,
            "error": "Invalid date range: from date must not be after to date.",
        }

    conditions = ["account_id = %s"]
    params: list = [account_id]

    if from_date is not None:
        conditions.append("DATE(created_at) >= %s")
        params.append(from_date)
    if to_date is not None:
        conditions.append("DATE(created_at) <= %s")
        params.append(to_date)
    if tx_type is not None:
        conditions.append("type = %s")
        params.append(tx_type)

    where_clause = " AND ".join(conditions)
    sql = (
        "SELECT type, amount, category, note, created_at, balance_after "
        f"FROM transactions WHERE {where_clause} "
        "ORDER BY created_at DESC, id DESC"
    )

    try:
        conn = fun_get_connection()
    except Exception as exc:
        logger.error("DB connection error in statement: %s", type(exc).__name__)
        return {"ok": False, "error": "Service unavailable. Please try again."}

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    except Exception as exc:
        logger.error("Statement query error: %s", type(exc).__name__)
        return {"ok": False, "error": "Failed to retrieve statement."}
    finally:
        cursor.close()
        conn.close()

    safe_rows = [
        {
            **row,
            "amount": Decimal(str(row["amount"])),
            "balance_after": Decimal(str(row["balance_after"])),
        }
        for row in rows
    ]

    return {"ok": True, "rows": safe_rows}


def fun_generate_csv(rows: list) -> str:
    """Serialize a list of transaction row dicts to a CSV string.

    The CSV always begins with a header line:
        date,type,amount,category,note,balance_after

    Each data row uses created_at.date() for the date column. NULL values for
    category and note are written as empty strings. Returns a header-only
    CSV when rows is empty. Satisfies AC-4.

    Args:
        rows: List of transaction dicts as returned by fun_get_statement.
              Each dict must have: type, amount, category, note,
                                   created_at (datetime), balance_after.

    Returns:
        str: Complete CSV content including header.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "type", "amount", "category", "note", "balance_after"])
    for row in rows:
        writer.writerow([
            row["created_at"].date(),
            row["type"],
            row["amount"],
            row["category"] if row["category"] is not None else "",
            row["note"] if row["note"] is not None else "",
            row["balance_after"],
        ])
    return output.getvalue()
