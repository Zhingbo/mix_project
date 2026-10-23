"""
串行重跑 22 个产业链第二阶段（直接调函数版）。

step 4 用优化版 step4_company_match_nodes_v2（SQL LIKE，快36倍）。
其他步骤用原版函数。

用法:
    cd /root/mix_project
    /root/anaconda3/bin/python scripts/serial_rerun_v2.py          # 全部22个
    /root/anaconda3/bin/python scripts/serial_rerun_v2.py 工业机器人  # 只跑指定的
"""
import sys
import time
import pymysql
from datetime import datetime

sys.path.insert(0, '/root/mix_project')

from pipeline_routes import TABLES

# step 4 用优化版
from steps.step4_company_match_nodes_v2 import step4_company_match_nodes as step4_v2
# 其他步骤用原版
from steps.step2_generate_definition import step2_generate_definition
from steps.step3_match_industryry import step3_match_industryry as step3_match_industry
from steps.step5_search_top_companies import step5_search_top_companies
from steps.step6_top_company_match import step6_top_company_match
from steps.step7_split_results import step7_split_results
from steps.step8_merge_and_clean import step8_merge_and_clean
from steps.step9_export_finallist import step9_export_finallist
from steps.step10_export_online_tables import step10_export_online_tables

DB_CONFIG = {
    'host': '8.141.5.67', 'port': 3306, 'user': 'root',
    'password': os.getenv('DB_PASSWORD'), 'database': 'business_data', 'charset': 'utf8mb4',
}

ALL_INDUSTRIES = [
    "储能", "光伏产业", "人工智能", "大飞机", "合成生物",
    "氢能产业", "工业软件", "AI智能算力", "可控核聚变", "工业元宇宙", "生物医药",
]

# 已有 finallist 数据的(只需从 step 10 开始)
HAS_FINALLIST = set()

LOG_FILE = "/root/mix_project/logs/serial_rerun_v2.log"


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


def check_finished(industry_name):
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name = %s", (industry_name,))
    count = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return count > 0


def run_one(industry_name):
    """串行跑一个产业链的所有步骤"""
    start_step = 10 if industry_name in HAS_FINALLIST else 2

    log(f"\n{'='*50}")
    log(f"开始: {industry_name} (从 step {start_step} 开始)")
    log(f"{'='*50}")
    t0 = time.time()

    try:
        if start_step <= 2:
            log(f"  step 2: 生成节点定义...")
            step2_generate_definition(industry_name, TABLES)

        if start_step <= 3:
            log(f"  step 3: 节点匹配行业...")
            step3_match_industry(industry_name, TABLES)

        if start_step <= 4:
            log(f"  step 4: 公司匹配节点 (优化版)...")
            t4 = time.time()
            step4_v2(industry_name, TABLES)
            log(f"  step 4 完成, 耗时 {time.time()-t4:.0f}s")

        if start_step <= 5:
            log(f"  step 5: 搜索头部企业...")
            step5_search_top_companies(industry_name, TABLES)

        if start_step <= 6:
            log(f"  step 6: 头部企业匹配节点...")
            step6_top_company_match(industry_name, TABLES)

        if start_step <= 7:
            log(f"  step 7: 拆分结果...")
            step7_split_results(industry_name, TABLES)

        if start_step <= 8:
            log(f"  step 8: 合并去重清理...")
            step8_merge_and_clean(industry_name, TABLES)

        if start_step <= 9:
            log(f"  step 9: 输出最终名单...")
            step9_export_finallist(industry_name, TABLES)

        # step 10 一定要跑
        log(f"  step 10: 输出上线表...")
        step10_export_online_tables(industry_name, TABLES)

        dt = time.time() - t0
        if check_finished(industry_name):
            log(f"  ✅ {industry_name} 完成, 总耗时 {dt:.0f}s")
            return True
        else:
            log(f"  ⚠️ {industry_name} 完成但 company_list_output 无数据, 总耗时 {dt:.0f}s")
            return False

    except Exception as e:
        log(f"  ❌ {industry_name} 失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    industries = sys.argv[1:] if len(sys.argv) > 1 else ALL_INDUSTRIES

    log("=" * 60)
    log(f"串行重跑 {len(industries)} 个产业链 (step4优化版)")
    log("=" * 60)

    success = []
    failed = []

    for i, ind in enumerate(industries, 1):
        log(f"\n[{i}/{len(industries)}]")
        ok = run_one(ind)
        if ok:
            success.append(ind)
        else:
            failed.append(ind)

    log(f"\n{'='*60}")
    log(f"全部完成: {len(success)} 成功, {len(failed)} 失败")
    if failed:
        log(f"失败的: {failed}")
    log("=" * 60)


if __name__ == "__main__":
    main()
