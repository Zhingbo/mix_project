"""
将 ent_industry_class_new 的 industry_class_third(国标口径) 转换为 A口径(联东自定义),
写入新表 ent_industry_class_new_converted.

原理:
    1. 读 industry_mapping_gb_to_custom.json (国标full_name → A口径full_name)
    2. 逐行读 new 表, 对每条 industry_class_third 字典的 key 做替换:
       {国标full_name: 强弱} → {A口径full_name: 强弱}
    3. 写入新表 ent_industry_class_new_converted (结构同 new 表, 仅 industry_class_third 换口径)
    4. 同步替换 industry_class_first / industry_class_second (取 A口径 full_name 的前两段)

只读原表, 只写新表. 不动 new 表, 不动 old 表, 不动项目代码.

用法:
    cd /root/mix_project/scripts
    source /root/acemcp/.venv/bin/activate
    python convert_new_table_industry.py            # 全量转换
    python convert_new_table_industry.py --dry-run   # 只统计不写表
    python convert_new_table_industry.py --limit 1000 # 只转前1000行(测试)
"""

import csv
import json
import os
import sys
import ast
import argparse
from typing import Dict, Optional

import pymysql

# ============== 配置 ==============
MATERIALS_DIR = "/root/mix_project/materials"
MAPPING_JSON = os.path.join(MATERIALS_DIR, "industry_mapping_gb_to_custom_v2.json")

DB_CONFIG = {
    "host": "8.141.5.67",
    "port": 3306,
    "user": "root",
    "password": os.getenv("DB_PASSWORD"),
    "database": "business_data",
    "charset": "utf8mb4",
    "connect_timeout": 60,
}

SOURCE_TABLE = "ent_industry_class_new"
TARGET_TABLE = "ent_industry_class_new_converted"

BATCH_SIZE = 2000  # 写入批次


def load_mapping() -> Dict[str, str]:
    """加载映射表"""
    with open(MAPPING_JSON, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    # 清洗: 去掉 "无" 和带括号的失败映射
    clean = {}
    skipped = 0
    for k, v in mapping.items():
        if v and not v.startswith("无") and v != "":
            clean[k] = v
        else:
            skipped += 1
    print(f"映射表: {len(clean)} 条有效 / {skipped} 条无效(未映射)")
    return clean


def parse_dict_field(s: str) -> Optional[dict]:
    """解析 industry_class_third 字典字段, 兼容单双引号"""
    if not s or s in ("", "{}"):
        return None
    try:
        return ast.literal_eval(s)
    except Exception:
        try:
            return json.loads(s.replace("'", '"'))
        except Exception:
            return None


def convert_keys(d: dict, mapping: Dict[str, str]) -> dict:
    """替换字典的 key: 国标full_name → A口径full_name"""
    out = {}
    for k, v in d.items():
        new_k = mapping.get(k)
        if new_k:
            # 若多个国标key映射到同一A口径, 取强度最高的(强>中>弱)
            existing = out.get(new_k)
            if existing:
                # 强度排序
                rank = {"强": 3, "中": 2, "弱": 1}
                if rank.get(v, 0) > rank.get(existing, 0):
                    out[new_k] = v
            else:
                out[new_k] = v
        else:
            # 没有映射的 key, 保留原 key 标记 (便于事后查漏)
            out[f"[未映射]{k}"] = v
    return out


def split_levels(full_name: str):
    """从 A口径 full_name '机械设备与零件|电气设备|电机制造' 取前两段"""
    parts = full_name.split("|")
    first = parts[0] if len(parts) >= 1 else ""
    second = "|".join(parts[:2]) if len(parts) >= 2 else ""
    return first, second


def ensure_target_table(cursor):
    """创建目标表(结构同 new 表)"""
    cursor.execute(f"DROP TABLE IF EXISTS {TARGET_TABLE}")
    cursor.execute(f"""
    CREATE TABLE {TARGET_TABLE} LIKE {SOURCE_TABLE}
    """)
    # 清空(防重复)
    cursor.execute(f"TRUNCATE TABLE {TARGET_TABLE}")
    print(f"目标表 {TARGET_TABLE} 已准备(结构同 {SOURCE_TABLE})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计不写表")
    parser.add_argument("--limit", type=int, default=0, help="只转前N行(测试用)")
    args = parser.parse_args()

    print("=" * 60)
    print("转换 new 表 industry_class_third: 国标 → A口径")
    print("=" * 60)

    mapping = load_mapping()
    if not mapping:
        print("错误: 映射表为空或全部无效. 请先运行 build_industry_mapping.py 并人工复核.")
        return

    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    # 用服务端游标流式读取, 不一次性加载全表到内存
    read_conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.SSCursor)
    read_cursor = read_conn.cursor()

    # 统计源表行数
    if args.limit:
        total = args.limit
        limit_sql = f" LIMIT {args.limit}"
    else:
        cursor.execute(f"SELECT COUNT(*) FROM {SOURCE_TABLE}")
        total = cursor.fetchone()[0]
        limit_sql = ""
    print(f"待转换: {total} 行 (dry_run={args.dry_run})")

    if not args.dry_run:
        ensure_target_table(cursor)

    # 读源表 (用服务端游标流式读)
    read_cursor.execute(f"""
        SELECT id, company_name, company_name_full, credit_code, website, is_official_website,
               product, business, industry, industry_class_first, industry_class_second,
               industry_class_third, `explain`, certainty, version, update_time
        FROM {SOURCE_TABLE}
        WHERE industry_class_third IS NOT NULL AND industry_class_third NOT IN ('','{{}}')
        {limit_sql}
    """)

    rows = read_cursor.fetchall() if args.limit else None
    if args.limit:
        print(f"读到 {len(rows)} 行")
    else:
        print("流式读取中...")

    converted = 0
    unmapped_keys = 0
    batch = []

    row_iter = rows if args.limit else read_cursor
    for row in row_iter:
        (rid, cname, cfull, ccode, web, isweb, prod, biz, ind, icf, ics, ict,
         explain, cert, ver, utime) = row

        d = parse_dict_field(ict)
        if d is None:
            continue

        new_d = convert_keys(d, mapping)

        # 检查是否有未映射的 key
        has_unmapped = any(k.startswith("[未映射]") for k in new_d)
        if has_unmapped:
            unmapped_keys += 1

        # 取第一个有效映射的 full_name 作为 first/second 的来源
        first_new = ""
        second_new = ""
        for k in new_d:
            if not k.startswith("[未映射]"):
                f, s = split_levels(k)
                first_new = f
                second_new = s
                break

        new_ict = str(new_d)

        if not args.dry_run:
            batch.append((rid, cname, cfull, ccode, web, isweb, prod, biz, ind,
                          first_new, second_new, new_ict, explain, cert, ver, utime))
            if len(batch) >= BATCH_SIZE:
                cursor.executemany(f"""
                    INSERT INTO {TARGET_TABLE}
                    (id, company_name, company_name_full, credit_code, website, is_official_website,
                     product, business, industry, industry_class_first, industry_class_second,
                     industry_class_third, `explain`, certainty, version, update_time)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, batch)
                conn.commit()
                print(f"  写入 {len(batch)} 行, 累计 {converted + len(batch)}", flush=True)
                batch = []

        converted += 1
        if converted % 100000 == 0:
            print(f"  已处理 {converted} 行...", flush=True)

    # 写剩余批次
    if not args.dry_run and batch:
        cursor.executemany(f"""
            INSERT INTO {TARGET_TABLE}
            (id, company_name, company_name_full, credit_code, website, is_official_website,
             product, business, industry, industry_class_first, industry_class_second,
             industry_class_third, `explain`, certainty, version, update_time)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, batch)
        conn.commit()
        print(f"  写入剩余 {len(batch)} 行")

    print(f"\n=== 汇总 ===")
    print(f"转换行数: {converted}")
    print(f"含未映射key的行数: {unmapped_keys} (这些行保留原key并加[未映射]前缀, 便于事后查漏)")
    if not args.dry_run:
        cursor.execute(f"SELECT COUNT(*) FROM {TARGET_TABLE}")
        print(f"目标表 {TARGET_TABLE} 最终行数: {cursor.fetchone()[0]}")

    cursor.close()
    conn.close()
    read_cursor.close()
    read_conn.close()
    print("\n完成. 下一步: 在 step4_company_match_nodes.py 把 source_table 改为 ent_industry_class_new_converted 测试匹配率.")


if __name__ == "__main__":
    main()
