import sqlite3
import os

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "material_acceptance.db")
print("DB path:", db_path)
print("DB exists:", os.path.exists(db_path))

conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cur.fetchall()
print("Tables:", [t[0] for t in tables])

if "notification_rules" in [t[0] for t in tables]:
    cur.execute("SELECT * FROM notification_rules")
    rows = cur.fetchall()
    print("notification_rules count:", len(rows))
    for r in rows:
        print("  ", r)

if "delivery_records" in [t[0] for t in tables]:
    cur.execute("PRAGMA table_info(delivery_records)")
    cols = cur.fetchall()
    print("delivery_records columns:", [c[1] for c in cols])

conn.close()
