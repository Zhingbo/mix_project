"""
步骤6：搜索头部企业并匹配节点

优化版（去除 Jina 依赖）：
1. 直接使用 DeepSeek 搜索头部企业（替代 Jina 搜索+AI提取）
2. 三个环节（上/中/下游）并行搜索
3. 企业匹配节点批量发送（每批5家）
4. 企业信息批量查询（IN 查询替代逐家建连接）
5. 失败自动重试
"""

import requests
import sys
import json
from typing import List, Dict
import time
import logging
from datetime import datetime
from openai import OpenAI
import pymysql
from pymysql.cursors import DictCursor
import os
import pandas as pd
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from .cancel_token import is_cancelled, reset_token, remove_token
from .step4_company_match_nodes import _generate_exclusion_keywords

OPENAI_API_KEY = os.getenv("DASHSCOPE_API_KEY", os.getenv("DASHSCOPE_API_KEY"))
OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL = "deepseek-v4.1-flash"
MATCH_BATCH_SIZE = 5
MAX_RETRIES = 3


def _baidu_search_head_companies(industry_name: str, max_per_query: int = 2) -> List[str]:
    """本地百度搜索榜单头部企业 + deepseek 抽取企业名, 返回企业名列表"""
    try:
        sys.path.insert(0, '/root/mix_project/baidu_spider/baidu_spider')
        import baidu_improved as bd
    except Exception as e:
        logging.warning(f"百度搜索模块不可用: {e}")
        return []
    year = datetime.now().year
    # 榜单类搜索口径: 覆盖行业百强/200强/500强/隐形冠军/创新TOP/独角兽/隐形独角兽/科技真榜等
    queries = [
        f"{year}中国{industry_name}企业100强",
        f"{year}中国{industry_name}企业200强名单",
        f"{year}中国{industry_name}企业500强",
        f"{year}{industry_name}龙头企业排行榜",
        f"{year}{industry_name}百强企业",
        f"{year}{industry_name}隐形冠军企业名单",
        f"{year}{industry_name}创新企业TOP100",
        f"{year}{industry_name}独角兽企业名单",
        f"{year}{industry_name}隐形独角兽企业名单",
        f"{year}{industry_name}科技真榜",
        f"{year}{industry_name}专精特新小巨人企业名单",
        f"{year}{industry_name}瞪羚企业名单",
    ]
    lines = []
    for q in queries:
        try:
            for r in bd.search_multiple_pages(q, max_pages=max_per_query):
                t = str(r.get('title', '')).strip()
                d = str(r.get('description', '')).strip()
                if t and len(t) >= 4:
                    lines.append(f"{t}。{d[:80]}")
        except Exception as e:
            logging.warning(f"百度搜索失败 {q}: {e}")
    if not lines:
        return []
    corpus = "\n".join(lines)
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    prompt = (f'从下方搜索结果提取「{industry_name}」产业链企业名称，输出JSON，格式：'
              f'{{"companies":["企业名1","企业名2",...]}}。最多120家，按重要性降序，'
              f'企业名去掉股票代码和括号说明。\n搜索结果：\n{corpus[:15000]}')
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or ""
        obj = json.loads(raw.replace("```json", "").replace("```", "").strip())
        comps = obj.get("companies", [])
        return [str(c).strip() for c in comps if str(c).strip()]
    except Exception as e:
        logging.warning(f"deepseek 抽取头部企业失败: {e}")
        return []


def _cleanup_deleted_nodes_data(industry_name: str, removed_nodes: list, tables: dict) -> int:
    """清理已删除节点的关联数据"""
    if not removed_nodes:
        return 0

    conn = pymysql.connect(
        host='8.141.5.67', port=3306, user='root',
        password=os.getenv('DB_PASSWORD'), database='business_data'
    )
    cursor = conn.cursor()

    tables_to_cleanup = [
        'company_nodes_info_result',
        'company_nodes_info_split',
        'company_nodes_final',
        'company_nodes_finallist',
    ]

    deleted_count = 0
    for node in removed_nodes:
        for table in tables_to_cleanup:
            try:
                cursor.execute(
                    f"DELETE FROM {table} WHERE industry_name = %s AND (matched_nodes = %s OR nodes = %s OR matched_node = %s)",
                    (industry_name, node, node, node)
                )
                deleted_count += cursor.rowcount
            except Exception as e:
                logging.warning(f"清理表 {table} 中节点 {node} 失败: {e}")

    conn.commit()
    cursor.close()
    conn.close()
    logging.info(f"清理已删除节点 {removed_nodes} 的关联数据，共 {deleted_count} 条")
    return deleted_count


def _extract_core_name(company_name: str) -> str:
    """提取公司核心名称，用于相似度比较"""
    suffixes = ['股份有限公司', '有限责任公司', '有限公司', '集团有限公司', '集团股份有限公司',
                '集团', '公司', '（中国）', '(China)', '（上海）', '(Shanghai)', '（北京）', '(Beijing)',
                '（深圳）', '(Shenzhen)', '（广州）', '(Guangzhou)', '科技', '技术', '股份', '有限']
    core_name = company_name
    for suffix in suffixes:
        core_name = core_name.replace(suffix, '')
    core_name = re.sub(r'[（(][^）)]*[）)]', '', core_name)
    return core_name.strip()


def _is_similar_company(name1: str, name2: str) -> bool:
    """判断两个公司名称是否指向同一家公司"""
    core1 = _extract_core_name(name1)
    core2 = _extract_core_name(name2)
    if core1 == core2:
        return True
    if core1 in core2 or core2 in core1:
        min_len = min(len(core1), len(core2))
        if min_len >= 2:
            return True
    return False


def _deduplicate_companies(companies: list, seen_companies: set, whitelist_set: set = None) -> list:
    """对公司列表进行智能去重，白名单企业最高优先级"""
    if whitelist_set is None:
        whitelist_set = set()

    unique_companies = []
    to_remove_from_seen = []
    to_add_to_seen = []

    for company in companies:
        is_duplicate = False

        for seen in list(seen_companies):
            if _is_similar_company(company, seen):
                is_duplicate = True
                if seen in whitelist_set:
                    pass
                elif len(company) > len(seen):
                    to_remove_from_seen.append(seen)
                    to_add_to_seen.append(company)
                    unique_companies.append(company)
                break

        if not is_duplicate:
            for i, existing in enumerate(unique_companies):
                if _is_similar_company(company, existing):
                    is_duplicate = True
                    if len(company) > len(existing):
                        unique_companies[i] = company
                    break

        if not is_duplicate:
            unique_companies.append(company)

    for name in to_remove_from_seen:
        seen_companies.discard(name)
    for name in to_add_to_seen:
        seen_companies.add(name)

    return unique_companies


# ==================== DeepSeek 直接搜索（替代 Jina） ====================

def _deepseek_search_companies(industry_name: str, position: str, search_angle: str) -> List[str]:
    """使用 DeepSeek 直接搜索产业链头部企业（凭模型自身知识，不依赖外部搜索引擎）"""
    try:
        client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

        system_prompt = f"""你是一个专业的产业链分析专家。请根据你的专业知识，准确识别产业链"{industry_name}"{position}环节的头部企业。

请严格按照以下JSON格式返回：
{{
    "top_companies": [
        "企业全称1",
        "企业全称2",
        "企业全称3"
    ]
}}

【最重要的规则 - 必须返回完整公司全称】：
- 必须返回公司的完整工商注册名称，包含"有限公司"、"股份有限公司"、"集团"等后缀
- 绝对禁止返回简称
- 如果不确定公司全称，宁可不返回也不要返回简称
- 只返回JSON格式，不要包含其他文字说明
- 确保返回的企业是真实存在的
- 优先返回上市公司、知名企业、行业龙头企业
- 对于不确定是否真实存在的公司，宁可不要返回
- 【严格限定行业】只返回真正属于"{industry_name}"产业链的企业，绝不返回保险、金融、证券、银行、房地产、汽车、光伏、太阳能、半导体、游戏、传媒、物流、电商、食品、纺织等明显不相干行业的企业
- 返回30-50家企业（尽可能多地返回）
- 返回的企业名称必须都是不一样的，不要有重复
- 优先返回中国企业，其次是知名外企"""

        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': search_angle}
            ],
            temperature=0.7,
            response_format={"type": "json_object"}
        )

        content = response.choices[0].message.content
        result = json.loads(content.replace("```json", "").replace("```", "").strip())
        companies = result.get("top_companies", [])
        return [str(c).strip() for c in companies if str(c).strip()]
    except Exception as e:
        logging.error(f"DeepSeek搜索{position}企业失败: {e}")
        return []


def _search_one_position(position: str, industry_name: str, search_angles: List[str]) -> List[str]:
    """在一个环节内使用多个搜索角度发现企业（供 ThreadPoolExecutor 并行调度）"""
    all_companies = []
    for angle in search_angles:
        for attempt in range(MAX_RETRIES):
            try:
                companies = _deepseek_search_companies(industry_name, position, angle)
                all_companies.extend(companies)
                logging.info(f"[{position}] 发现 {len(companies)} 家企业 (角度: {angle[:30]}...)")
                break
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    logging.warning(f"[{position}] 搜索失败，重试: {e}")
                    time.sleep(1)
                else:
                    logging.error(f"[{position}] 搜索最终失败: {e}")
    return all_companies


def _deepseek_search_list_companies(industry_name: str) -> List[str]:
    """DeepSeek 凭模型知识直搜榜单类企业(兜底, 不依赖百度反爬)"""
    angles = [
        f"列出中国{industry_name}行业(细分赛道)的100强、200强、500强企业",
        f"列出中国{industry_name}领域的隐形冠军、专精特新小巨人、瞪羚企业名单",
        f"列出中国{industry_name}领域的独角兽、隐形独角兽、高成长/高创新企业名单",
        f"列出{industry_name}行业科技真榜上榜企业、龙头企业",
    ]
    comps = []
    for a in angles:
        try:
            comps.extend(_deepseek_search_companies(industry_name, '全产业链', a))
        except Exception as e:
            logging.warning(f"DeepSeek榜单兜底搜索失败: {e}")
    seen = set()
    out = []
    for c in comps:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _llm_enrich_company_info(company_names: List[str], industry_name: str = None) -> Dict[str, dict]:
    """用 DeepSeek 批量生成企业细分行业 + 主营产品(底表查不到时的兜底)"""
    if not company_names:
        return {}
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    names = "\n".join(company_names)
    prompt = (f'你是企业信息专家。请根据每家企业名称，判断其所属细分行业和主营产品。\n'
              f'输出JSON：{{"companies":[{{"name":"企业全称","industry":"细分行业","product":"主营产品一句话"}}]}}\n'
              f'行业尽量具体(如基因检测/创新药/生物试剂/CDMO/医学影像/半导体设备)，不要只写大类。\n'
              f'企业列表：\n{names}')
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or ""
        obj = json.loads(raw.replace("```json", "").replace("```", "").strip())
        out = {}
        for c in obj.get("companies", []):
            nm = str(c.get("name", "")).strip()
            if nm:
                prod = str(c.get("product", "")).strip()
                ind = str(c.get("industry", "")).strip()
                out[nm] = {
                    "product": prod,
                    "business": prod,
                    "industry": ind,
                    "industry_class": "",
                }
        return out
    except Exception as e:
        logging.warning(f"DeepSeek 企业画像生成失败: {e}")
        return {}


def _batch_lookup_company_info(company_names: List[str], industry_name: str = None) -> Dict[str, dict]:
    """批量查询企业真实业务信息；底表查不到的用 DeepSeek 补行业/产品"""
    if not company_names:
        return {}

    info_map = {}
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        chunk_size = 200
        for i in range(0, len(company_names), chunk_size):
            chunk = company_names[i:i + chunk_size]
            placeholders = ",".join(["%s"] * len(chunk))
            cursor.execute(f"""
                SELECT company_name, product, business, industry, industry_class_third
                FROM ent_industry_class_chain_scope_20260928_converted
                WHERE company_name IN ({placeholders})
            """, chunk)
            for row in cursor.fetchall():
                info_map[row[0]] = {
                    "product": row[1] or "",
                    "business": row[2] or "",
                    "industry": row[3] or "",
                    "industry_class": row[4] or ""
                }
    except Exception as e:
        logging.warning(f"批量查询企业信息失败: {e}")
    finally:
        cursor.close()
        conn.close()

    logging.info(f"批量查询企业信息: 请求 {len(company_names)} 家，命中 {len(info_map)} 家")

    # 兜底: 底表没命中的企业, 用 DeepSeek 补行业/产品(便于更精准挂载)
    missing = [n for n in company_names if n and n not in info_map]
    if missing:
        logging.info(f"底表未命中 {len(missing)} 家, 改用 DeepSeek 补行业/产品")
        for i in range(0, len(missing), 50):
            batch = missing[i:i + 50]
            try:
                info_map.update(_llm_enrich_company_info(batch, industry_name))
            except Exception as e:
                logging.warning(f"DeepSeek 补行业/产品失败: {e}")
    return info_map


# ==================== 数据库工具 ====================

def get_db_connection():
    """获取新的数据库连接"""
    return pymysql.connect(
        host='8.141.5.67', port=3306, user='root',
        password=os.getenv('DB_PASSWORD'), database='business_data',
        connect_timeout=30, read_timeout=30
    )


def _count_table_rows(table_name: str, column_name: str, industry_name: str) -> int:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT COUNT(*) FROM {table_name} WHERE {column_name} = %s",
            (industry_name,)
        )
        return cursor.fetchone()[0]
    except Exception as exc:
        logging.warning(f"检查表 {table_name} 数据失败: {exc}")
        return 0
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# ==================== 主函数 ====================

def step6_top_company_match(industry_name, tables, whitelist_data=None, progress_callback=None, change_context=None):
    """
    步骤6：搜索头部企业并匹配节点（优化版）

    优化点：
    - 使用 DeepSeek 直接搜索，不依赖 Jina
    - 三个环节（上/中/下游）并行搜索
    - 企业匹配节点批量发送（每批5家）
    - 企业信息批量DB查询
    - 失败自动重试
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(f'logs/step6_{datetime.now().strftime("%Y%m%d")}.log'),
            logging.StreamHandler()
        ]
    )

    topcompany_table = tables.get('company_nodes_top', 'company_nodes_top')
    chain_table = tables['chain_needcomp']
    result_table = tables.get('company_nodes_info_result', 'company_nodes_info_result')

    print(f"\n{'='*40}")
    print(f"步骤6：搜索头部企业并匹配节点（DeepSeek直搜 + 并行 + 批量匹配）")
    print(f"产业链名称: {industry_name}")
    print(f"{'='*40}")

    reset_token(industry_name)

    # ==================== 增量更新：清理已删除的节点 ====================
    removed_nodes = []
    nodes_to_process = None

    if change_context:
        removed_nodes = change_context.get('removed_nodes', [])
        added_nodes = change_context.get('added_nodes', [])
        modified_nodes = change_context.get('modified_nodes', [])
        added_companies = change_context.get('added_companies', [])
        removed_companies = change_context.get('removed_companies', [])

        if removed_nodes:
            logging.info(f"检测到已删除节点: {removed_nodes}，开始清理关联数据")
            _cleanup_deleted_nodes_data(industry_name, removed_nodes, tables)

        if added_nodes or modified_nodes:
            nodes_to_process = set(added_nodes + modified_nodes)
            logging.info(f"增量模式：只处理变更的节点 {nodes_to_process}")
        elif not removed_nodes:
            has_whitelist_changes = bool(added_companies or removed_companies)
            existing_result_count = _count_table_rows(result_table, 'industry_name', industry_name)
            pending_company_count = _count_table_rows(topcompany_table, 'industry_chain', industry_name)

            if has_whitelist_changes:
                logging.info("增量模式：检测到白名单变更，继续执行步骤6")
            elif existing_result_count == 0 and pending_company_count > 0:
                logging.info("增量模式：步骤6结果为空且存在待匹配企业，执行全量步骤6")
            else:
                logging.info("增量模式：无节点变更且无白名单变更，跳过步骤6")
                return {"step": 6, "name": "头部企业匹配节点", "status": "skipped", "reason": "无节点或白名单变更"}

    positions = ["上游", "中游", "下游"]
    all_companies = []
    seen_companies = set()
    whitelist_set = set()

    # ==================== 1. 加载白名单企业 ====================
    whitelist_from_xlsx = load_whitelist_from_xlsx(industry_name)
    xlsx_loaded = any(len(companies) > 0 for companies in whitelist_from_xlsx.values())

    if xlsx_loaded:
        for position in positions:
            companies = whitelist_from_xlsx[position]
            if companies:
                for company in companies:
                    whitelist_set.add(company)
                    if company not in seen_companies:
                        seen_companies.add(company)
                        all_companies.append((company, position))
                logging.info(f"从 xlsx 加载{position}白名单: {len(companies)} 家")
    else:
        conn = get_db_connection()
        query = f"SELECT company_name FROM {topcompany_table} WHERE industry_chain = %s"
        df_whitelist = pd.read_sql(query, conn, params=[industry_name])
        conn.close()

        for company_name in df_whitelist['company_name']:
            whitelist_set.add(company_name)
            if company_name not in seen_companies:
                seen_companies.add(company_name)
                all_companies.append((company_name, "中游"))

        if not df_whitelist.empty:
            logging.info(f"从数据库加载白名单: {len(df_whitelist)} 家")

    # ==================== 2. 联网搜索榜单头部企业(本地百度 + deepseek 抽取) ====================
    searched_companies = _baidu_search_head_companies(industry_name)
    if not searched_companies:
        logging.info("百度搜索无结果(可能被反爬), 改用 DeepSeek 榜单兜底直搜")
        searched_companies = _deepseek_search_list_companies(industry_name)
    _added = 0
    for _c in searched_companies:
        if _c and _c not in seen_companies and _c not in whitelist_set:
            seen_companies.add(_c)
            all_companies.append((_c, "中游"))
            _added += 1
    logging.info(f"联网搜索到头部企业 {len(searched_companies)} 家, 去重后新增 {_added} 家待匹配")

    if is_cancelled(industry_name):
        logging.info("步骤6已被取消（搜索阶段后）")
        remove_token(industry_name)
        return {"step": 6, "name": "头部企业匹配节点", "status": "cancelled", "message": "用户取消操作"}

    if not all_companies:
        remove_token(industry_name)
        return {"step": 6, "name": "头部企业匹配节点", "status": "skipped", "reason": "未找到任何企业"}

    logging.info(f"搜索阶段完成，共 {len(all_companies)} 家企业待匹配")

    # ==================== 2.5 白名单缓存复用(已匹配过的直接取, 不再跑 LLM) ====================
    def _norm(x):
        x = (x or '').strip()
        if len(x) >= 2 and x[0] == '"' and x[-1] == '"':
            try:
                return str(json.loads(x))
            except Exception:
                return x
        return x
    _wl_cache = {}
    _cc = get_db_connection()
    _c = _cc.cursor()
    _c.execute(
        "SELECT company_name, matched_nodes, match_reason, match_score, certainty "
        "FROM whitelist_company WHERE industry_name=%s "
        "AND matched_nodes IS NOT NULL AND LENGTH(matched_nodes)>0", (industry_name,))
    for _cn, _mn, _mr, _ms, _ce in _c.fetchall():
        _wl_cache[_cn] = (_norm(_mn), _norm(_mr), _norm(_ms), _norm(_ce))
    _c.close(); _cc.close()

    _cached_companies = []
    _to_match_companies = []
    for _item in all_companies:
        _cn = _item[0]
        # 生命健康硬规则: 药房/药铺必须走LLM重匹配, 旧缓存可能绕过"挂下游"规则
        _force_rematch = (industry_name == '生命健康' and ('药房' in str(_cn) or '药铺' in str(_cn)))
        if _cn in _wl_cache and not _force_rematch:
            _cached_companies.append(_item)
        else:
            _to_match_companies.append(_item)
    all_companies = _to_match_companies
    logging.info(f"白名单缓存命中 {len(_cached_companies)} 家, 需新匹配 {len(all_companies)} 家")

    # ==================== 3. 准备节点数据 ====================
    conn = get_db_connection()
    cursor = conn.cursor()
    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS {result_table} (
        company_name TEXT,
        ai_company_name TEXT,
        major_product LONGTEXT,
        company_intro LONGTEXT,
        matched_nodes TEXT,
        match_reason LONGTEXT,
        certainty TEXT,
        score TEXT,
        industry_name TEXT
    )
    """
    cursor.execute(create_table_sql)
    conn.commit()

    query = f"SELECT nodes, nodes_definition, node_level FROM {chain_table} WHERE chain_name = %s"
    df_nodes = pd.read_sql(query, conn, params=[industry_name])

    nodes = []
    nodes_definitions = {}
    excluded_nodes = {industry_name, '上游', '中游', '下游',
                      f'{industry_name}上游', f'{industry_name}中游', f'{industry_name}下游'}

    for _, row in df_nodes.iterrows():
        node_level = row.get('node_level', 0)
        node_list = str(row.get('nodes', '')).split(',')
        definition = str(row.get('nodes_definition', '')).strip()
        for node in node_list:
            node = node.strip()
            if node and node not in excluded_nodes and (node_level is None or node_level >= 2):
                nodes.append(node)
                nodes_definitions[node] = definition

    nodes = list(set(nodes))
    logging.info(f"产业链节点数: {len(nodes)} (已排除0级、1级节点)")

    if nodes_to_process is not None:
        original_nodes = nodes[:]
        nodes = [n for n in nodes if n in nodes_to_process]
        logging.info(f"增量过滤：从 {len(original_nodes)} 个节点中筛选出 {len(nodes)} 个")
        if not nodes:
            conn.close()
            return {"step": 6, "name": "头部企业匹配节点", "status": "skipped", "reason": "无需要处理的节点"}

    if not nodes:
        logging.warning("未找到产业链节点数据")
        conn.close()
        return {"step": 6, "name": "头部企业匹配节点", "status": "skipped", "reason": "无节点数据"}

    conn.close()

    # ==================== 4. 批量匹配企业到节点 ====================
    nodes_str = ", ".join(nodes)
    nodes_definitions_str = "; ".join([f"{node}: {nodes_definitions[node]}" for node in nodes])

    special_rule = ""
    if industry_name == '生命健康':
        special_rule = '\n- 特别规则：企业名称含"药房"或"药铺"的，必须匹配到下游节点（如线下药店、医疗流通），不要匹配到中游的药品研发与生产、化学药、中药、生物药'

    batch_match_prompt = f'''你是一个产业链分析专家，也是一个构建产业链知识图谱的专家。

你的任务是根据每家公司的简介和主营产品，在已有的产业链节点({nodes_str})中找到最匹配的节点。

节点定义：
{nodes_definitions_str}

匹配规则：
- 根据公司主营产品和简介，结合节点定义，找到最相关的产业链节点
- 匹配关系可能是：包含关系、组成关系、关联关系{special_rule}
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
            "产业链名称": "{industry_name}"
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

    # 批量查询所有企业的真实业务信息
    company_names_list = [name for name, _ in all_companies]
    company_info_map = _batch_lookup_company_info(company_names_list, industry_name)

    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    results = []
    # 复用白名单缓存(已匹配节点的企业直接加入, 跳过 LLM)
    for _cn, _pos in _cached_companies:
        _mn, _mr, _ms, _ce = _wl_cache[_cn]
        results.append({
            '原始公司名': _cn,
            '企业名称': _cn,
            '主营产品': '',
            '公司简介': f'{_cn}是{industry_name}环节的头部企业。',
            '匹配节点': _mn,
            '匹配原因': _mr,
            '置信度': _ce,
            '分数': _ms,
        })
    total_companies = len(all_companies)
    total_batches = (total_companies + MATCH_BATCH_SIZE - 1) // MATCH_BATCH_SIZE

    if progress_callback:
        progress_callback('batch_progress', {
            'step': 6, 'step_name': '头部企业匹配节点',
            'current': 0, 'total': total_companies,
            'message': f'开始批量匹配企业到节点，共 {total_companies} 家（{total_batches} 批）'
        })

    logging.info(f"开始批量匹配，共 {total_companies} 家企业，{total_batches} 批（每批 {MATCH_BATCH_SIZE} 家）")

    for batch_start in range(0, total_companies, MATCH_BATCH_SIZE):
        batch = all_companies[batch_start:batch_start + MATCH_BATCH_SIZE]
        batch_num = batch_start // MATCH_BATCH_SIZE + 1

        if batch_num % 3 == 0 and is_cancelled(industry_name):
            logging.info(f"步骤6已被取消（已处理 {batch_start}/{total_companies} 家）")
            remove_token(industry_name)
            return {"step": 6, "name": "头部企业匹配节点", "status": "cancelled", "message": "用户取消操作"}

        # 构建本批企业的输入数据
        companies_input = []
        batch_name_map = {}
        for company_name, position in batch:
            real_info = company_info_map.get(company_name)
            if real_info and real_info.get("business"):
                input_data = {
                    "company_name": company_name,
                    "company_intro": real_info["business"][:500],
                    "major_product": real_info["product"][:500],
                    "industry_category": real_info["industry"][:200],
                }
            else:
                input_data = {
                    "company_name": company_name,
                    "company_intro": f"{company_name}是{industry_name}{position}环节的企业。",
                    "major_product": f"从事{industry_name}{position}相关业务",
                }
            companies_input.append(input_data)
            batch_name_map[company_name] = company_name

        logging.info(f"批次 {batch_num}/{total_batches}：匹配 {len(batch)} 家企业")

        for attempt in range(MAX_RETRIES):
            try:
                response = client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[
                        {'role': 'system', 'content': batch_match_prompt},
                        {'role': 'user', 'content': json.dumps({"companies": companies_input}, ensure_ascii=False)}
                    ],
                    temperature=0.6,
                    response_format={"type": "json_object"}
                )

                raw_content = response.choices[0].message.content
                parsed = json.loads(raw_content.replace("```json", "").replace("```", "").strip())

                batch_results = parsed.get('results', [])
                if isinstance(parsed, list):
                    batch_results = parsed

                for item in batch_results:
                    ai_name = str(item.get('企业名称', '')).strip()
                    matched_original = ai_name
                    for cn, _ in batch:
                        if cn == ai_name or cn in ai_name or ai_name in cn:
                            matched_original = cn
                            break
                    item['原始公司名'] = matched_original
                    results.append(item)

                matched_names = {str(r.get('企业名称', '')).strip() for r in batch_results}
                logging.info(f"  批次 {batch_num} 成功匹配 {len(batch_results)} 家")

                if progress_callback:
                    progress_callback('batch_progress', {
                        'step': 6, 'step_name': '头部企业匹配节点',
                        'current': min(batch_start + MATCH_BATCH_SIZE, total_companies),
                        'total': total_companies,
                        'message': f'已匹配 {min(batch_start + MATCH_BATCH_SIZE, total_companies)}/{total_companies} 家企业'
                    })
                break

            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    logging.warning(f"  批次 {batch_num} 第 {attempt+1} 次失败，{e}，1秒后重试")
                    time.sleep(1)
                else:
                    logging.error(f"  批次 {batch_num} 最终失败: {e}")
                    if progress_callback:
                        progress_callback('warning', {
                            'step': 6, 'step_name': '头部企业匹配节点',
                            'message': f'批次 {batch_num} 匹配失败: {e}'
                        })

    # ==================== 4.5 生命健康硬规则兜底(保存前) ====================
    # 药房/药铺企业无论来自缓存还是LLM, 只要匹配到非下游节点, 一律改为下游"线下药店"
    if industry_name == '生命健康':
        try:
            _ds_conn = get_db_connection()
            _ds_cur = _ds_conn.cursor()
            _ds_cur.execute(
                "SELECT nodes FROM industrial_chain.industrial_chain_structure "
                "WHERE chain_name=%s AND parent_node=%s", (industry_name, '产业链下游'))
            _ds_nodes = set()
            _lvl2 = [r[0] for r in _ds_cur.fetchall()]
            for _n2 in _lvl2:
                if _n2:
                    _ds_nodes.add(_n2)
                _ds_cur.execute(
                    "SELECT nodes FROM industrial_chain.industrial_chain_structure "
                    "WHERE chain_name=%s AND parent_node=%s", (industry_name, _n2))
                for (_g,) in _ds_cur.fetchall():
                    if _g:
                        _ds_nodes.add(_g)
            _ds_cur.close(); _ds_conn.close()
            _forced_cnt = 0
            for _r in results:
                _cname = str(_r.get('原始公司名', '') or _r.get('企业名称', ''))
                if ('药房' in _cname) or ('药铺' in _cname):
                    _mn = str(_r.get('匹配节点', '') or '')
                    _nlist = [x.strip() for x in _mn.split(';') if x.strip()]
                    _bad = [n for n in _nlist if n not in _ds_nodes]
                    if _bad or not _nlist:
                        _r['匹配节点'] = '线下药店'
                        _r['匹配原因'] = '生命健康下游:药房/药铺'
                        _r['置信度'] = '2'
                        _r['分数'] = '60'
                        _forced_cnt += 1
            if _forced_cnt:
                logging.info(f"生命健康药房/药铺兜底纠正: {_forced_cnt} 家 -> 线下药店")
        except Exception as _e:
            logging.warning(f"生命健康药房/药铺兜底检查失败(忽略): {_e}")

    # ==================== 5. 保存到数据库 ====================
    if results:
        save_conn = get_db_connection()
        save_cursor = save_conn.cursor()

        delete_sql = f"DELETE FROM {result_table} WHERE industry_name = %s"
        save_cursor.execute(delete_sql, (industry_name,))
        save_conn.commit()

        insert_sql = f"""
        INSERT INTO {result_table} (company_name, ai_company_name, major_product, company_intro, matched_nodes, match_reason, certainty, score, industry_name)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        for data in results:
            values = (
                data.get('原始公司名', ''),
                data.get('企业名称', ''),
                json.dumps(data.get('主营产品', ''), ensure_ascii=False),
                json.dumps(data.get('公司简介', ''), ensure_ascii=False),
                json.dumps(data.get('匹配节点', ''), ensure_ascii=False),
                json.dumps(data.get('匹配原因', ''), ensure_ascii=False),
                data.get('置信度', ''),
                data.get('分数', ''),
                industry_name
            )
            save_cursor.execute(insert_sql, values)

        save_conn.commit()
        save_cursor.close()
        save_conn.close()

        logging.info(f"成功插入 {len(results)} 条结果")

    remove_token(industry_name)
    logging.info(f"步骤6完成，共处理 {len(results)} 家企业")
    return {"step": 6, "name": "头部企业匹配节点", "status": "completed", "count": len(results)}


# ==================== 白名单加载 ====================

def load_whitelist_from_xlsx(industry_chain: str) -> Dict[str, List[str]]:
    """从 xlsx 文件读取白名单企业"""
    whitelist = {"上游": [], "中游": [], "下游": []}

    possible_filenames = [
        f"{industry_chain}-上中下游企业名录.xlsx",
        f"Industry_chain/{industry_chain}-上中下游企业名录.xlsx",
        f"{industry_chain}_上中下游企业名录.xlsx",
    ]

    for filename in possible_filenames:
        if os.path.exists(filename):
            try:
                df = pd.read_excel(filename)
                df_chain = df[df.iloc[:, 0].astype(str) == industry_chain]

                if not df_chain.empty:
                    for position in ["上游", "中游", "下游"]:
                        df_position = df_chain[df_chain.iloc[:, 1].astype(str) == position]
                        companies = df_position.iloc[:, 2].dropna().astype(str).str.strip().tolist()
                        whitelist[position] = [c for c in companies if c and c != 'nan']

                    total = sum(len(v) for v in whitelist.values())
                    logging.info(f"从 xlsx 文件 {filename} 加载了 {total} 家白名单企业")

                    whitelist = _complete_company_names(whitelist)
                    return whitelist

            except Exception as e:
                logging.error(f"读取 xlsx 文件 {filename} 失败: {str(e)}")

    return whitelist


def _complete_company_names(whitelist: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """补全白名单中的企业名称（批量优化版：DB查询用 IN 批量，天眼查逐家回退）"""
    import requests as req_lib

    FULL_NAME_SUFFIXES = ['有限公司', '股份有限公司', '集团有限公司', '集团股份有限公司']
    TIANYANCHA_TOKEN = os.getenv('TIANYANCHA_TOKEN')
    TIANYANCHA_API_URL = "https://open.api.tianyancha.com/services/open/search/2.0"

    completed_whitelist = {"上游": [], "中游": [], "下游": []}

    # 分类：已经是全名 vs 需要补全
    needs_completion = []
    for position, companies in whitelist.items():
        for company in companies:
            if any(suffix in company for suffix in FULL_NAME_SUFFIXES):
                completed_whitelist[position].append(company)
            else:
                needs_completion.append((company, position))

    if not needs_completion:
        return completed_whitelist

    logging.info(f"开始补全 {len(needs_completion)} 家企业名称")

    # 批量 DB 查询
    company_names = [c for c, _ in needs_completion]
    db_map = {}
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        chunk_size = 200
        for i in range(0, len(company_names), chunk_size):
            chunk = company_names[i:i + chunk_size]
            placeholders = ",".join(["%s"] * len(chunk))
            cursor.execute(f"""
                SELECT company_name, company_name_full
                FROM ent_industry_class_chain_scope_20260928_converted
                WHERE company_name IN ({placeholders})
                AND company_name_full IS NOT NULL AND company_name_full != ''
            """, chunk)
            for row in cursor.fetchall():
                db_map[row[0]] = row[1]
        cursor.close()
        conn.close()
    except Exception as e:
        logging.warning(f"批量查询企业全名失败: {e}")

    # 逐家处理：DB 命中则用，否则回退天眼查
    for company, position in needs_completion:
        if company in db_map and db_map[company] != company:
            logging.info(f"数据库匹配: {company} -> {db_map[company]}")
            completed_whitelist[position].append(db_map[company])
            continue

        try:
            params = {"word": company, "pageSize": 1}
            headers = {"Authorization": TIANYANCHA_TOKEN}
            response = req_lib.get(TIANYANCHA_API_URL, params=params, headers=headers, timeout=15)

            if response.status_code == 200:
                data = response.json()
                if data.get("error_code") == 0 and data.get("result", {}).get("items"):
                    full_name = data["result"]["items"][0].get("name")
                    if full_name and full_name != company:
                        logging.info(f"天眼查补全: {company} -> {full_name}")
                        completed_whitelist[position].append(full_name)
                        continue

            completed_whitelist[position].append(company)
        except Exception as e:
            logging.warning(f"天眼查补全失败 {company}: {e}")
            completed_whitelist[position].append(company)

    total_completed = sum(len(v) for v in completed_whitelist.values())
    logging.info(f"名称补全完成，共 {total_completed} 家企业")
    return completed_whitelist


if __name__ == "__main__":
    from auto_industry_chain_pipeline import TABLES
    step6_top_company_match("生物医药产业", TABLES)
