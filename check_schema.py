import sqlite3, os
os.chdir(r'C:\Users\Soon Yuan Chi\OneDrive\Desktop\比賽')
conn = sqlite3.connect('butler.db')
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print('=== 現有資料表 ===')
for t in tables:
    cur.execute('PRAGMA table_info([' + t + '])')
    cols = cur.fetchall()
    print(f'\n[{t}]')
    for c in cols:
        print(f'  {c[1]} ({c[2]})')
conn.close()
