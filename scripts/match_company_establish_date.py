"""
从人形机器人企业名单.xlsx 第三个sheet(企业表)取企业名,
去阿里云RDS的 enterprise_base_info_wide_dtsx_update_20260828 表查成立时间,
输出新xlsx含原4列+成立时间+注册年份+匹配状态.

用法:
    cd /root/mix_project/scripts
    source /root/acemcp/.venv/bin/activate
    python match_company_establish_date.py
"""
import openpyxl
import pymysql
import os
from datetime import datetime

# 配置
INPUT_XLSX = "/root/mix_project/生命健康_企业名单.xlsx"
OUTPUT_XLSX = "/root/mix_project/生命健康_企业名单_含成立时间.xlsx"
SHEET_NAME = "企业表"

ALIYUN_DB = {
    "host": "rm-2zej668f34v6xr91wdo.mysql.rds.aliyuncs.com",
    "port": 3306,
    "user": "root",
    "password": os.getenv("DB_PASSWORD_ZS"),
    "database": "zs_digital_staff_db",
    "charset": "utf8mb4",
    "connect_timeout": 60,
    "read_timeout": 60,
}
TABLE = "enterprise_establish_time_chain_scope_20260928"
BATCH_SIZE = 500  # 每批IN查询的企业数


def main():
    print("=" * 60)
    print("企业成立时间匹配")
    print("=" * 60)

    # 1. 读Excel企业名
    wb_in = openpyxl.load_workbook(INPUT_XLSX, read_only=True)
    ws = wb_in[SHEET_NAME]
    rows = []
    for i, row in enumerate(ws.iter_rows(min_row=1, values_only=True)):
        if i == 0:
            header = list(row)
            continue
        company = str(row[3]).strip() if row[3] else ""
        rows.append({
            "row_idx": i + 1,
            "c1": row[0],
            "c2": row[1],
            "c3": row[2],
            "company": company,
        })
    wb_in.close()
    print(f"读到 {len(rows)} 个企业名")

    # 2. 批量查成立时间
    conn = pymysql.connect(**ALIYUN_DB)
    cursor = conn.cursor()
    print(f"连接阿里云RDS, 表 {TABLE}")

    # 先建索引映射: 企业名 -> (establish_time, establish_year)
    result_map = {}
    companies = [r["company"] for r in rows if r["company"]]
    unique_companies = list(dict.fromkeys(companies))  # 去重保序
    print(f"唯一企业名: {len(unique_companies)}")

    matched = 0
    for bi in range(0, len(unique_companies), BATCH_SIZE):
        batch = unique_companies[bi:bi + BATCH_SIZE]
        placeholders = ",".join(["%s"] * len(batch))
        sql = f"""
            SELECT company_name, establish_time, establish_year
            FROM {TABLE}
            WHERE company_name IN ({placeholders})
        """
        try:
            cursor.execute(sql, batch)
            for name, inc_time, reg_year in cursor.fetchall():
                result_map[name] = (inc_time, reg_year)
        except Exception as e:
            print(f"  批 {bi//BATCH_SIZE+1} 查询失败: {e}")
        if (bi // BATCH_SIZE + 1) % 10 == 0:
            print(f"  已查 {min(bi+BATCH_SIZE, len(unique_companies))}/{len(unique_companies)}", flush=True)

    matched = len(result_map)
    print(f"匹配到成立时间: {matched} / {len(unique_companies)} ({matched*100//len(unique_companies)}%)")

    cursor.close()
    conn.close()

    # 3. 写新Excel
    wb_out = openpyxl.Workbook()
    ws_out = wb_out.active
    ws_out.title = SHEET_NAME
    # 表头: 原4列 + 成立时间 + 注册年份 + 匹配状态
    out_header = header + ["成立时间", "注册年份", "匹配状态"]
    ws_out.append(out_header)

    matched_cnt = 0
    for r in rows:
        inc_time, reg_year = result_map.get(r["company"], (None, None))
        status = "已匹配" if inc_time or reg_year else "未匹配"
        if inc_time or reg_year:
            matched_cnt += 1
        # 日期格式化(兼容 date/datetime/str/None)
        if inc_time is None:
            inc_str = ""
        elif hasattr(inc_time, "strftime"):
            inc_str = inc_time.strftime("%Y-%m-%d")
        else:
            s = str(inc_time).strip()
            inc_str = s[:10] if s else ""
        ws_out.append([r["c1"], r["c2"], r["c3"], r["company"], inc_str, reg_year or "", status])

    wb_out.save(OUTPUT_XLSX)
    print(f"\n输出: {OUTPUT_XLSX}")
    print(f"总企业 {len(rows)}, 匹配 {matched_cnt}, 未匹配 {len(rows)-matched_cnt}")


if __name__ == "__main__":
    main()
