"""
串行重跑 22 个产业链第二阶段（一个一个来，避免并发读 877 万行导致超时）。

对已有 finallist 数据的产业链（量子科技、卫星导航、低空经济、大飞机），从 step 10 开始。
对其余 18 个，从 step 2 全量重跑。

用法:
    cd /root/mix_project
    /root/anaconda3/bin/python scripts/serial_rerun.py          # 全部串行
    /root/anaconda3/bin/python scripts/serial_rerun.py 集成电路   # 只跑指定的
"""
import requests
import time
import sys
import json
from datetime import datetime

API_BASE = "http://127.0.0.1:8001"
LOGIN_URL = f"{API_BASE}/api/auth/login"
PROCESS_URL = f"{API_BASE}/api/pipeline/process"
STOP_URL = f"{API_BASE}/api/pipeline/stop"
STATUS_QUERY = """
SELECT current_step, progress, status, error_message
FROM pipeline_task_status WHERE industry_name = %s
"""

import pymysql

DB_CONFIG = {
    'host': '8.141.5.67',
    'port': 3306,
    'user': 'root',
    'password': os.getenv('DB_PASSWORD'),
    'database': 'business_data',
    'charset': 'utf8mb4',
}

# 22 个产业链(DB实际名)
ALL_INDUSTRIES = [
    "储能", "光伏产业", "人工智能", "大飞机", "合成生物",
    "氢能产业", "工业软件", "AI智能算力", "可控核聚变", "工业元宇宙", "生物医药",
]

# 已有 finallist 数据的(只需从 step 10 开始)
HAS_FINALLIST = set()

LOG_FILE = "/root/mix_project/logs/serial_rerun.log"


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


def login():
    resp = requests.post(LOGIN_URL, json={"username": "admin", "password": "admin123"}, timeout=10)
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError(f"登录失败: {resp.json()}")
    return token


def trigger(token, industry_name, start_step):
    """触发并等待完成（SSE 流式读取直到结束）"""
    headers = {"Authorization": f"Bearer {token}"}
    body = {"industry_name": industry_name, "start_step": start_step, "force": True}

    try:
        resp = requests.post(PROCESS_URL, json=body, headers=headers, timeout=None, stream=True)
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"

        # 读取 SSE 流直到结束
        for line in resp.iter_lines(decode_unicode=True):
            if line:
                # 检查是否有完成或错误标志
                if "完成" in line and ("处理完成" in line or "步骤10完成" in line):
                    return True, line
                if "error" in line.lower() or "失败" in line:
                    # 继续读，可能是中间步骤的日志
                    pass
        # SSE 流结束
        return True, "stream ended"
    except Exception as e:
        return False, str(e)


def check_finished(industry_name):
    """查数据库确认是否真的完成了(company_list_output 有数据)"""
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name = %s", (industry_name,))
    count = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return count > 0


def run_one(token, industry_name):
    """串行跑一个产业链"""
    start_step = 10 if industry_name in HAS_FINALLIST else 2

    log(f"开始: {industry_name} (从 step {start_step} 开始)")
    t0 = time.time()

    ok, msg = trigger(token, industry_name, start_step)
    dt = time.time() - t0

    if ok:
        # 等 5 秒让数据库写入
        time.sleep(5)
        if check_finished(industry_name):
            log(f"  ✅ {industry_name} 完成, 耗时 {dt:.0f}s")
            return True
        else:
            log(f"  ⚠️ {industry_name} SSE 结束但 company_list_output 无数据, 耗时 {dt:.0f}s")
            return False
    else:
        log(f"  ❌ {industry_name} 失败: {msg}, 耗时 {dt:.0f}s")
        return False


def main():
    industries = sys.argv[1:] if len(sys.argv) > 1 else ALL_INDUSTRIES

    log("=" * 60)
    log(f"串行重跑 {len(industries)} 个产业链")
    log("=" * 60)

    token = login()
    log("登录成功")

    success = []
    failed = []

    for i, ind in enumerate(industries, 1):
        log(f"\n[{i}/{len(industries)}] {ind}")
        ok = run_one(token, ind)
        if ok:
            success.append(ind)
        else:
            failed.append(ind)

    log(f"\n{'=' * 60}")
    log(f"全部完成: {len(success)} 成功, {len(failed)} 失败")
    if failed:
        log(f"失败的: {failed}")
    log("=" * 60)


if __name__ == "__main__":
    main()
