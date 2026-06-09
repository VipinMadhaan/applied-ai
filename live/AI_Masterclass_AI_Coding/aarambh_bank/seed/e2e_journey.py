"""End-to-end journey script covering SC-01 through SC-07."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from decimal import Decimal
from datetime import date
from src.features.auth import fun_register, fun_login, fun_require_auth, fun_logout
from src.features.account import fun_create_account, fun_get_account
from src.features.dashboard import fun_get_dashboard_data
from src.features.deposit import fun_deposit
from src.features.withdraw import fun_withdraw
from src.features.statement import fun_get_statement, fun_generate_csv
from src.ai.sql_guard import fun_validate_sql

PASS = "PASS"
FAIL = "FAIL"

def chk(condition, label):
    status = PASS if condition else FAIL
    print(f"  [{status}] {label}")
    return condition

all_ok = True

print("=== SC-01: Registration & Authentication ===")
fun_register("sc01_user", "sc01@test.io", "9111111111", "Test1234!")
r = fun_login("sc01_user", "Test1234!")
all_ok &= chk(r["ok"] and r["user_id"] > 0, "Valid login succeeds with user_id")
all_ok &= chk("logged_in" in r and r["logged_in"], "Login result carries logged_in=True")
rw = fun_login("sc01_user", "WRONG")
rn = fun_login("no_such_user", "Test1234!")
all_ok &= chk(not rw["ok"], "Wrong password rejected")
all_ok &= chk(not rn["ok"], "Unknown username rejected")
all_ok &= chk(rw["error"] == rn["error"], "Both failures return identical generic message (no enumeration)")
user_id = r["user_id"]

print()
print("=== SC-02: Dashboard ===")
acct = fun_create_account(user_id)
account_id = acct["account_id"]
data = fun_get_dashboard_data(user_id)
all_ok &= chk(data is not None, "Dashboard returns data for authenticated user")
all_ok &= chk("username" in data and "email" in data and "phone" in data, "Profile fields present")
all_ok &= chk("masked_account_number" in data, "Masked account number present")
all_ok &= chk("*" in data["masked_account_number"], "Account number is masked")
all_ok &= chk(data["masked_account_number"][-4:] == acct["account_number"][-4:], "Last 4 digits visible")
all_ok &= chk(isinstance(data["balance"], Decimal), "Balance is Decimal (not float)")
all_ok &= chk(isinstance(data["recent_transactions"], list), "recent_transactions is a list")
all_ok &= chk(fun_get_dashboard_data(999999) is None, "Unknown user_id returns None")

print()
print("=== SC-03: Deposit ===")
r = fun_deposit(account_id, Decimal("10000.00"), "Salary", "June pay")
all_ok &= chk(r["ok"] and r["balance"] == Decimal("10000.00"), "Valid deposit increases balance exactly")
all_ok &= chk(isinstance(r["balance"], Decimal), "Returned balance is Decimal")
r0 = fun_deposit(account_id, Decimal("0"), None, None)
all_ok &= chk(not r0["ok"], "Zero deposit rejected")
rn = fun_deposit(account_id, Decimal("-500"), None, None)
all_ok &= chk(not rn["ok"], "Negative deposit rejected")
r2 = fun_deposit(account_id, Decimal("500.50"), "Food", "Lunch")
all_ok &= chk(r2["balance"] == Decimal("10500.50"), "Consecutive deposit balance correct")

print()
print("=== SC-04: Withdraw (no overdraft) ===")
r = fun_withdraw(account_id, Decimal("2000.25"), "Shopping", "Clothes")
all_ok &= chk(r["ok"] and r["balance"] == Decimal("8500.25"), "Valid withdrawal decreases balance exactly")
rover = fun_withdraw(account_id, Decimal("99999"), None, None)
all_ok &= chk(not rover["ok"] and "Insufficient" in rover["error"], "Overdraft rejected with Insufficient message")
r_zero = fun_withdraw(account_id, Decimal("0"), None, None)
all_ok &= chk(not r_zero["ok"], "Zero withdrawal rejected")
# Withdraw exactly equal to balance
exact = fun_withdraw(account_id, Decimal("8500.25"), None, None)
all_ok &= chk(exact["ok"] and exact["balance"] == Decimal("0.00"), "Withdraw exactly = balance leaves 0.00")

print()
print("=== SC-05: Bank Statement ===")
fun_deposit(account_id, Decimal("5000.00"), "Salary", None)
fun_deposit(account_id, Decimal("3000.00"), "Bonus", None)
fun_withdraw(account_id, Decimal("1500.00"), "Bills", None)
s_all = fun_get_statement(account_id)
all_ok &= chk(s_all["ok"] and len(s_all["rows"]) >= 3, f"Statement returns rows ({len(s_all['rows'])} found)")
all_ok &= chk(isinstance(s_all["rows"][0]["amount"], Decimal), "Row amounts are Decimal")
# Newest first
ts = [r["created_at"] for r in s_all["rows"]]
all_ok &= chk(ts == sorted(ts, reverse=True), "Rows are newest-first")
# Type filter
sc = fun_get_statement(account_id, tx_type="CREDIT")
sd = fun_get_statement(account_id, tx_type="DEBIT")
all_ok &= chk(all(r["type"] == "CREDIT" for r in sc["rows"]), "CREDIT filter returns only CREDITs")
all_ok &= chk(all(r["type"] == "DEBIT"  for r in sd["rows"]), "DEBIT filter returns only DEBITs")
# Inverted date range → error
bad = fun_get_statement(account_id, from_date=date(2026,12,31), to_date=date(2026,1,1))
all_ok &= chk(not bad["ok"] and "date" in bad["error"].lower(), "Inverted date range returns clear error")
# CSV
csv = fun_generate_csv(s_all["rows"])
header = csv.splitlines()[0]
all_ok &= chk(header == "date,type,amount,category,note,balance_after", f"CSV header correct: {header}")
lines = [l for l in csv.splitlines() if l]
all_ok &= chk(len(lines) == len(s_all["rows"]) + 1, "CSV has header + one row per transaction")

print()
print("=== SC-06: AI Chat Guard ===")
guard_tests = [
    (f"SELECT SUM(amount) FROM transactions WHERE account_id = {account_id}", True,  "Valid scoped SELECT"),
    (f"SELECT * FROM transactions WHERE account_id = {account_id} AND type='CREDIT'", True, "Filtered scoped SELECT"),
    ("DROP TABLE users",                                                                False, "DROP rejected"),
    (f"UPDATE accounts SET balance=0 WHERE account_id={account_id}",                  False, "UPDATE rejected"),
    (f"DELETE FROM transactions WHERE account_id={account_id}",                       False, "DELETE rejected"),
    (f"SELECT 1; DROP TABLE users",                                                    False, "Multi-statement rejected"),
    ("SELECT * FROM transactions",                                                      False, "Unscoped SELECT rejected"),
    (f"SELECT * FROM transactions WHERE account_id={account_id+1}",                   False, "Wrong account_id rejected"),
    (f"SELECT * FROM transactions -- WHERE account_id={account_id}",                  False, "account_id in comment rejected"),
    (f"SELECT * FROM transactions WHERE account_id={account_id} INTO OUTFILE '/tmp'", False, "INTO OUTFILE rejected"),
    ("EXECUTE some_proc",                                                               False, "EXECUTE rejected"),
]
for sql, expected, label in guard_tests:
    ok, reason = fun_validate_sql(sql, account_id)
    result = ok == expected
    all_ok &= chk(result, label)

print()
print("=== SC-07: User Data Isolation & Session Security ===")
fun_register("sc07_other", "sc07@test.io", "9111111112", "Test1234!")
r2 = fun_login("sc07_other", "Test1234!")
other_uid = r2["user_id"]
other_acct = fun_create_account(other_uid)
fun_deposit(other_acct["account_id"], Decimal("99999.00"), None, None)
# Each user sees only their own data
my_dash = fun_get_dashboard_data(user_id)
other_dash = fun_get_dashboard_data(other_uid)
all_ok &= chk(my_dash["balance"] != other_dash["balance"], "Different users see different balances")
my_stmt = fun_get_statement(account_id)
other_stmt = fun_get_statement(other_acct["account_id"])
my_ids = {r["balance_after"] for r in my_stmt["rows"]}
other_ids = {r["balance_after"] for r in other_stmt["rows"]}
all_ok &= chk(my_ids.isdisjoint(other_ids), "Statement rows are user-isolated (no cross-contamination)")
# Session gating
session = {"logged_in": True, "user_id": user_id, "username": "sc01_user"}
all_ok &= chk(fun_require_auth(session), "Authenticated session passes require_auth")
fun_logout(session)
all_ok &= chk(not fun_require_auth(session), "After logout, require_auth returns False")
all_ok &= chk(not fun_require_auth({}), "Empty session denied")
all_ok &= chk(not fun_require_auth({"logged_in": True, "user_id": None}), "user_id=None denied")

print()
print("=" * 55)
print(f"OVERALL: {'ALL PASS' if all_ok else 'FAILURES DETECTED'}")
