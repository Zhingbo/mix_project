# -*- coding: utf-8 -*-
import os
import pymysql

c = pymysql.connect(host='8.141.5.67', port=3306, user='root',
                    password=os.getenv('DB_PASSWORD'), database='business_data',
                    charset='utf8mb4')
cur = c.cursor()

cur.execute("""
    SELECT industry_name, status, current_step, updated_at
    FROM pipeline_task_status
    WHERE id IN (SELECT MAX(id) FROM pipeline_task_status GROUP BY industry_name)
    ORDER BY industry_name
""")
rows = cur.fetchall()
print('共 %d 条链' % len(rows))
for industry_name, status, step, updated in rows:
    cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s",
                (industry_name,))
    fin = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name=%s",
                (industry_name,))
    out = cur.fetchone()[0]
    print(f"{industry_name}\t{status}\tstep{step}\tfin={fin}\tout={out}\t{updated}")

cur.close()
c.close()
print('DONE')