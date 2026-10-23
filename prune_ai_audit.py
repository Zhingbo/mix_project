# -*- coding: utf-8 -*-
import os
# 人工智能校核删减:
#   1) 下游"应用领域"(20个环节) 只保留 score=9999, 删其余
#   2) "AI芯片" 只保留 score=9999, 删其余
# 删除的记录写入留痕表 chain_deleted_company_log (含产业链/环节/置信度/原因/时间)
import pymysql
from datetime import datetime
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', connect_timeout=30,
          read_timeout=3600, write_timeout=3600)
conn = pymysql.connect(**DB)
cur = conn.cursor()
IND = '人工智能'

DOWNSTREAM = ['内容生成','智慧医疗','智慧城市','智慧金融','智能制造','智能安防','智能客服',
               '智能家居','智能推送','智能教育','智能机器人','智能运载工具','智能零售',
               '智能驾驶','虚拟数字人','代码生成','图像生成','文本生成','视频生成','音频生成']

# 1. 建留痕表
cur.execute("""CREATE TABLE IF NOT EXISTS chain_deleted_company_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  industry_name VARCHAR(100) NOT NULL COMMENT '产业链名称',
  company_name VARCHAR(255) NOT NULL COMMENT '企业名称',
  nodes VARCHAR(255) COMMENT '环节名称',
  node_level INT COMMENT '环节层级',
  parent_node VARCHAR(255) COMMENT '父环节',
  score VARCHAR(50) COMMENT '删除前置信度',
  delete_reason VARCHAR(255) COMMENT '删除原因',
  deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '删除时间',
  INDEX idx_chain (industry_name),
  INDEX idx_company (company_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='产业链企业删减留痕表'""")
conn.commit()
log("留痕表 chain_deleted_company_log 就绪")

# 2. 建临时表: 本次要删的 (company, node) + 原因
nodes_sql = ",".join("'" + n.replace("'", "''") + "'" for n in DOWNSTREAM)
cond = f"""industry_name=%s AND (score IS NULL OR score <> '9999')
  AND (nodes='AI芯片' OR nodes IN ({nodes_sql}))"""
cur.execute(f"DROP TABLE IF EXISTS tmp_del_ai")
cur.execute(f"""CREATE TABLE tmp_del_ai AS
  SELECT company_name, nodes, node_level, parent_node, score,
         IF(nodes='AI芯片', 'AI芯片环节仅保留9999强相关', '下游应用领域仅保留9999强相关') AS delete_reason
  FROM company_nodes_finallist WHERE {cond}""", (IND,))
cur.execute("SELECT COUNT(*) FROM tmp_del_ai")
n = cur.fetchone()[0]
log(f"待删除记录: {n} 条")

# 3. 写入留痕表
cur.execute("""INSERT INTO chain_deleted_company_log
  (industry_name, company_name, nodes, node_level, parent_node, score, delete_reason)
  SELECT %s, company_name, nodes, node_level, parent_node, score, delete_reason FROM tmp_del_ai""", (IND,))
log(f"已写入留痕表: {cur.rowcount} 条")
conn.commit()

# 4. 删 finallist (按 company + node 精确匹配, 避免误删多节点企业的其它环节)
cur.execute("""DELETE f FROM company_nodes_finallist f
  JOIN tmp_del_ai t ON f.company_name = t.company_name AND f.nodes = t.nodes
  WHERE f.industry_name=%s""", (IND,))
log(f"finallist 删除: {cur.rowcount} 行")
conn.commit()

# 5. 删 list_output (按 company + 层级3=环节 精确匹配)
cur.execute("""DELETE l FROM company_list_output l
  JOIN tmp_del_ai t
    ON l.供应商 COLLATE utf8mb4_0900_ai_ci = t.company_name COLLATE utf8mb4_0900_ai_ci
   AND l.层级3 COLLATE utf8mb4_0900_ai_ci = t.nodes COLLATE utf8mb4_0900_ai_ci
  WHERE l.industry_name=%s""", (IND,))
log(f"list_output 删除: {cur.rowcount} 行")
conn.commit()

cur.execute("DROP TABLE IF EXISTS tmp_del_ai")
conn.commit()

# 6. 校验
cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (IND,))
log(f"校验 finallist 总量: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name=%s", (IND,))
log(f"校验 list_output 总量: {cur.fetchone()[0]}")
cur.execute("SELECT score, COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s AND (nodes='AI芯片' OR nodes IN (%s)) AND score='9999'", (IND,))
log(f"校验保留的9999(AI芯片+下游): {cur.fetchall()}")

cur.close(); conn.close()
log("===== 人工智能校核删减完成 =====")