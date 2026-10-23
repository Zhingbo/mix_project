# -*- coding: utf-8 -*-
"""监控 AI智能算力 重跑: 轮询 task_status / mapping / finallist / list_output, 写到文件"""
import os
import pymysql, time, os

DB = dict(host="127.0.0.1", user="root", password=os.getenv("DB_PASSWORD"),
          database="business_data", charset="utf8mb4", connect_timeout=15)
OUT = "/root/mix_project/regen_ai2_final.txt"
PROGRESS = "/root/mix_project/regen_ai2_progress.txt"

def q(cur, sql, *args):
    cur.execute(sql, args)
    return cur.fetchone()[0]

def snap(cur):
    return {
        "mapping": q(cur, "SELECT COUNT(*) FROM company_nodes_mapping WHERE industry_name=%s", "AI智能算力"),
        "merge": q(cur, "SELECT COUNT(*) FROM company_nodes_merge_temp WHERE industry_name=%s", "AI智能算力"),
        "finallist": q(cur, "SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", "AI智能算力"),
        "list_output": q(cur, "SELECT COUNT(*) FROM company_list_output WHERE industry_name=%s", "AI智能算力"),
    }

c = pymysql.connect(**DB)
cur = c.cursor()
t0 = time.time()
last_map = None
while True:
    cur.execute("SELECT status, current_step, progress FROM pipeline_task_status "
                "WHERE industry_name=%s ORDER BY id DESC LIMIT 1", ("AI智能算力",))
    row = cur.fetchone()
    status, step, prog = (row[0], row[1], row[2]) if row else (None, None, None)
    s = snap(cur)
    with open(PROGRESS, "w") as f:
        f.write(f"elapsed={time.time()-t0:.0f}s status={status} step={step} prog={prog}\n")
        f.write(f"mapping={s['mapping']} merge={s['merge']} finallist={s['finallist']} list_output={s['list_output']}\n")
    if last_map is None:
        last_map = s["mapping"]
    if status in ("completed", "error", "cancelled"):
        with open(OUT, "w") as f:
            f.write(f"END status={status} step={step} prog={prog} elapsed={time.time()-t0:.0f}s\n")
            for k, v in s.items():
                f.write(f"{k}={v}\n")
        break
    time.sleep(20)
cur.close(); c.close()
print("monitor done")