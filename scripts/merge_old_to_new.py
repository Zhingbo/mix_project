# -*- coding: utf-8 -*-
import os
# 旧表 -> 新表合并(旧表优先): 新增新表没有的, 覆盖两表都有的
#   - 备份新表将被覆盖的 10.9万 行
#   - first/second 由 strongest 分类归一化为纯字符串; third 原样; entity_id 保留(新增行留空)
import pymysql
import ast
import json

OLD = 'ent_industry_class_old'
NEW = 'ent_industry_class_chain_scope_20260928_converted'
BK = '_backup_new_overlap_20261012'

cfg = dict(host='8.141.5.67', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
           database='business_data', charset='utf8mb4', connect_timeout=60)
RANK = {'强': 3, '中': 2, '弱': 1}

COLS_INSERT = ("company_name, company_name_full, credit_code, entity_id, website, "
               "is_official_website, product, business, industry, industry_class_first, "
               "industry_class_second, industry_class_third, `explain`, certainty, version, update_time")
COLS_UPDATE = ("company_name=VALUES(company_name), company_name_full=VALUES(company_name_full), "
               "credit_code=VALUES(credit_code), website=VALUES(website), "
               "is_official_website=VALUES(is_official_website), product=VALUES(product), "
               "business=VALUES(business), industry=VALUES(industry), "
               "industry_class_first=VALUES(industry_class_first), "
               "industry_class_second=VALUES(industry_class_second), "
               "industry_class_third=VALUES(industry_class_third), `explain`=VALUES(`explain`), "
               "certainty=VALUES(certainty), version=VALUES(version), update_time=VALUES(update_time)")


def parse(s):
    if not s or str(s).strip() in ('', '{}', 'None'):
        return None
    try:
        return ast.literal_eval(s)
    except Exception:
        try:
            return json.loads(s.replace("'", '"'))
        except Exception:
            return None


def best_key(d):
    best, br = None, -1
    for k, v in d.items():
        r = RANK.get(str(v).strip(), 0)
        if r > br:
            best, br = k, r
    return best


def norm(first_s, second_s, third_s):
    d3 = parse(third_s)
    if d3:
        k = best_key(d3)
        if k:
            p = str(k).split('|')
            return p[0] if p else '', '|'.join(p[:2])
    d2 = parse(second_s)
    if d2:
        k = best_key(d2)
        if k:
            p = str(k).split('|')
            return p[0] if p else '', '|'.join(p[:2])
    d1 = parse(first_s)
    if d1:
        k = best_key(d1)
        if k:
            return str(k), ''
    return '', ''


def main():
    conn = pymysql.connect(**cfg)
    cur = conn.cursor()

    cur.execute(f"SELECT COUNT(*) FROM {OLD}"); old_tot = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM {NEW}"); new_before = cur.fetchone()[0]
    cur.execute(f"""SELECT COUNT(*) FROM {OLD} o WHERE EXISTS
                    (SELECT 1 FROM {NEW} n WHERE n.company_name=o.company_name)""")
    overlap = cur.fetchone()[0]
    print(f"old={old_tot}  new_before={new_before}  重名(将覆盖)={overlap}  新增={old_tot-overlap}")

    # 备份: 新表中将被覆盖的行
    cur.execute(f"DROP TABLE IF EXISTS {BK}")
    cur.execute(f"""CREATE TABLE {BK} AS SELECT n.* FROM {NEW} n WHERE EXISTS
                    (SELECT 1 FROM {OLD} o WHERE o.company_name=n.company_name)""")
    conn.commit()
    cur.execute(f"SELECT COUNT(*) FROM {BK}"); print(f"已备份将被覆盖的行: {cur.fetchone()[0]}")

    # 读取旧表(流式), 归一化并 upsert
    rd = pymysql.connect(**cfg, cursorclass=pymysql.cursors.SSCursor)
    rc = rd.cursor()
    rc.execute(f"""SELECT company_name, company_name_full, credit_code, website, is_official_website,
        product, business, industry, industry_class_first, industry_class_second, industry_class_third,
        `explain`, certainty, version, update_time FROM {OLD}""")

    batch = []
    ins_cnt = upd_cnt = 0
    ph = "(" + ",".join(["%s"]*16) + ")"
    sql = f"INSERT INTO {NEW} ({COLS_INSERT}) VALUES {ph} ON DUPLICATE KEY UPDATE {COLS_UPDATE}"

    for row in rc:
        (cn, cnf, cc, web, isw, prod, biz, ind, icf, ics, ict, expl, cert, ver, ut) = row
        f, s = norm(icf, ics, ict)
        batch.append((cn, cnf, cc, None, web, isw, prod, biz, ind, f, s, ict, expl, cert, ver, ut))
        if len(batch) >= 2000:
            cur.executemany(sql, batch)
            conn.commit()
            batch = []
    if batch:
        cur.executemany(sql, batch)
        conn.commit()

    rd.close()

    cur.execute(f"SELECT COUNT(*) FROM {NEW}"); new_after = cur.fetchone()[0]
    print(f"合并完成: 新增={old_tot-overlap}  覆盖={overlap}")
    print(f"新表行数: {new_before} -> {new_after} (增量 {new_after-new_before})")
    conn.close()
    print("done")


if __name__ == "__main__":
    main()
