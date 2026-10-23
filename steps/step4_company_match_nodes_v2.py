"""
步骤4：公司匹配节点（SQL优化版 + 并行 + LLM反向排除）

优化点：
- 不再读全表到内存
- 对每个节点的 full_name 做 SQL LIKE 查询，直接在数据库里匹配
- 一级领域跨行业防护改用 industry_class_first 等值过滤（走 idx_ic_first 索引，大幅提速）
- 节点查询并行化（线程池）
- 匹配完成后用 LLM 生成"该产业链一定不会出现的名字特征词"，反向过滤掉误入企业（只作用于 step4 结果，不动白名单）
"""
import os
import pandas as pd
from sqlalchemy import create_engine, text
import ast
import re
import json
import pymysql
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from .cancel_token import is_cancelled, reset_token, remove_token

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("DASHSCOPE_API_KEY", os.getenv("DASHSCOPE_API_KEY"))
OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL = "deepseek-v4.1-flash"


def _cleanup_deleted_nodes_from_mapping(industry_name: str, removed_nodes: list, tables: dict) -> int:
    """清理已删除节点的公司匹配数据"""
    if not removed_nodes:
        return 0
    conn = pymysql.connect(
        host='8.141.5.67', user='root', password=os.getenv('DB_PASSWORD'), database='business_data'
    )
    cursor = conn.cursor()
    deleted_count = 0
    for node in removed_nodes:
        try:
            cursor.execute(
                "DELETE FROM company_nodes_mapping WHERE industry_name = %s AND nodes = %s",
                (industry_name, node)
            )
            deleted_count += cursor.rowcount
        except Exception as e:
            logger.warning(f"清理 company_nodes_mapping 中节点 {node} 失败: {e}")
    conn.commit()
    cursor.close()
    conn.close()
    logger.info(f"清理已删除节点 {removed_nodes} 的公司匹配数据，共 {deleted_count} 条")
    return deleted_count


def _generate_exclusion_keywords(industry_name: str, node_names: list) -> list:
    """让 LLM 分析: 企业名称中含什么特征就几乎一定不属于该产业链, 返回排除关键词列表"""
    try:
        client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        node_list = "、".join([str(n) for n in node_names[:80] if str(n) not in ('', 'nan')])
        user_msg = (
            f"产业链名称：{industry_name}\n"
            f"产业链节点（环节）：{node_list}\n\n"
            f"请判断：企业名称中包含哪些词（或特征），就几乎一定不属于「{industry_name}」这个产业链，应该被剔除。\n"
            f"要求：\n"
            f"1. 只给明确不属于该产业链的行业/产品特征词。例如产业链是「生命健康」，则“五金、模具、纺织、服装、汽车、光伏、储能、半导体、家具、食品、物流、房地产、传媒、游戏”这类无关行业的词就是排除特征。\n"
            f"2. 不要给“科技、实业、集团、贸易、销售、制造、信息、工程、服务”这类几乎所有行业都有的泛词。\n"
            f"3. 宁缺毋滥，只给高置信度、且会出现在企业名称里的词。\n"
            f"4. 排除词应为 2~8 个汉字的中文词。\n"
            f"请严格按 JSON 输出：{{\"exclude_keywords\": [\"词1\", \"词2\", ...]}}"
        )
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是产业链企业名单审核助手，负责给出“一定不属于某产业链”的企业名称排除特征词。"},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        raw = resp.choices[0].message.content
        data = json.loads(raw)
        kws = data.get("exclude_keywords", []) if isinstance(data, dict) else []
        kws = [str(k).strip() for k in kws if str(k).strip()]
        # 安全约束: 去掉单字/超长/含空白词, 去重
        kws = [k for k in dict.fromkeys(kws) if 2 <= len(k) <= 12 and ' ' not in k and '，' not in k and ',' not in k]
        return kws
    except Exception as e:
        print(f"LLM 反向排除词生成失败: {e}，跳过反向过滤")
        return []


def step4_company_match_nodes(industry_name, tables, whitelist_data=None, progress_callback=None, change_context=None):
    """
    将公司匹配到产业链节点（SQL优化版 + 并行 + LLM反向排除）
    """
    host = '8.141.5.67'
    user = 'root'
    password = os.getenv('DB_PASSWORD')
    database = 'business_data'
    port = 3306

    target_table = tables['company_nodes_mapping']
    source_table = tables['ent_industry_class_old']
    nodes_mapping_table = tables.get('nodes_industry_mapping', 'nodes_industry_mapping')

    engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}")

    print(f"\n{'='*40}")
    print(f"步骤4：公司匹配节点（SQL优化版 + 并行 + LLM反向排除）")
    print(f"产业链名称: {industry_name}")
    print(f"目标表: {target_table}")

    reset_token(industry_name)

    if change_context:
        removed_nodes = change_context.get('removed_nodes', [])
        if removed_nodes:
            print(f"检测到已删除节点: {removed_nodes}，开始清理关联数据")
            _cleanup_deleted_nodes_from_mapping(industry_name, removed_nodes, tables)

    # 创建目标表
    def create_table_if_not_exists():
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {target_table} (
            company_name VARCHAR(255),
            credit_code VARCHAR(100),
            certainty VARCHAR(20),
            industry_name VARCHAR(255),
            nodes TEXT,
            name VARCHAR(255),
            level VARCHAR(50),
            full_name VARCHAR(255),
            reason TEXT
        )
        """
        try:
            with engine.connect() as conn:
                conn.execute(text(create_table_sql))
            print(f"表 {target_table} 检查完成")
        except Exception as e:
            print(f"创建表失败：{e}")

    create_table_if_not_exists()

    # 1. 查询节点行业映射数据
    industry_name_escaped = industry_name.replace("'", "''")
    query_b = f"""
    SELECT industry_name, nodes, name, level, full_name, reason
    FROM {nodes_mapping_table}
    WHERE industry_name = '{industry_name_escaped}'
    """
    df_b = pd.read_sql(query_b, engine)
    df_b['full_name'] = df_b['full_name'].astype(str)

    if df_b.empty:
        print(f"警告：未找到产业链 '{industry_name}' 的节点映射数据")
        return {"step": 4, "name": "公司匹配节点", "status": "skipped", "reason": "无节点映射数据"}

    # 过滤掉0级、1级节点
    excluded_patterns = [industry_name, '上游', '中游', '下游', '产业链上游', '产业链中游', '产业链下游']
    original_count = len(df_b)
    df_b = df_b[~df_b['nodes'].isin(excluded_patterns) &
                ~df_b['nodes'].str.contains('上游|中游|下游', na=False) &
                ~df_b['full_name'].str.contains('上游|中游|下游', na=False)]
    filtered_count = len(df_b)
    print(f"加载节点映射数据: {original_count} 条 -> 过滤后: {filtered_count} 条")

    # 提取一级领域集合
    chain_level1_domains = set()
    for _, row_b in df_b.iterrows():
        domain = str(row_b['full_name']).split('|')[0].strip()
        if domain:
            chain_level1_domains.add(domain)
    chain_level1_domains.discard('其他')
    print(f"产业链 '{industry_name}' 相关一级领域: {sorted(chain_level1_domains)}")

    if df_b.empty:
        print("过滤后无节点，跳过")
        return {"step": 4, "name": "公司匹配节点", "status": "skipped", "reason": "无有效节点"}

    # 2. 删除旧数据
    with engine.connect() as conn:
        delete_sql = text(f"DELETE FROM {target_table} WHERE industry_name = :industry_name")
        conn.execute(delete_sql, {"industry_name": industry_name})
        conn.commit()

    # 3. 构建一级领域防护 SQL 条件（等值过滤，走 idx_ic_first 索引）
    if chain_level1_domains:
        domain_list = sorted(chain_level1_domains)
        quoted = ",".join("'" + d.replace("'", "''") + "'" for d in domain_list)
        domain_filter = f"AND a.industry_class_first IN ({quoted})"
    else:
        domain_filter = ""

    nodes_rows = list(df_b.iterrows())

    def _match_one_node(row_b):
        """单个节点的匹配，返回 matched 列表（供线程池并发）"""
        full_name = str(row_b['full_name'])
        if not full_name or full_name == 'nan':
            return []
        full_name_escaped = full_name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("'", "''")
        sql = f"""
        SELECT COALESCE(a.company_name_full, a.company_name) AS company_name,
               a.credit_code, a.certainty, a.industry_class_third
        FROM {source_table} a
        WHERE a.industry_class_third LIKE '%{full_name_escaped}%'
          AND (a.industry_class_third LIKE '%强%' OR a.industry_class_third LIKE '%中%')
          {domain_filter}
        """
        results = []
        c = pymysql.connect(host=host, user=user, password=password, database=database, port=port)
        try:
            cur = c.cursor()
            try:
                cur.execute(sql)
                rows = cur.fetchall()
            except Exception as e:
                print(f"查询节点 {full_name} 失败: {e}")
                return []
            finally:
                cur.close()
        finally:
            c.close()

        for row in rows:
            company_name, credit_code, certainty, industry_class_third = row
            try:
                industry_dict = ast.literal_eval(industry_class_third) if industry_class_third else {}
            except (ValueError, SyntaxError):
                continue
            if not industry_dict:
                continue

            # 精确验证: full_name 是某个 key 的子串, 且 value 是 '强'/'中'
            matched = False
            for key, strength in industry_dict.items():
                if full_name in key and strength in ['强', '中']:
                    matched = True
                    break
            if not matched:
                continue

            # 一级领域防护(精确验证)
            if chain_level1_domains:
                company_has_relevant_domain = False
                for cls_key in industry_dict.keys():
                    company_domain = str(cls_key).split('|')[0].strip()
                    if company_domain in chain_level1_domains:
                        company_has_relevant_domain = True
                        break
                if not company_has_relevant_domain:
                    continue

            results.append({
                'company_name': company_name,
                'credit_code': credit_code,
                'certainty': (certainty if certainty else '1'),
                'industry_name': row_b['industry_name'],
                'nodes': row_b['nodes'],
                'name': row_b['name'],
                'level': row_b['level'],
                'full_name': row_b['full_name'],
                'reason': row_b['reason']
            })
        return results

    # 4. 并行匹配所有节点
    total_nodes = len(nodes_rows)
    all_matched = []
    nodes_processed = 0
    max_workers = 8
    print(f"开始并行匹配节点，线程数={max_workers}，节点数={total_nodes}")

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_match_one_node, row_b) for _, row_b in nodes_rows]
        for fut in as_completed(futures):
            if is_cancelled(industry_name):
                print("步骤4已被取消")
                remove_token(industry_name)
                return {"step": 4, "name": "公司匹配节点", "status": "cancelled", "message": "用户取消操作"}
            all_matched.extend(fut.result())
            nodes_processed += 1
            if nodes_processed % 10 == 0:
                print(f"  节点进度: {nodes_processed}/{total_nodes}, 累计匹配: {len(all_matched)}")
                if progress_callback:
                    progress_callback('batch_progress', {
                        'batch': nodes_processed,
                        'total_batches': total_nodes,
                        'count': len(all_matched),
                        'message': f'节点 {nodes_processed}/{total_nodes} 完成，累计 {len(all_matched)} 条'
                    })

    # 5. 去重: 同一企业+同一行业只保留一条
    seen_pairs = set()
    deduped = []
    for m in all_matched:
        dedup_key = (m['company_name'], m['name'])
        if dedup_key not in seen_pairs:
            seen_pairs.add(dedup_key)
            deduped.append(m)
    all_matched = deduped
    print(f"\n匹配完成，去重后共 {len(all_matched)} 条记录")

    # 6. LLM 反向排除: 生成"该链一定不会出现的名字特征"，过滤误入企业
    if all_matched:
        node_names = list(dict.fromkeys([str(r['name']) for r in all_matched]))
        exclude_kws = _generate_exclusion_keywords(industry_name, node_names)
        if exclude_kws:
            print(f"LLM 生成的排除特征词({len(exclude_kws)}): {exclude_kws}")
            before = len(all_matched)
            filtered = [m for m in all_matched
                        if not any(kw in (m['company_name'] or '') for kw in exclude_kws)]
            removed = before - len(filtered)
            print(f"反向过滤: 移除 {removed} 家，剩余 {len(filtered)} 家")
            all_matched = filtered
        else:
            print("LLM 未生成有效排除词，跳过反向过滤")

    # 7. 插入结果到目标表
    if all_matched:
        result_df = pd.DataFrame(all_matched)
        batch_size = 5000
        for i in range(0, len(result_df), batch_size):
            batch = result_df.iloc[i:i+batch_size]
            try:
                batch.to_sql(target_table, engine, index=False, if_exists='append')
                print(f"  插入批次 {i//batch_size + 1}/{(len(result_df)+batch_size-1)//batch_size}: {len(batch)} 条")
            except Exception as e:
                print(f"  插入失败: {e}")

    remove_token(industry_name)
    print(f"步骤4完成，数据已插入到 {target_table}")
    return {"step": 4, "name": "公司匹配节点", "status": "completed"}


if __name__ == "__main__":
    from auto_industry_chain_pipeline import TABLES
    step4_company_match_nodes("氢能产业", TABLES)