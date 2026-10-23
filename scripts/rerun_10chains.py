# -*- coding: utf-8 -*-
import os
# 串行 force 重跑 10 条产业链(从 step 2 全量), 逐条触发并等待 SSE 结束, 再核对结果
import requests
import pymysql
import time
import json
import sys
from datetime import datetime

API_BASE = "http://127.0.0.1:8001"
LOGIN_URL = f"{API_BASE}/api/auth/login"
PROCESS_URL = f"{API_BASE}/api/pipeline/process"

DB = dict(host='8.141.5.67', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4')

ALL = ["可控核聚变", "生命健康", "量子科技", "脑机接口", "5G",
       "低空经济", "商业航天", "人形机器人", "集成电路", "卫星导航"]

LOG_FILE = "/root/mix_project/logs/rerun_10chains.log"


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def login():
    r = requests.post(LOGIN_URL, json={"username": "admin", "password": "admin123"}, timeout=15)
    tok = r.json().get("access_token")
    if not tok:
        raise RuntimeError(f"登录失败: {r.text[:200]}")
    return tok


def trigger_and_wait(token, ind, start_step=2):
    headers = {"Authorization": f"Bearer {token}"}
    body = {"industry_name": ind, "start_step": start_step, "force": True}
    last_marker = ""
    try:
        with requests.post(PROCESS_URL, json=body, headers=headers,
                           timeout=None, stream=True) as resp:
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
            for raw in resp.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                line = raw.strip()
                # 进度/步骤标记, 只记简洁摘要
                for key in ("处理步骤", "步骤10", "全量模式", "从步骤", "结构变更", "错误", "失败",
                            "ERROR", "Traceback", "已丢弃"):
                    if key in line and key not in last_marker:
                        log(f"    {ind} | {line[:160]}")
                        last_marker = key
                        break
        return True, "stream ended"
    except Exception as e:
        return False, str(e)


def db_status(ind, poll=40):
    conn = pymysql.connect(**DB)
    cur = conn.cursor()
    terminal = None
    for _ in range(poll):
        cur.execute("SELECT status, current_step, progress, error_message FROM "
                    "pipeline_task_status WHERE industry_name=%s ORDER BY id DESC LIMIT 1", (ind,))
        row = cur.fetchone()
        if row:
            st, step, prog, err = row
            if st in ("completed", "error", "cancelled"):
                terminal = (st, step, prog, err)
                break
        time.sleep(3)
    cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (ind,))
    fin = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name=%s", (ind,))
    lst = cur.fetchone()[0]
    cur.close(); conn.close()
    return terminal, fin, lst


def main():
    inds = sys.argv[1:] if len(sys.argv) > 1 else ALL
    log("=" * 60)
    log(f"串行 force 重跑 {len(inds)} 条链 (从 step 2 全量)")
    log("=" * 60)
    token = login()
    log("登录成功")
    ok, bad = [], []
    for i, ind in enumerate(inds, 1):
        log(f"\n[{i}/{len(inds)}] {ind}")
        t0 = time.time()
        trig_ok, msg = trigger_and_wait(token, ind, 2)
        dt = time.time() - t0
        if not trig_ok:
            log(f"  ❌ {ind} 触发/流失败: {msg} (耗时{dt:.0f}s)")
            bad.append(ind)
            continue
        terminal, fin, lst = db_status(ind)
        status = terminal[0] if terminal else "unknown"
        err = (terminal[3] or "")[:160] if terminal else ""
        log(f"  SSE结束 耗时{dt:.0f}s | 状态={status} | finallist={fin} | list_output={lst}")
        if status == "completed" and lst > 0:
            log(f"  ✅ {ind} 完成")
            ok.append(ind)
        else:
            log(f"  ⚠️ {ind} 未确认完成: status={status} err={err}")
            bad.append(ind)
        time.sleep(2)
    log(f"\n{'=' * 60}")
    log(f"全部结束: 成功 {len(ok)} / 失败或存疑 {len(bad)}")
    if bad:
        log(f"存疑: {bad}")
    log("=" * 60)


if __name__ == "__main__":
    main()