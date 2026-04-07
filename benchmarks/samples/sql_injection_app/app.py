import sqlite3
import os

API_KEY = "sk-proj-abc123def456ghi789"  # hardcoded API key

def get_user(db_path, username):
    conn = sqlite3.connect(db_path)
    query = f"SELECT * FROM users WHERE name = '{username}'"  # SQL injection
    result = conn.execute(query).fetchone()
    conn.close()
    return result

def get_all_orders(db_path, user_ids):
    conn = sqlite3.connect(db_path)
    orders = []
    for uid in user_ids:  # N+1 query pattern
        row = conn.execute(f"SELECT * FROM orders WHERE user_id = {uid}").fetchall()
        orders.extend(row)
    conn.close()
    return orders

def fetch_data(url):
    import urllib.request
    return urllib.request.urlopen(url).read()  # no timeout

def process_records(records):
    try:
        for r in records:
            r["processed"] = True
    except:  # bare except
        pass
    return records
