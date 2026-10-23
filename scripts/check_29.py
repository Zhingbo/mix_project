# -*- coding: utf-8 -*-
import os
import pymysql
c = pymysql.connect(host='8.141.5.67', port=3306, user='root',
                    password=os.getenv('DB_PASSWORD'), database='business_data', charset='utf8mb4')
cur = c.cursor()
chains = ['3D打印', '5G', 'AI智能算力', '人工智能', '人形机器人', '仪器仪表', '低空经济',
          '储能', '光伏产业', '卫星导航', '可控核聚变', '合成生物', '商业航天', '大飞机',
          '工业元宇宙', '工业母机产业链', '工业软件', '新能源汽车', '无人机', '机器人',
          '检验检测', '氢能产业', '激光', '脑机接口', '船舶海工', '跨境电商', '量子科技',
          '集成电路', '自动驾驶']
done = run = fail = 0
for ch in chains:
    cur.execute("SELECT status,current_step FROM pipeline_task_status WHERE industry_name=%s ORDER BY id DESC LIMIT 1", (ch,))
    r = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (ch,))
    fin = cur.fetchone()[0]
    st = r[0] if r else '?'
    step = r[1] if r else '-'
    if st == 'completed' and fin > 0:
        mark, done = 'OK', done + 1
    elif st == 'running':
        mark, run = 'RUN', run + 1
    else:
        mark, fail = 'FAIL', fail + 1
    print(f"{ch}\t{st}\tstep{step}\tfin={fin}\t{mark}")
cur.close(); c.close()
print(f"\n完成={done} 运行中={run} 失败/未跑={fail}")