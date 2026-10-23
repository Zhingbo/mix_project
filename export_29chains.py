# -*- coding: utf-8 -*-
# 重跑完成后, 批量导出 29 条链 -> 3 sheet xlsx(最终名单/结构表/企业表+成立时间)
import pymysql
import pandas as pd
import os
import sys
from datetime import datetime

CHAINS = ["3D打印", "5G", "AI智能算力", "人工智能", "人形机器人", "仪器仪表", "低空经济",
          "储能", "光伏产业", "卫星导航", "可控核聚变", "合成生物", "商业航天", "大飞机",
          "工业元宇宙", "工业母机产业链", "工业软件", "新能源汽车", "无人机", "机器人",
          "检验检测", "氢能产业", "激光", "脑机接口", "船舶海工", "跨境电商", "量子科技",
          "集成电路", "自动驾驶"]

MAXR = 1000000
BATCH = 500
LOCAL = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
             database="business_data", charset="utf8mb4", connect_timeout=60)
RDS = dict(host="rm-2zej668f34v6xr91wdo.mysql.rds.aliyuncs.com", port=3306,
           user="root", password=os.getenv("DB_PASSWORD_ZS"), database="zs_digital_staff_db",
           charset="utf8mb4", connect_timeout=60, read_timeout=60)
RDS_TABLE = "enterprise_establish_time_chain_scope_20260928"
OUTDIR = "/root/mix_project/产业链导出_重跑_20261015"
LOG = "/root/mix_project/logs/export_29chains.log"
os.makedirs(OUTDIR, exist_ok=True)


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def build_est_map(companies):
    m = {}
    if not companies:
        return m
    rdb = pymysql.connect(**RDS)
    rc = rdb.cursor()
    for i in range(0, len(companies), BATCH):
        b = companies[i:i + BATCH]
        ph = ",".join(["%s"] * len(b))
        rc.execute(f"SELECT company_name, establish_time, establish_year "
                   f"FROM {RDS_TABLE} WHERE company_name IN ({ph})", b)
        for n, t, y in rc.fetchall():
            m[n] = (t, y)
    rc.close()
    rdb.close()
    return m


def fmt(t):
    if t is None:
        return ""
    if hasattr(t, "strftime"):
        return t.strftime("%Y-%m-%d")
    return str(t).strip()[:10]


def get_level_cols(conn):
    """动态发现 company_list_output 的层级列(层级1..层级N)，避免固定写死3列丢高层级数据"""
    cur = conn.cursor()
    cur.execute("SHOW COLUMNS FROM company_list_output")
    cols = [r[0] for r in cur.fetchall() if str(r[0]).startswith("层级")]
    cur.close()
    def key(c):
        try:
            return int(str(c).replace("层级", ""))
        except Exception:
            return 0
    cols.sort(key=key)
    return cols


def main():
    chains = sys.argv[1:] if len(sys.argv) > 1 else CHAINS
    conn = pymysql.connect(**LOCAL)
    level_cols = get_level_cols(conn)
    level_sel = ", ".join(f"`{c}`" for c in level_cols) if level_cols else "`层级1`, `层级2`, `层级3`"
    log(f"  list_output 层级列: {level_cols}")
    for ch in chains:
        t0 = datetime.now()
        log(f"=== {ch} 导出开始 ===")
        try:
            df_fin = pd.read_sql(
                "SELECT company_name AS 企业名称, industry_name AS 产业链, nodes AS 节点, "
                "node_level AS 节点层级, parent_node AS 父节点, score AS 置信度 "
                "FROM company_nodes_finallist WHERE industry_name=%s ORDER BY id LIMIT %s",
                conn, params=(ch, MAXR))
            df_struct = pd.read_sql(
                "SELECT id AS 编码, nodes AS 产业环节, parent_node AS 父节点, "
                "parent_id AS 父级id, node_level AS 级别 "
                "FROM industrial_chain.industrial_chain_structure WHERE chain_name=%s "
                "ORDER BY node_level, id", conn, params=(ch,))
            df_company = pd.read_sql(
                f"SELECT {level_sel}, `供应商` FROM company_list_output "
                "WHERE industry_name=%s ORDER BY id LIMIT %s", conn, params=(ch, MAXR))

            companies = [str(x) for x in df_company["供应商"].tolist() if x]
            uniq = list(dict.fromkeys(companies))
            log(f"  企业表 {len(df_company)} 行, 去重 {len(uniq)}, 匹配成立时间...")
            emap = build_est_map(uniq)

            def match_est(sup):
                if not sup:
                    return ("", "", "未匹配")
                r = emap.get(str(sup))
                if r and (r[0] or r[1]):
                    return (fmt(r[0]), r[1] or "", "已匹配")
                return ("", "", "未匹配")

            est = df_company["供应商"].map(match_est)
            df_company["成立时间"] = [x[0] for x in est]
            df_company["注册年份"] = [x[1] for x in est]
            df_company["匹配状态"] = [x[2] for x in est]

            f = os.path.join(OUTDIR, f"{ch}_企业名单.xlsx")
            with pd.ExcelWriter(f, engine="openpyxl") as w:
                df_fin.to_excel(w, sheet_name="最终名单", index=False)
                df_struct.to_excel(w, sheet_name="结构表", index=False)
                df_company.to_excel(w, sheet_name="企业表", index=False)
            dt = (datetime.now() - t0).total_seconds()
            log(f"  ✅ {ch} 导出完成: 最终{len(df_fin)}/结构{len(df_struct)}/企业{len(df_company)} 耗时{dt:.0f}s -> {f}")
        except Exception as e:
            log(f"  ❌ {ch} 导出失败: {e}")
    conn.close()
    log("全部导出结束")


if __name__ == "__main__":
    main()