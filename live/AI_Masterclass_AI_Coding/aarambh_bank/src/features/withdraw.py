"""Withdraw feature: remove funds from a user's account atomically.

Satisfies specs/withdraw.md AC-1 through AC-6.
"""

import logging
from decimal import Decimal

from src.db.connection import fun_get_connection

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")


def fun_withdraw(
    account_id: int,
    amount: Decimal,
    category: str | None = None,
    note: str | None = None,
) -> dict:
    """Withdraw a positive amount from an account atomically.

    Validates the amount, enforces the no-overdraft rule, then in a single
    DB transaction:
      1. Reads the current balance (row-locking via SELECT FOR UPDATE).
      2. Rejects if amount > current_balance ("Insufficient balance.").
      3. Computes new_balance = current_balance - amount.
      4. UPDATEs accounts.balance.
      5. INSERTs a DEBIT row in transactions with the correct balance_after.
      6. COMMITs both changes together.

    A failure at or after step 4 triggers a rollback, leaving the DB unchanged.
    All money is handled as Decimal; no float is used. Satisfies AC-1–AC-6.

    Args:
        account_id: Primary key of the account to debit.
        amount:     Positive Decimal amount to withdraw.
        category:   Optional transaction category (stored as NULL when omitted).
        note:       Optional free-text note (stored as NULL when omitted).

    Returns:
        dict: {"ok": True, "balance": Decimal}  on success.
              {"ok": False, "error": str}        on validation failure,
                                                 insufficient funds, or DB error.
    """
    if not isinstance(amount, Decimal):
        try:
            amount = Decimal(str(amount))
        except Exception:
            return {"ok": False, "error": "Amount must be a valid number."}

    if amount <= ZERO:
        return {"ok": False, "error": "Withdrawal amount must be greater than zero."}

    try:
        conn = fun_get_connection()
    except Exception as exc:
        logger.error("DB connection error during withdrawal: %s", type(exc).__name__)
        return {"ok": False, "error": "Service unavailable. Please try again."}

    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT balance FROM accounts WHERE id = %s FOR UPDATE",
            (account_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return {"ok": False, "error": "Account not found."}

        current_balance = Decimal(str(row[0]))

        if amount > current_balance:
            return {"ok": False, "error": "Insufficient balance."}

        new_balance = current_balance - amount

        cursor.execute(
            "UPDATE accounts SET balance = %s WHERE id = %s",
            (new_balance, account_id),
        )
        cursor.execute(
            "INSERT INTO transactions "
            "(account_id, type, amount, category, note, balance_after) "
            "VALUES (%s, 'DEBIT', %s, %s, %s, %s)",
            (account_id, amount, category, note, new_balance),
        )
        conn.commit()
        return {"ok": True, "balance": Decimal(str(new_balance))}

    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("Withdrawal error: %s", type(exc).__name__)
        return {"ok": False, "error": "Withdrawal failed. Please try again."}
    finally:
        cursor.close()
        conn.close()
