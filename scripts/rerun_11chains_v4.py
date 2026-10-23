# -*- coding: utf-8 -*-
import os
# 第二批补跑 11 条链: 等 v3(9链) 和 lifehealth 都跑完后, 再串行 clear+force 重跑
import requests
import pymysql
import time
import sys
import re
import subprocess
from datetime import datetime

API_BASE = "http://127.0.0.1:8001"
LOGIN_URL = f"{API_BASE}/api/auth/login"
PROCESS_URL = f"{API_BASE}/api/pipeline/process"
DELETE_URL = f"{API_BASE}/api/pipeline/delete_steps"

DB = dict(host='8.141.5.67', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4')

# 11 条补跑链(用库里的准确名)
ALL = ["机器人", "新能源汽车", "检验检测", "无人机", "仪器仪表",
       "工业母机产业链", "3D打印", "激光", "跨境电商", "船舶海工", "自动驾驶"]

LOG_FILE = "/root/mix_project/logs/rerun_11chains_v4.log"


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def proc_alive(pattern):
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True, timeout=10)
        return bool(r.stdout.strip())
    except Exception:
        return False


def wait_predecessors():
    while True:
        v3 = proc_alive("rerun_9chains_v3.py")
        lh = proc_alive("rerun_lifehealth.py")
        # 也要确认没有链还在 running 状态(避免孤儿 gunicorn 任务)
        running = []
        try:
            conn = pymysql.connect(**DB)
            cur = conn.cursor()
            cur.execute("SELECT industry_name FROM pipeline_task_status WHERE status='running'")
            running = [r[0] for r in cur.fetchall()]
            cur.close(); conn.close()
        except Exception:
            running = ["?"]
        if not v3 and not lh and not running:
            log("前置任务(v3 + 生命健康)已全部结束, 开始第二批补跑")
            return
        log(f"等待前置任务: v3运行={v3} 生命健康运行={lh} 库内running={running}")
        time.sleep(180)


def login():
    r = requests.post(LOGIN_URL, json={"username": "admin", "password": "admin123"}, timeout=15)
    tok = r.json().get("access_token")
    if not tok:
        raise RuntimeError(f"登录失败: {r.text[:200]}")
    return tok


def clear_steps(token, ind):
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.post(DELETE_URL, json={"industry_name": ind,
                                        "steps": [2, 3, 4, 5, 6, 7, 8, 9, 10]},
                      headers=headers, timeout=120)
    log(f"    delete_steps(2-10) {ind} -> HTTP {r.status_code}")
    conn = pymysql.connect(**DB)
    cur = conn.cursor()
    for t, col in [("company_nodes_merge_temp", "industry_name"),
                   ("industry_structure_output", "industry_name")]:
        cur.execute(f"DELETE FROM {t} WHERE {col} = %s", (ind,))
    conn.commit()
    cur.close(); conn.close()


def trigger_and_wait(token, ind):
    headers = {"Authorization": f"Bearer {token}"}
    body = {"industry_name": ind, "start_step": 2, "force": True}
    seen = set()
    try:
        with requests.post(PROCESS_URL, json=body, headers=headers,
                           timeout=None, stream=True) as resp:
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
            for raw in resp.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                line = raw.strip()
                m = re.search(r"开始执行步骤(\d+)", line)
                if m:
                    k = f"step{m.group(1)}"
                    if k not in seen:
                        log(f"    {ind} | 进入 step{m.group(1)}")
                        seen.add(k)
                elif "Traceback" in line or ("失败" in line and "已有数据" not in line):
                    log(f"    {ind} | {line[:160]}")
        return True, "stream ended"
    except Exception as e:
        return False, str(e)


def db_status(ind, poll=240, interval=10):
    conn = pymysql.connect(**DB)
    cur = conn.cursor()
    terminal = None
    for _ in range(poll):
        cur.execute("SELECT status, current_step, progress, error_message "
                    "FROM pipeline_task_status WHERE industry_name=%s "
                    "ORDER BY id DESC LIMIT 1", (ind,))
        row = cur.fetchone()
        if row and row[0] in ("completed", "error", "cancelled"):
            terminal = row
            break
        time.sleep(interval)
    cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (ind,))
    fin = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name=%s", (ind,))
    lst = cur.fetchone()[0]
    cur.close(); conn.close()
    return terminal, fin, lst


def main():
    inds = sys.argv[1:] if len(sys.argv) > 1 else ALL
    log("=" * 60)
    log(f"第二批补跑 {len(inds)} 条链: {inds}")
    log("=" * 60)
    wait_predecessors()
    token = login()
    log("登录成功")
    ok, bad = [], []
    for i, ind in enumerate(inds, 1):
        log(f"\n[{i}/{len(inds)}] {ind}")
        try:
            clear_steps(token, ind)
        except Exception as e:
            log(f"  ⚠️ 清空步骤失败 {e}")
        t0 = time.time()
        trig_ok, msg = trigger_and_wait(token, ind)
        dt = time.time() - t0
        if not trig_ok:
            log(f"  ❌ {ind} 流失败: {msg} (耗时{dt:.0f}s)")
            bad.append(ind)
            continue
        terminal, fin, lst = db_status(ind)
        st = terminal[0] if terminal else "unknown"
        err = (terminal[3] or "")[:160] if terminal else ""
        log(f"  SSE结束 耗时{dt:.0f}s | 状态={st} | finallist={fin} | list_output={lst}")
        if st == "completed" and lst > 0:
            log(f"  ✅ {ind} 完成")
            ok.append(ind)
        else:
            log(f"  ⚠️ {ind} 未确认: {st} {err}")
            bad.append(ind)
        time.sleep(3)
    log(f"\n{'=' * 60}")
    log(f"第二批全部结束: 成功 {len(ok)} / 存疑 {len(bad)}")
    if bad:
        log(f"存疑: {bad}")
    log("=" * 60)


if __name__ == "__main__":
    main()