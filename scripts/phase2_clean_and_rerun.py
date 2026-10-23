"""
清空 22 个产业链的第二阶段数据（不动第一阶段图谱）。

清空范围:
- 第二阶段各步骤产生的结果表(DELETE 整行)
- chain_needcomp.nodes_definition 字段(置 NULL,保留节点结构)
- ent_industry_class_chain_scope_20260928_converted.company_name_full 字段(只清该产业链相关企业,置 NULL)
- 第一阶段 industrial_chain 库的图谱完全不动

用法:
    cd /root/mix_project
    /root/anaconda3/bin/python scripts/phase2_clean_and_rerun.py clean          # 清空全部22个
    /root/anaconda3/bin/python scripts/phase2_clean_and_rerun.py clean 大飞机    # 只清"大飞机"一个
    /root/anaconda3/bin/python scripts/phase2_clean_and_rerun.py rerun         # 仅重跑
    /root/anaconda3/bin/python scripts/phase2_clean_and_rerun.py clean_rerun  # 清空+重跑
    /root/anaconda3/bin/python scripts/phase2_clean_and_rerun.py status        # 查看当前数据状态
"""
import pymysql
import requests
import time
import sys
import json
from datetime import datetime

# ==================== 配置 ====================

DB_CONFIG = {
    'host': '8.141.5.67',
    'port': 3306,
    'user': 'root',
    'password': os.getenv('DB_PASSWORD'),
    'database': 'business_data',
    'charset': 'utf8mb4',
    'connect_timeout': 60,
    'read_timeout': 120,
    'write_timeout': 120,
}

API_BASE = "http://127.0.0.1:8001"
LOGIN_URL = f"{API_BASE}/api/auth/login"
PROCESS_URL = f"{API_BASE}/api/pipeline/process"

ADMIN_USER = "admin"
ADMIN_PASS = "admin123"

# 22 个产业链(标准名 -> 数据库实际名)
INDUSTRY_MAP = {
    "集成电路": "集成电路",
    "机器人": "工业机器人",
    "工业软件": "工业软件",
    "卫星导航": "卫星导航",
    "大飞机": "大飞机",
    "仪器仪表": "仪器仪表",
    "工业母机": "工业母机产业链",
    "3D打印": "3D打印",
    "人工智能": "人工智能",
    "激光产业": "激光",
    "合成生物": "合成生物",
    "光伏产业": "光伏产业",
    "5G产业": "5G",
    "低空经济": "低空经济",
    "储能产业": "储能",
    "跨境电商": "跨境电商",
    "脑机接口": "脑机接口",
    "量子科技": "量子科技",
    "工业元宇宙": "工业元宇宙",
    "商业航天": "商业航天",
    "可控核聚变": "可控核聚变",
    "智能算力": "AI智能算力",
}

# 第二阶段各表 + WHERE 字段
PHASE2_TABLES = [
    ("nodes_industry_mapping",        "industry_name"),
    ("company_nodes_mapping",         "industry_name"),
    ("company_nodes_mapping_temp",     "industry_name"),
    ("company_nodes_top",             "industry_chain"),
    ("company_nodes_info_result",     "industry_name"),
    ("company_nodes_info_split",      "industry_name"),
    ("company_nodes_final",           "industry_name"),
    ("company_nodes_finallist",       "industry_name"),
    ("company_nodes_merge_temp",      "industry_name"),
    ("industry_structure_output",     "industry_name"),
    ("company_list_output",           "industry_name"),
]

MAX_CONCURRENT = 2
LOG_FILE = "/root/mix_project/logs/phase2_clean_rerun.log"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        import os
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ==================== 清空 ====================

def clean_industry(conn, chain_name):
    """清空单个产业链的第二阶段数据（只清该产业链,不碰其他产业链和第一阶段图谱）"""
    cursor = conn.cursor()
    deleted = {}

    # 0. 先查出该产业链的企业名列表(用于精准清 ent_industry_class_chain_scope_20260928_converted)
    #    必须在 DELETE company_nodes_mapping 之前查,否则查不到了
    try:
        cursor.execute(
            "SELECT DISTINCT company_name FROM company_nodes_mapping WHERE industry_name = %s",
            (chain_name,)
        )
        company_list = [r[0] for r in cursor.fetchall() if r[0]]
    except Exception as e:
        company_list = []
        deleted["ent_industry_class_chain_scope_20260928_converted.company_name_full"] = f"SKIP(查企业列表失败: {e})"

    # 1. DELETE 各结果表(整行,按 industry_name/industry_chain 过滤)
    for table, field in PHASE2_TABLES:
        sql = f"DELETE FROM `{table}` WHERE `{field}` = %s"
        try:
            cursor.execute(sql, (chain_name,))
            deleted[table] = cursor.rowcount
        except Exception as e:
            deleted[table] = f"ERROR: {e}"
            conn.rollback()
    conn.commit()

    # 2. chain_needcomp: 只清 nodes_definition 字段(保留节点结构)
    try:
        cursor.execute(
            "UPDATE chain_needcomp SET nodes_definition = NULL WHERE chain_name = %s",
            (chain_name,)
        )
        deleted["chain_needcomp.nodes_definition"] = cursor.rowcount
        conn.commit()
    except Exception as e:
        deleted["chain_needcomp.nodes_definition"] = f"ERROR: {e}"
        conn.rollback()

    # 3. ent_industry_class_chain_scope_20260928_converted: 只清该产业链相关企业的 company_name_full
    #    分批 IN 查询,避免单条 SQL 过长;绝不做全表 UPDATE
    if company_list:
        BATCH = 500
        total_updated = 0
        for i in range(0, len(company_list), BATCH):
            batch = company_list[i:i + BATCH]
            placeholders = ",".join(["%s"] * len(batch))
            try:
                cursor.execute(
                    f"UPDATE ent_industry_class_chain_scope_20260928_converted "
                    f"SET company_name_full = NULL "
                    f"WHERE company_name IN ({placeholders})",
                    batch
                )
                total_updated += cursor.rowcount
            except Exception as e:
                deleted["ent_industry_class_chain_scope_20260928_converted.company_name_full"] = f"ERROR(batch {i}): {e}"
                conn.rollback()
                break
        else:
            conn.commit()
            deleted["ent_industry_class_chain_scope_20260928_converted.company_name_full"] = total_updated
    elif "ent_industry_class_chain_scope_20260928_converted.company_name_full" not in deleted:
        deleted["ent_industry_class_chain_scope_20260928_converted.company_name_full"] = "SKIP(无企业列表)"

    cursor.close()
    return deleted


def run_clean(industries=None):
    """执行清空。industries 为 None 则清全部22个,否则只清指定的"""
    if industries is None:
        industries = list(INDUSTRY_MAP.items())
    else:
        # 把标准名转成 (标准名, 数据库名)
        industries = [(name, INDUSTRY_MAP[name]) for name in industries if name in INDUSTRY_MAP]

    log("=" * 60)
    log(f"开始清空 {len(industries)} 个产业链第二阶段数据")
    log("=" * 60)

    conn = pymysql.connect(**DB_CONFIG)
    total_deleted = 0

    for std_name, db_name in industries:
        log(f"\n--- 清空: {std_name} (DB名: {db_name}) ---")
        deleted = clean_industry(conn, db_name)
        for table, count in deleted.items():
            if isinstance(count, int):
                total_deleted += count
                log(f"  {table}: {count} 行")
            else:
                log(f"  {table}: {count}")
        log(f"  {std_name} 清空完成")

    conn.close()
    log(f"\n{'=' * 60}")
    log(f"清空完成,总删除 {total_deleted} 行")
    log("=" * 60)


# ==================== 重跑 ====================

def login():
    """登录拿 token"""
    resp = requests.post(LOGIN_URL, json={"username": ADMIN_USER, "password": ADMIN_PASS}, timeout=10)
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"登录失败: {data}")
    log(f"登录成功")
    return token


def trigger_rerun(token, industry_name):
    """触发单个产业链的重跑(非阻塞,只发请求确认启动)"""
    headers = {"Authorization": f"Bearer {token}"}
    body = {"industry_name": industry_name, "start_step": 2, "force": True}
    try:
        resp = requests.post(PROCESS_URL, json=body, headers=headers, timeout=30, stream=True)
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        # 读前几行 SSE 确认任务已启动
        started = False
        for line in resp.iter_lines(decode_unicode=True):
            if line:
                started = True
                break
        return True, "triggered" if started else "triggered(no_confirm)"
    except Exception as e:
        return False, str(e)


def run_rerun(industries=None):
    """执行重跑(并发 MAX_CONCURRENT)"""
    if industries is None:
        industries = list(INDUSTRY_MAP.items())
    else:
        industries = [(name, INDUSTRY_MAP[name]) for name in industries if name in INDUSTRY_MAP]

    log("=" * 60)
    log(f"开始重跑 {len(industries)} 个产业链,并发={MAX_CONCURRENT}")
    log("=" * 60)

    token = login()

    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    results = {}
    results_lock = threading.Lock()

    def rerun_one(std_name, db_name):
        log(f"\n--- 触发重跑: {std_name} (DB名: {db_name}) ---")
        ok, msg = trigger_rerun(token, db_name)
        with results_lock:
            results[std_name] = {"ok": ok, "msg": msg, "db_name": db_name}
        if ok:
            log(f"  {std_name} 已触发,等待完成...")
        else:
            log(f"  {std_name} 触发失败: {msg}")
        return std_name, ok

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:
        futures = []
        for std_name, db_name in industries:
            futures.append(executor.submit(rerun_one, std_name, db_name))
        for f in as_completed(futures):
            std_name, ok = f.result()
            log(f"  {std_name} 完成: {'成功' if ok else '失败'}")

    log(f"\n{'=' * 60}")
    log("所有产业链已触发重跑")
    log("注意:任务在后端异步执行,需通过前端或 status 命令查看完成情况")
    log("=" * 60)


# ==================== 状态查看 ====================

def run_status():
    """查看 22 个产业链的当前数据状态"""
    log("=" * 60)
    log("22 个产业链第二阶段数据状态")
    log("=" * 60)

    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    print(f"\n{'产业链':<14} {'chain_needcomp':>14} {'nodes_mapping':>14} {'nodes_industry':>14} {'finallist':>10} {'company_list':>12}")
    print("-" * 90)

    for std_name, db_name in INDUSTRY_MAP.items():
        cursor.execute("SELECT COUNT(*) FROM chain_needcomp WHERE chain_name=%s", (db_name,))
        cn = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM nodes_industry_mapping WHERE industry_name=%s", (db_name,))
        ni = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM company_nodes_mapping WHERE industry_name=%s", (db_name,))
        nm = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (db_name,))
        fl = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name=%s", (db_name,))
        cl = cursor.fetchone()[0]
        print(f"{std_name:<14} {cn:>14} {nm:>14} {ni:>14} {fl:>10} {cl:>12}")

    cursor.close()
    conn.close()


# ==================== 主入口 ====================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    extra = sys.argv[2:]  # 可选:指定产业链名

    if cmd == "clean":
        run_clean(extra if extra else None)
    elif cmd == "rerun":
        run_rerun(extra if extra else None)
    elif cmd == "clean_rerun":
        run_clean(extra if extra else None)
        log("\n等待 5 秒后开始重跑...\n")
        time.sleep(5)
        run_rerun(extra if extra else None)
    elif cmd == "status":
        run_status()
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
