import sqlite3

#テーブル名一覧の取得

DB_PATH = "./db/nikkei_stock_average_analysis.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# テーブル一覧取得
cursor.execute("""
SELECT name
FROM sqlite_master
WHERE type='table'
ORDER BY name
""")

tables = cursor.fetchall()

for table in tables:
    table_name = table[0]

    print("=" * 50)
    print(table_name)

    cursor.execute(f"PRAGMA table_info({table_name})")

    columns = cursor.fetchall()

    for col in columns:
        print(f"  {col[1]} ({col[2]})")

conn.close()