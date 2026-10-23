# -*- coding: utf-8 -*-
import os
# 等合成生物跑完后, 自动启动 大飞机 step4 重跑
import pymysql, time, subprocess
from datetime import datetime
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', connect_timeout=15)

def status(chain):
    try:
        c = pymysql.connect(**DB)
        cur = c.cursor()
        cur.execute("SELECT status, current_step, progress FROM pipeline_task_status WHERE industry_name=%s ORDER BY id DESC LIMIT 1", (chain,))
        r = cur.fetchone()
        cur.close(); c.close()
        return r
    except Exception as e:
        return None

log("监控合成生物 ...")
while True:
    r = status('合成生物')
    if r:
        st, step, prog = r
        log(f"  合成生物 status={st} step={step} prog={prog}")
        if st in ('completed', 'error', 'cancelled'):
            break
    time.sleep(60)

log(f"合成生物已结束({r[0]}), 启动 大飞机:4 ...")
subprocess.run(["python3", "/root/mix_project/recover_chains.py", "大飞机:4"])
log("大飞机重跑已启动")