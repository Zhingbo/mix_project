# -*- coding: utf-8 -*-
import os
# 针对性补匹配: 把 whitelist_company 里"空挂载"的企业用 LLM 匹配到节点并回填
import pymysql, json, time, hashlib
from openai import OpenAI

KEY = os.getenv("DASHSCOPE_API_KEY")
BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "deepseek-v4.1-flash"
BATCH = 5
MAX_RETRIES = 3
client = OpenAI(api_key=KEY, base_url=BASE)

def get_db():
    return pymysql.connect(host='8.141.5.67', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
                           database='business_data', charset='utf8mb4')

def node_hash(ind):
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT nodes FROM industrial_chain.industrial_chain_structure WHERE chain_name=%s",(ind,))
    ns=set()
    for (nodes_str,) in cur.fetchall():
        for n in str(nodes_str).split(','):
            n=n.strip()
            if n: ns.add(n)
    cur.close(); conn.close()
    return hashlib.md5("|".join(sorted(ns)).encode()).hexdigest()[:16]

def get_nodes_definitions(ind):
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT nodes, nodes_definition, node_level FROM chain_needcomp WHERE chain_name=%s",(ind,))
    nodes=[]; defs={}
    excluded={ind,'上游','中游','下游',f'{ind}上游',f'{ind}中游',f'{ind}下游'}
    for (nodes_str, definition, nl) in cur.fetchall():
        for node in str(nodes_str).split(','):
            node=node.strip()
            if node and node not in excluded and (nl is None or nl>=2):
                nodes.append(node)
                defs[node]=str(definition or '').strip()
    cur.close(); conn.close()
    return list(set(nodes)), defs

def lookup_info(names):
    info={}
    if not names: return info
    conn=get_db(); cur=conn.cursor()
    for i in range(0,len(names),200):
        chunk=names[i:i+200]
        ph=",".join(["%s"]*len(chunk))
        cur.execute(f"SELECT company_name, product, business, industry FROM ent_establish_industry_merged_20260928 WHERE company_name IN ({ph})", chunk)
        for cn,prod,biz,ind in cur.fetchall():
            info[cn]={"product":prod or "", "business":biz or "", "industry":ind or ""}
    cur.close(); conn.close()
    return info

def build_prompt(nodes, defs, ind):
    nodes_str=", ".join(nodes)
    defs_str="; ".join([f"{n}: {defs.get(n,'')}" for n in nodes])
    return f'''你是一个产业链分析专家，也是一个构建产业链知识图谱的专家。

你的任务是根据每家公司的简介和主营产品，在已有的产业链节点({nodes_str})中找到最匹配的节点。

节点定义：
{defs_str}

匹配规则：
- 根据公司主营产品和简介，结合节点定义，找到最相关的产业链节点
- 匹配关系可能是：包含关系、组成关系、关联关系
- 不要匹配"上游"、"中游"、"下游"以及产业链名称本身
- 每家企业最多匹配20个节点
- 为每个匹配的节点给出匹配原因和分数

我会一次给你多家企业的信息，请以JSON格式为每家企业分别返回匹配结果：
{{
    "results": [
        {{
            "企业名称": "公司全称",
            "主营产品": "主要产品或服务",
            "公司简介": "公司简介",
            "匹配节点": "节点1;节点2;节点3",
            "匹配原因": "原因1;原因2;原因3",
            "置信度": "2",
            "分数": "75;80;85",
            "产业链名称": "{ind}"
        }}
    ]
}}

注意：
1. 匹配节点必须在提供的节点列表中
2. 分数范围：置信度1为75-100，置信度2为51-74，置信度3为26-50，置信度4为0-25
3. 匹配节点不能为空
4. 必须为每家企业都返回结果，不要遗漏
5. 每个字段用双引号括起来
'''

def match_batch(batch_names, info, nodes, defs, ind):
    companies_input=[]
    for cn in batch_names:
        real=info.get(cn)
        if real and real.get("business"):
            companies_input.append({"company_name":cn,"company_intro":real["business"][:500],"major_product":real["product"][:500],"industry_category":real["industry"][:200]})
        else:
            companies_input.append({"company_name":cn,"company_intro":f"{cn}是{ind}环节的企业。","major_product":f"从事{ind}相关业务"})
    prompt=build_prompt(nodes, defs, ind)
    for attempt in range(MAX_RETRIES):
        try:
            resp=client.chat.completions.create(model=MODEL,
                messages=[{'role':'system','content':prompt},{'role':'user','content':json.dumps({"companies":companies_input},ensure_ascii=False)}],
                temperature=0.6, response_format={"type":"json_object"})
            raw=resp.choices[0].message.content
            parsed=json.loads(raw.replace("```json","").replace("```","").strip())
            results=parsed.get('results',[]) if isinstance(parsed,dict) else (parsed if isinstance(parsed,list) else [])
            out={}
            for item in results:
                ai=str(item.get('企业名称','')).strip()
                for cn in batch_names:
                    if cn==ai or cn in ai or ai in cn:
                        out[cn]=item
                        break
            return out
        except Exception as e:
            if attempt<MAX_RETRIES-1:
                time.sleep(2)
            else:
                print(f"  批次匹配失败: {e}", flush=True)
                return {}

def main():
    conn=get_db(); cur=conn.cursor()
    # 按链取空挂载企业
    cur.execute("SELECT industry_name, company_name, id, position, company_name FROM whitelist_company WHERE matched_nodes IS NULL OR matched_nodes='' ORDER BY industry_name")
    rows=cur.fetchall()
    by_chain={}
    for ind, cn, wl_id, pos, cn2 in rows:
        by_chain.setdefault(ind, []).append((wl_id, cn))
    cur.close(); conn.close()
    print(f"共需补匹配 {sum(len(v) for v in by_chain.values())} 家, 分布在 {len(by_chain)} 个链", flush=True)

    total_done=0
    for ind, items in by_chain.items():
        nodes, defs = get_nodes_definitions(ind)
        if not nodes:
            print(f"[{ind}] 无节点, 跳过 {len(items)} 家", flush=True)
            continue
        h=node_hash(ind)
        names=[cn for _,cn in items]
        info=lookup_info(list(set(names)))
        print(f"[{ind}] {len(items)} 家待匹配, {len(nodes)} 个节点", flush=True)
        conn=get_db(); cur=conn.cursor()
        for i in range(0,len(items),BATCH):
            batch=items[i:i+BATCH]
            batch_names=[cn for _,cn in batch]
            res=match_batch(batch_names, info, nodes, defs, ind)
            for wl_id, cn in batch:
                it=res.get(cn)
                if not it: continue
                mn=str(it.get('匹配节点','')).strip()
                mr=str(it.get('匹配原因','')).strip()
                sc=str(it.get('分数','')).strip()
                ce=str(it.get('置信度','')).strip()
                if mn:
                    cur.execute("UPDATE whitelist_company SET matched_nodes=%s, match_reason=%s, match_score=%s, certainty=%s, matched_at=NOW(), node_snapshot=%s WHERE id=%s",(mn,mr,sc,ce,h,wl_id))
                    total_done+=1
            conn.commit()
            if (i//BATCH+1)%10==0:
                print(f"  [{ind}] 已处理 {min(i+BATCH,len(items))}/{len(items)}", flush=True)
        cur.close(); conn.close()
        print(f"[{ind}] 完成, 累计回填 {total_done} 家", flush=True)

    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT COUNT(*) FROM whitelist_company WHERE matched_nodes IS NULL OR matched_nodes=''")
    remain=cur.fetchone()[0]
    cur.close(); conn.close()
    print(f"全部结束, 补填 {total_done} 家, 仍空 {remain} 家", flush=True)

if __name__=='__main__':
    main()