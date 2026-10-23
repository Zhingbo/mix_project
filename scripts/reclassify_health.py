import os
import pymysql

cfg = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
           database="business_data", charset="utf8mb4")
T = "ent_industry_class_chain_scope_20260928_converted"
BK = "_backup_health_reclass_20260929"

HEALTH_RE = ("医疗|医药|医院|诊所|门诊|药房|药店|健康管理|康复|护理|养老|"
             "生物科技|生物医药|生物技术|基因|细胞|干细胞|抗体|疫苗|生物制品|"
             "制药|药业|中药|中医|中成药|中药材|口腔|眼科|牙科|齿科|义齿|"
             "体检|诊断|医学|医用|养生|保健|康养")

CAT_RULES = [
    ("医疗器械|医用耗材|医疗设备", "医疗器械制造"),
    ("药房|药店|医药流通", "医药流通与零售"),
    ("中药|中医|中成药|中药材|饮片", "中医药研发与制造"),
    ("基因|细胞|干细胞|疫苗|抗体|生物制品|生物医药|生物科技|生物技术", "生物医药研发与制造"),
    ("制药|药业|医药|药物|药品|原料药|制剂", "生物医药研发与制造"),
    ("健康管理|养生|保健|体检|康复|护理|养老|康养", "健康管理与康复服务"),
    ("口腔|眼科|牙科|齿科|义齿", "专科医疗服务"),
    ("医院|诊所|门诊|卫生院", "医疗服务"),
    ("医疗|医学|医护|医生|医用", "医疗服务"),
]


def build_case():
    whens = []
    for kws, cat in CAT_RULES:
        conds = " OR ".join(f"company_name LIKE '%{k}%'" for k in kws.split("|"))
        whens.append(f"WHEN ({conds}) THEN '{cat}'")
    return "CASE " + " ".join(whens) + " ELSE '健康相关' END"


def q(s):
    return "'" + s.replace("'", "''") + "'"


conn = pymysql.connect(**cfg)
cur = conn.cursor()

print("=== 1) 备份受影响行 ===")
cur.execute(f"DROP TABLE IF EXISTS {BK}")
cur.execute(f"""
    CREATE TABLE {BK} AS
    SELECT id, credit_code, industry_class_first, industry_class_second, industry_class_third
    FROM {T}
    WHERE industry_class_first='其他' AND company_name REGEXP {q(HEALTH_RE)}
""")
conn.commit()
cur.execute(f"SELECT COUNT(*) FROM {BK}")
print(f"备份行数 = {cur.fetchone()[0]}")

print("=== 2) 更新前统计 ===")
for f in ("其他", "大健康"):
    cur.execute(f"SELECT COUNT(*) FROM {T} WHERE industry_class_first='{f}'")
    print(f"  {f}: {cur.fetchone()[0]}")

print("=== 3) 执行重分类 UPDATE ===")
case_expr = build_case()
third_prefix = "{'大健康|"
third_suffix = "|健康相关': '强'}"
sql = (
    f"UPDATE {T} SET "
    f"industry_class_first = '大健康', "
    f"industry_class_second = CONCAT('大健康|', {case_expr}), "
    f"industry_class_third = CONCAT({q(third_prefix)}, {case_expr}, {q(third_suffix)}) "
    f"WHERE industry_class_first='其他' AND company_name REGEXP {q(HEALTH_RE)}"
)
cur.execute(sql)
conn.commit()
print(f"UPDATE 影响行数 = {cur.rowcount}")

print("=== 4) 更新后统计 ===")
for f in ("其他", "大健康"):
    cur.execute(f"SELECT COUNT(*) FROM {T} WHERE industry_class_first='{f}'")
    print(f"  {f}: {cur.fetchone()[0]}")

print("=== 5) 大健康二级分布 ===")
cur.execute(f"""SELECT industry_class_second, COUNT(*) c FROM {T}
                WHERE industry_class_first='大健康'
                GROUP BY industry_class_second ORDER BY c DESC""")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]}")

print("=== 6) 样例(医疗服务 3条) ===")
cur.execute(f"""SELECT industry_class_first, industry_class_second, industry_class_third
                FROM {T} WHERE industry_class_first='大健康'
                AND industry_class_second LIKE '大健康|医疗服务%' LIMIT 3""")
for row in cur.fetchall():
    print(f"  {row}")

cur.close(); conn.close()
print("完成")