# -*- coding: utf-8 -*-
import os
# 人工智能: 榜单企业追加(不重跑, 保留现有4.09万名单)
# 1) DeepSeek榜单直搜 2) 补画像 3) LLM匹配节点 4) 追加到 finallist + list_output
import sys, time, logging, json
import pymysql
from openai import OpenAI
logging.basicConfig(level=logging.INFO)
sys.path.insert(0, '/root/mix_project')
from steps.step6_top_company_match import _deepseek_search_list_companies, _llm_enrich_company_info

OPENAI_API_KEY = os.getenv("DASHSCOPE_API_KEY")
OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL = "deepseek-v4.1-flash"
IND = '人工智能'

DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', connect_timeout=30,
          read_timeout=3600, write_timeout=3600)
conn = pymysql.connect(**DB)
cur = conn.cursor()

def log(m): print(f"[{__import__('datetime').datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

# 1. 榜单直搜 + 补画像
log("搜索榜单企业...")
comps = _deepseek_search_list_companies(IND)
log(f"搜索到 {len(comps)} 家")
info = _llm_enrich_company_info(comps, IND)
log(f"补画像 {len(info)} 家")

# 2. 读节点列表
cur.execute("SELECT nodes, nodes_definition, node_level, parent_node FROM chain_needcomp WHERE chain_name=%s", (IND,))
nodes = cur.fetchall()
node_names = [r[0] for r in nodes if r[2] and int(r[2]) >= 2]
nodes_str = "\n".join(f"- {r[0]}({r[2]}级, 父:{r[3]}): {r[1] or ''}" for r in nodes if r[2] and int(r[2]) >= 2)
log(f"可用节点 {len(node_names)} 个")

# 3. LLM 批量匹配节点
client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
matched = []
# 分批(每批30家)
for i in range(0, len(comps), 30):
    batch = comps[i:i+30]
    comp_lines = []
    for c in batch:
        d = info.get(c, {})
        comp_lines.append(f"{c} | 行业:{d.get('industry','')} | 产品:{d.get('product','')}")
    prompt = (f'你是产业链专家。请把下面每家企业匹配到「人工智能」产业链最合适的节点。\n'
              f'可用节点(只能从这里选)：\n{nodes_str}\n\n'
              f'企业列表：\n' + "\n".join(comp_lines) + '\n\n'
              f'输出JSON: {{"matches":[{{"company":"企业名","node":"节点名"}}]}}, 每家企业一个最合适节点, 不要添加节点列表之外的新节点。')
    resp = client.chat.completions.create(model=LLM_MODEL,
        messages=[{'role':'user','content':prompt}], temperature=0.1, response_format={"type":"json_object"})
    raw = resp.choices[0].message.content or ""
    obj = json.loads(raw.replace('```json','').replace('```','').strip())
    for m in obj.get('matches', []):
        c = str(m.get('company','')).strip()
        n = str(m.get('node','')).strip()
        if c and n in node_names:
            matched.append((c, n))
    log(f"  匹配批次 {i//30+1}: 累计 {len(matched)} 条")

log(f"匹配到节点 {len(matched)} 条")

# 4. 追加到 finallist + list_output (去重)
cur.execute("SELECT company_name FROM company_nodes_finallist WHERE industry_name=%s", (IND,))
existing = set(r[0] for r in cur.fetchall())
added = 0
for c, n in matched:
    if c in existing:
        continue
    # 找该节点的 parent_node 和 level
    cur.execute("SELECT node_level, parent_node FROM chain_needcomp WHERE chain_name=%s AND nodes=%s", (IND, n))
    r = cur.fetchone()
    if not r:
        continue
    lvl, parent = r
    parent = parent or ''
    lvl = int(lvl or 0)
    # 计算 list_output 的 层级1/2/3
    if lvl == 2:
        l1, l2, l3 = '人工智能', parent, n
    else:
        # 三级节点: 层级1=产业链X(父的父), 层级2=父(二级), 层级3=节点
        grand = parent
        cur.execute("SELECT parent_node FROM chain_needcomp WHERE chain_name=%s AND nodes=%s", (IND, parent))
        g = cur.fetchone()
        if g and g[0]:
            grand = g[0]
        l1, l2, l3 = grand, parent, n
    try:
        cur.execute("INSERT IGNORE INTO company_nodes_finallist (company_name, industry_name, nodes, node_level, parent_node, score) VALUES (%s,%s,%s,%s,%s,%s)",
                    (c, IND, n, lvl, parent, '9999'))
        cur.execute("INSERT IGNORE INTO company_list_output (层级1, 层级2, 层级3, 供应商, industry_name) VALUES (%s,%s,%s,%s,%s)",
                    (l1, l2, l3, c, IND))
        added += 1
    except Exception as e:
        log(f"  插入失败 {c}: {e}")
conn.commit()
log(f"新增 {added} 家(榜单企业)")

cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (IND,))
log(f"人工智能 finallist 总量: {cur.fetchone()[0]}")

cur.close(); conn.close()
log("===== 人工智能榜单追加完成 =====")