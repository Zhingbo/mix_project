# -*- coding: utf-8 -*-
"""
产业链特殊后置处理（在 step10 之后自动执行，仅针对特定链）
工业软件优化规则：
  1) '研发设计类软件' 母节点(level=2) 下 score=1 的弱相关企业删除
     （名称笼统导致过匹配，如"信用管理/分公司"被误挂；保留 score>=2 与五个细分方向）
  2) '应用领域' + 8个细分方向 下 score=1 的弱相关企业删除，保留核心企业(score>=2)
非目标链直接返回 skipped，不影响其它产业链。
"""
import os
import pymysql

DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', connect_timeout=30,
          read_timeout=3600, write_timeout=3600)

# 需要按 score=1 清理的节点(工业软件)
_TARGET_NODES = ('研发设计类软件', '应用领域', '其他应用领域', '安防电子', '工业通信',
                 '机械设备', '汽车制造', '能源电子', '航空航天', '轨道交通')


def apply_chain_special_processing(industry_name, tables=None, progress_callback=None):
    if industry_name != '工业软件':
        return {'status': 'skipped', 'reason': f'{industry_name} 无特殊处理'}

    conn = pymysql.connect(**DB)
    cur = conn.cursor()
    detail = {}

    nodes_sql = ",".join("'" + n.replace("'", "''") + "'" for n in _TARGET_NODES)
    cond = f"""industry_name=%s AND (
        nodes IN ({nodes_sql}) AND score='1'
    )"""

    # 备份待删 finallist 行(可回滚)
    cur.execute("DROP TABLE IF EXISTS bak_gyrj_special_fin")
    cur.execute(f"CREATE TABLE bak_gyrj_special_fin AS SELECT * FROM company_nodes_finallist WHERE {cond}", (industry_name,))
    cur.execute("SELECT COUNT(*) FROM bak_gyrj_special_fin")
    detail['finallist_deleted'] = cur.fetchone()[0]

    # 删 finallist
    cur.execute(f"DELETE FROM company_nodes_finallist WHERE {cond}", (industry_name,))
    conn.commit()

    # 删 list_output(按 company_name + 层级3=节点 精确匹配，多节点企业只删弱相关那一行)
    cur.execute("""DELETE l FROM company_list_output l
        JOIN bak_gyrj_special_fin b
          ON l.供应商 COLLATE utf8mb4_0900_ai_ci = b.company_name COLLATE utf8mb4_0900_ai_ci
         AND l.层级3 COLLATE utf8mb4_0900_ai_ci = b.nodes COLLATE utf8mb4_0900_ai_ci
        WHERE l.industry_name=%s""", (industry_name,))
    detail['list_output_deleted'] = cur.rowcount
    conn.commit()

    # 删 mapping / merge_temp (防复现)
    for tbl in ['company_nodes_mapping', 'company_nodes_merge_temp']:
        try:
            cur.execute(f"""DELETE x FROM {tbl} x
                JOIN bak_gyrj_special_fin b
                  ON x.company_name COLLATE utf8mb4_0900_ai_ci = b.company_name COLLATE utf8mb4_0900_ai_ci
                 AND x.nodes COLLATE utf8mb4_0900_ai_ci = b.nodes COLLATE utf8mb4_0900_ai_ci
                WHERE x.industry_name=%s""", (industry_name,))
            detail[f'{tbl}_deleted'] = cur.rowcount
            conn.commit()
        except Exception as e:
            detail[f'{tbl}_error'] = str(e)

    cur.execute("DROP TABLE IF EXISTS bak_gyrj_special_fin")
    conn.commit()
    cur.close()
    conn.close()
    return {'status': 'completed', 'reason': '工业软件定向优化完成', **detail}