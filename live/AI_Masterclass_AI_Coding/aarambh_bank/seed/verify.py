"""Quick integrity check for seeded demo data."""
import os, sys
from decimal import Decimal
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from src.db.connection import fun_get_connection

conn = fun_get_connection()
cur = conn.cursor(dictionary=True)

cur.execute("SELECT COUNT(*) AS cnt FROM users WHERE username LIKE 'demo_%'")
print("Demo users      :", cur.fetchone()["cnt"])

cur.execute("""SELECT COUNT(*) AS cnt FROM accounts a
               JOIN users u ON u.id = a.user_id WHERE u.username LIKE 'demo_%'""")
print("Demo accounts   :", cur.fetchone()["cnt"])

cur.execute("""SELECT COUNT(*) AS cnt FROM transactions t
               JOIN accounts a ON a.id = t.account_id
               JOIN users u ON u.id = a.user_id WHERE u.username LIKE 'demo_%'""")
print("Demo transactions:", cur.fetchone()["cnt"])

cur.execute("""
    SELECT u.username, a.balance AS ab, t.balance_after AS tb
    FROM users u
    JOIN accounts a ON a.user_id = u.id
    JOIN transactions t ON t.account_id = a.id
    WHERE u.username LIKE 'demo_%'
      AND t.id = (SELECT MAX(t2.id) FROM transactions t2 WHERE t2.account_id = a.id)
    ORDER BY u.username
""")
print("\nBalance consistency (account.balance == last tx balance_after):")
all_match = True
for row in cur.fetchall():
    match = row["ab"] == row["tb"]
    all_match = all_match and match
    print(f"  {row['username']:<22} account={row['ab']}  last_tx={row['tb']}  OK={match}")

cur.execute("SELECT balance FROM accounts a JOIN users u ON u.id = a.user_id WHERE u.username LIKE 'demo_%'")
decimal_ok = all(isinstance(r["balance"], Decimal) for r in cur.fetchall())
print(f"\nAll balances are Decimal : {decimal_ok}")
print(f"All balances consistent  : {all_match}")
cur.close()
conn.close()
