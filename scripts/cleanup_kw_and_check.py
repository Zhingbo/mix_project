import os
import pymysql

cfg = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
           database="business_data", charset="utf8mb4")
BASE = "ent_industry_class_chain_scope_20260928_converted"
OUT = [
    ("company_nodes_mapping", "company_name"),
    ("company_nodes_info_result", "company_name"),
    ("company_nodes_info_split", "company_name"),
    ("company_nodes_final", "company_name"),
    ("company_nodes_finallist", "company_name"),
    ("company_list_output", "供应商"),
]
KW = ["家具", "厨具", "服饰", "饰品", "商贸", "物流", "电商"]
KW_RE = "|".join(KW)

conn = pymysql.connect(**cfg)
cur = conn.cursor()

def one(sql, args=None):
    cur.execute(sql, args)
    r = cur.fetchone()
    return r[0] if r else None

print("=" * 60)
print("一、收尾: 底表(待清理)删除(按备份表 id 精确删)")
cur.execute("SELECT COUNT(*) FROM _backup_daichuli_20260929")
bk_n = cur.fetchone()[0]
print(f"  备份表(待清理)条数 = {bk_n}")
cur.execute(f"DELETE b FROM {BASE} b JOIN _backup_daichuli_20260929 d ON b.id=d.id")
conn.commit()
print(f"  底表按id删除 = {cur.rowcount}")
print(f"  底表(待清理)剩余 = {one(f'SELECT COUNT(*) FROM {BASE} WHERE company_name LIKE %s', ('%待清理%',))}")

print("=" * 60)
print(f"二、关键词删除: {KW}")

# 2.1 底表备份
cur.execute(f"DROP TABLE IF EXISTS _backup_kw_20260929")
cur.execute(f"CREATE TABLE _backup_kw_20260929 AS SELECT * FROM {BASE} WHERE company_name REGEXP %s", (KW_RE,))
conn.commit()
print(f"  底表关键词命中(已备份) = {one('SELECT COUNT(*) FROM _backup_kw_20260929')}")

# 2.2 输出表删除
for t, col in OUT:
    n = cur.execute(f"DELETE FROM {t} WHERE {col} REGEXP %s", (KW_RE,))
    conn.commit()
    print(f"  输出表 {t}.{col} 删除 = {n}")

# 2.3 底表删除
cur.execute(f"DELETE FROM {BASE} WHERE company_name REGEXP %s", (KW_RE,))
conn.commit()
print(f"  底表删除 = {cur.rowcount}")
print(f"  底表关键词剩余 = {one(f'SELECT COUNT(*) FROM {BASE} WHERE company_name REGEXP %s', (KW_RE,))}")

print("=" * 60)
print("三、CHECK(只查不删): 编号名称 + 非'公司'结尾")

# 编号名称: 纯字母数字、无中文、长度>=12 (信用代码18位)
CODE_RE = "^[0-9A-Za-z]{12,}$"
NOT_GONGSI = "%公司"

for t, col in OUT:
    c_code = one(f"SELECT COUNT(*) FROM {t} WHERE {col} REGEXP %s", (CODE_RE,))
    c_notg = one(f"SELECT COUNT(*) FROM {t} WHERE {col} NOT LIKE %s AND {col} IS NOT NULL AND {col} != ''", (NOT_GONGSI,))
    print(f"  [{t}] 编号={c_code}  非公司结尾={c_notg}")

print("--- 底表 ---")
print(f"  编号名称 = {one(f'SELECT COUNT(*) FROM {BASE} WHERE company_name REGEXP %s', (CODE_RE,))}")
print(f"  非公司结尾 = {one(f'SELECT COUNT(*) FROM {BASE} WHERE company_name NOT LIKE %s AND company_name IS NOT NULL', (NOT_GONGSI,))}")

print("--- 底表 编号样例行 ---")
cur.execute(f"SELECT company_name, industry_class_first FROM {BASE} WHERE company_name REGEXP %s LIMIT 20", (CODE_RE,))
for r in cur.fetchall():
    print(f"    {r[0]}  [{r[1]}]")

print("--- 底表 非公司结尾样例行 ---")
cur.execute(f"SELECT company_name, industry_class_first FROM {BASE} WHERE company_name NOT LIKE %s AND company_name IS NOT NULL AND company_name != '' LIMIT 20", (NOT_GONGSI,))
for r in cur.fetchall():
    print(f"    {r[0]}  [{r[1]}]")

cur.close(); conn.close()
print("完成")