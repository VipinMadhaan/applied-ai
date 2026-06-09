"""Demo data seeder for Aarambh Bank.

Creates NUM_USERS demo users each with one account and MONTHS months of
categorised transaction history. Idempotent: clears previous demo data
before re-seeding so consecutive runs never duplicate rows.

Usage:
    python seed/seed.py [num_users] [months]
    Defaults: 5 users, 6 months.
"""

import calendar
import logging
import os
import random
import sys
from datetime import date
from decimal import Decimal

import bcrypt

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from src.db.connection import fun_get_connection  # noqa: E402
from src.db.schema import fun_init_schema  # noqa: E402
from src.features.account import fun_create_account  # noqa: E402

logger = logging.getLogger(__name__)

DEMO_USER_PREFIX = "demo_"
DEMO_USER_PIN = "Demo@1234"

DEMO_USER_TEMPLATES = [
    ("demo_rahul",   "demo_rahul@aarambh.demo",   "9811111110"),
    ("demo_priya",   "demo_priya@aarambh.demo",   "9811111111"),
    ("demo_arjun",   "demo_arjun@aarambh.demo",   "9811111112"),
    ("demo_meera",   "demo_meera@aarambh.demo",   "9811111113"),
    ("demo_vikram",  "demo_vikram@aarambh.demo",  "9811111114"),
    ("demo_ananya",  "demo_ananya@aarambh.demo",  "9811111115"),
    ("demo_rohit",   "demo_rohit@aarambh.demo",   "9811111116"),
    ("demo_deepa",   "demo_deepa@aarambh.demo",   "9811111117"),
    ("demo_kiran",   "demo_kiran@aarambh.demo",   "9811111118"),
    ("demo_sandeep", "demo_sandeep@aarambh.demo", "9811111119"),
]

SALARY_MIN = Decimal("45000.00")
SALARY_MAX = Decimal("85000.00")

DEBIT_CATEGORIES = {
    "food":          {"count": (4, 8),  "min": Decimal("150.00"),  "max": Decimal("800.00")},
    "transport":     {"count": (3, 6),  "min": Decimal("50.00"),   "max": Decimal("400.00")},
    "shopping":      {"count": (1, 3),  "min": Decimal("400.00"),  "max": Decimal("4000.00")},
    "bills":         {"count": (1, 2),  "min": Decimal("500.00"),  "max": Decimal("5000.00")},
    "entertainment": {"count": (1, 3),  "min": Decimal("150.00"),  "max": Decimal("1500.00")},
}


def fun_random_amount(min_val: Decimal, max_val: Decimal) -> Decimal:
    """Return a random Decimal amount in [min_val, max_val] rounded to 2 d.p.

    Uses integer arithmetic on paise/cents to avoid float precision loss.

    Args:
        min_val: Lower bound (Decimal).
        max_val: Upper bound (Decimal).

    Returns:
        Decimal: A random amount with 2 decimal places.
    """
    min_paise = int(min_val * 100)
    max_paise = int(max_val * 100)
    return (Decimal(random.randint(min_paise, max_paise)) / Decimal(100)).quantize(
        Decimal("0.01")
    )


def fun_month_start(months_back: int) -> date:
    """Return the first day of the month that is months_back months before today.

    Args:
        months_back: How many months in the past (1 = last month).

    Returns:
        date: First day of the target month.
    """
    today = date.today()
    year, month = today.year, today.month - months_back
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def fun_clear_demo_data(conn) -> int:
    """Delete all rows belonging to demo users (username LIKE 'demo_%').

    Deletes in FK-safe order: transactions → accounts → users.

    Args:
        conn: Open MySQL connection (autocommit=False).

    Returns:
        int: Number of demo user rows deleted.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id FROM users WHERE username LIKE %s",
            (f"{DEMO_USER_PREFIX}%",),
        )
        user_ids = [row[0] for row in cursor.fetchall()]
        if not user_ids:
            return 0

        uid_placeholders = ",".join(["%s"] * len(user_ids))
        cursor.execute(
            f"SELECT id FROM accounts WHERE user_id IN ({uid_placeholders})",
            user_ids,
        )
        account_ids = [row[0] for row in cursor.fetchall()]

        if account_ids:
            aid_placeholders = ",".join(["%s"] * len(account_ids))
            cursor.execute(
                f"DELETE FROM transactions WHERE account_id IN ({aid_placeholders})",
                account_ids,
            )
            cursor.execute(
                f"DELETE FROM accounts WHERE id IN ({aid_placeholders})",
                account_ids,
            )

        cursor.execute(
            f"DELETE FROM users WHERE id IN ({uid_placeholders})",
            user_ids,
        )
        conn.commit()
        return len(user_ids)
    finally:
        cursor.close()


def fun_seed_user(conn, username: str, email: str, phone: str) -> int:
    """Insert one demo user row and return its generated id.

    Hashes DEMO_USER_PIN with a fresh bcrypt salt per user.

    Args:
        conn: Open MySQL connection.
        username: Demo username.
        email: Demo email address.
        phone: Demo phone number (digits only).

    Returns:
        int: Auto-increment id of the inserted user.
    """
    hashed = bcrypt.hashpw(DEMO_USER_PIN.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, email, phone, password_hash) "
            "VALUES (%s, %s, %s, %s)",
            (username, email, phone, hashed),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        cursor.close()


def fun_seed_account(user_id: int) -> tuple:
    """Create one demo bank account via the account feature module.

    Args:
        user_id: The demo user's id.

    Returns:
        tuple: (account_id: int, account_number: str)

    Raises:
        RuntimeError: If account creation fails.
    """
    result = fun_create_account(user_id)
    if not result["ok"]:
        raise RuntimeError(
            f"Account creation failed for user {user_id}: {result['error']}"
        )
    return result["account_id"], result["account_number"]


def fun_build_transaction_rows(months: int) -> tuple:
    """Generate transaction dicts for one account covering the given number of months.

    Produces a salary CREDIT on day 1 of each month followed by random debit
    transactions across food/transport/shopping/bills/entertainment categories.
    Ensures the running balance never goes below zero.

    Args:
        months: Number of complete months of history to generate.

    Returns:
        tuple: (rows: list[dict], final_balance: Decimal)
               Each dict has: type, amount, category, note, tx_date, balance_after.
    """
    rows = []
    balance = Decimal("0.00")

    for months_back in range(months, 0, -1):
        first = fun_month_start(months_back)
        _, last_day = calendar.monthrange(first.year, first.month)

        salary = fun_random_amount(SALARY_MIN, SALARY_MAX)
        balance += salary
        rows.append({
            "type": "CREDIT",
            "amount": salary,
            "category": "salary",
            "note": "Monthly salary",
            "tx_date": first,
            "balance_after": balance,
        })

        debits = []
        for category, cfg in DEBIT_CATEGORIES.items():
            for _ in range(random.randint(*cfg["count"])):
                amt = fun_random_amount(cfg["min"], cfg["max"])
                day = random.randint(2, last_day)
                debits.append((day, category, amt))
        debits.sort(key=lambda x: x[0])

        for day, category, amt in debits:
            if amt > balance:
                amt = (balance * Decimal("0.7")).quantize(Decimal("0.01"))
            if amt <= Decimal("0.00"):
                continue
            balance -= amt
            rows.append({
                "type": "DEBIT",
                "amount": amt,
                "category": category,
                "note": f"{category.title()} expense",
                "tx_date": date(first.year, first.month, day),
                "balance_after": balance,
            })

    return rows, balance


def fun_insert_transactions(conn, account_id: int, rows: list) -> int:
    """Bulk-insert transaction rows for one account.

    All inserts are wrapped in a single commit for atomicity.

    Args:
        conn: Open MySQL connection.
        account_id: The account these transactions belong to.
        rows: List of transaction dicts from fun_build_transaction_rows.

    Returns:
        int: Number of rows inserted.
    """
    if not rows:
        return 0
    cursor = conn.cursor()
    try:
        data = [
            (
                account_id,
                r["type"],
                r["amount"],
                r["category"],
                r["note"],
                r["tx_date"],
                r["balance_after"],
            )
            for r in rows
        ]
        cursor.executemany(
            "INSERT INTO transactions "
            "(account_id, type, amount, category, note, created_at, balance_after) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            data,
        )
        conn.commit()
        return cursor.rowcount
    finally:
        cursor.close()


def fun_update_balance(conn, account_id: int, final_balance: Decimal) -> None:
    """Update accounts.balance to reflect the post-transaction final balance.

    Args:
        conn: Open MySQL connection.
        account_id: The account to update.
        final_balance: Computed final balance after all transactions.

    Returns:
        None
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE accounts SET balance = %s WHERE id = %s",
            (final_balance, account_id),
        )
        conn.commit()
    finally:
        cursor.close()


def fun_main(num_users: int = 5, months: int = 6) -> None:
    """Seed the database with demo users and transaction history.

    Idempotent: clears any existing demo_ data before inserting fresh rows.
    Prints a summary table and totals on completion.

    Args:
        num_users: Number of demo users to create (1–10).
        months: Months of transaction history to generate per account.

    Returns:
        None
    """
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    num_users = max(1, min(num_users, len(DEMO_USER_TEMPLATES)))
    months = max(1, months)

    fun_init_schema()
    conn = fun_get_connection()

    cleared = fun_clear_demo_data(conn)
    if cleared:
        print(f"Cleared {cleared} existing demo user(s) and their data.")

    templates = DEMO_USER_TEMPLATES[:num_users]
    total_tx = 0

    print(f"\nSeeding {len(templates)} user(s) x {months} month(s) of history...")
    print(f"{'Username':<22} {'Account':>12}  {'Txns':>6}  {'Balance (INR)':>16}")
    print("-" * 62)

    for username, email, phone in templates:
        user_id = fun_seed_user(conn, username, email, phone)
        account_id, account_number = fun_seed_account(user_id)
        rows, final_balance = fun_build_transaction_rows(months)
        tx_count = fun_insert_transactions(conn, account_id, rows)
        fun_update_balance(conn, account_id, final_balance)
        total_tx += tx_count
        print(
            f"{username:<22} ****{account_number[-4:]:>8}  {tx_count:>6}  {final_balance:>16,.2f}"
        )

    conn.close()
    print("-" * 62)
    print(f"Total: {len(templates)} users | {total_tx} transactions")
    print(f"\nDemo login: username = demo_<name> | PIN = {DEMO_USER_PIN}")


if __name__ == "__main__":
    _num = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    _months = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    fun_main(_num, _months)
