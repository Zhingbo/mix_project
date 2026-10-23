"""
步骤3：节点匹配行业

功能：使用AI将产业链节点匹配到行业分类
优化：批量发送节点到LLM（每批最多5个），减少API请求次数；客户端在函数内创建一次复用；失败自动重试
"""

import os
import json
import time
from openai import OpenAI
import pandas as pd
import pymysql
from pymysql import Error
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("DASHSCOPE_API_KEY", os.getenv("DASHSCOPE_API_KEY"))
OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL = "deepseek-v4.1-flash"
BATCH_SIZE = 5
MAX_RETRIES = 3


def _cleanup_deleted_nodes_mapping(industry_name: str, removed_nodes: list) -> int:
    """清理已删除节点的行业映射数据"""
    if not removed_nodes:
        return 0

    cnx = pymysql.connect(
        user='root',
        password=os.getenv('DB_PASSWORD'),
        host='8.141.5.67',
        database='business_data'
    )
    cursor = cnx.cursor()
    deleted_count = 0

    for node in removed_nodes:
        try:
            cursor.execute(
                "DELETE FROM nodes_industry_mapping WHERE industry_name = %s AND nodes = %s",
                (industry_name, node)
            )
            deleted_count += cursor.rowcount
        except Exception as e:
            logger.warning(f"清理 nodes_industry_mapping 中节点 {node} 失败: {e}")

    cnx.commit()
    cursor.close()
    cnx.close()

    logger.info(f"清理已删除节点 {removed_nodes} 的行业映射数据，共 {deleted_count} 条")
    return deleted_count


# ==================== 表名配置 ====================
TABLES = {
    'chain_needcomp': 'chain_needcomp',
    'mapping_industry_info_new': 'mapping_industry_info_new',
    'nodes_industry_mapping': 'nodes_industry_mapping',
}


def connect_to_mysql():
    try:
        cnx = pymysql.connect(
            user='root',
            password=os.getenv('DB_PASSWORD'),
            host='8.141.5.67',
            database='business_data'
        )
        return cnx
    except Error as err:
        print(f"无法连接到数据库：{err}")
        return None


def get_data_from_mysql(query, params=None):
    cnx = connect_to_mysql()
    if not cnx:
        return None
    cursor = cnx.cursor()
    try:
        cursor.execute(query, params or ())
        columns = [col[0] for col in cursor.description]
        data = cursor.fetchall()
        df = pd.DataFrame(data, columns=columns)
        return df
    except Error as err:
        print(f"查询数据时出错：{err}")
    finally:
        cursor.close()
        cnx.close()
    return None


def create_table(cnx):
    """创建节点匹配表"""
    cursor = cnx.cursor()
    create_table_query = """
    CREATE TABLE IF NOT EXISTS nodes_industry_mapping (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nodes VARCHAR(255),
        name VARCHAR(255),
        level VARCHAR(255),
        full_name VARCHAR(255),
        industry_name VARCHAR(255),
        reason TEXT
    )
    """
    try:
        cursor.execute(create_table_query)
        cnx.commit()
        print("表 nodes_industry_mapping 创建成功或已存在。")
    except Error as err:
        print(f"创建表时出错：{err}")
    finally:
        cursor.close()


def insert_data(table_name, data):
    """插入数据"""
    cnx = connect_to_mysql()
    if not cnx:
        print("无法连接到数据库")
        return
    cursor = cnx.cursor()
    insert_query = f"""
    INSERT INTO {table_name} (nodes, name, level, full_name, industry_name, reason)
    VALUES (%s, %s, %s, %s, %s, %s)
    """
    try:
        cursor.executemany(insert_query, data)
        cnx.commit()
        print(f"成功插入 {cursor.rowcount} 条数据。")
    except Error as err:
        print(f"插入数据时出错：{err}")
    finally:
        cursor.close()
        cnx.close()


def _count_existing_mappings(industry_name: str) -> int:
    cnx = connect_to_mysql()
    if not cnx:
        return 0
    cursor = cnx.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM nodes_industry_mapping WHERE industry_name = %s",
            (industry_name,)
        )
        return cursor.fetchone()[0]
    except Error as err:
        logger.warning(f"检查节点映射数据失败: {err}")
        return 0
    finally:
        cursor.close()
        cnx.close()


FRONTIER_MARKS = ["超导", "核聚变", "托卡马克", "等离子体", "量子", "脑机", "数字孪生", "元宇宙", "合成生物", "光量子", "粒子", "智能算力", "大模型", "AI芯片"]
BROAD_MANUF = ["输配电", "电机制造", "通信设备", "钢铁", "金属冶炼", "通用设备", "专用设备", "泵、阀门", "铸造", "模具", "轴承", "齿轮", "通用机械", "金属压延"]


def _is_frontier_broad(node_name, full_name):
    """前沿概念节点被配到通用制造宽类 -> 视为无精确匹配"""
    if any(m in (node_name or "") for m in FRONTIER_MARKS):
        if any(b in (full_name or "") for b in BROAD_MANUF):
            return True
    return False


def _validate_match_item(item, name_info):
    """校验单条匹配结果，返回标准化字典或None"""
    if not isinstance(item, dict):
        return None

    node_name = str(item.get('节点名称') or '').strip()
    industry_name = str(item.get('行业名称') or item.get('匹配行业') or '').strip()
    reason = str(item.get('匹配原因') or item.get('原因') or '').strip()

    if not node_name:
        logger.warning(f"AI返回缺少节点名称，跳过: {item}")
        return None

    if not industry_name:
        logger.warning(f"节点 {node_name} AI返回缺少行业名称，跳过")
        return None

    if industry_name not in name_info:
        logger.warning(f"AI返回的行业名称 '{industry_name}' 不在行业名称库中，节点：{node_name}")
        return None

    # 跳过兜底宽类(一级是"其他" 或 三级是"其他..."): 前沿节点找不到精确行业时避免落宽类导致下游爆炸
    _lv, _fn = name_info.get(industry_name, (None, None))
    if _fn:
        _fn = str(_fn)
        _segs = _fn.split('|')
        if _fn.startswith('其他|') or (len(_segs) >= 3 and _segs[-1].startswith('其他')):
            logger.info(f"节点 {node_name} 映射到兜底宽类 '{_fn}'，跳过(视为无精确匹配)")
            return None

    if _fn and _is_frontier_broad(node_name, str(_fn)):
        logger.info(f"节点 {node_name} 是前沿概念但配到通用制造宽类 '{_fn}'，跳过(视为无精确匹配)")
        return None

    if not reason:
        reason = f'AI未返回匹配原因，按节点"{node_name}"与行业"{industry_name}"的匹配结果保留。'
        logger.warning(f"节点 {node_name} AI返回缺少匹配原因，已使用默认原因")

    return {
        '节点名称': node_name,
        '行业名称': industry_name,
        '匹配原因': reason,
    }


def process_industry(industry_name, tables, change_context=None):
    """处理行业匹配（批量优化版）"""
    print(f"开始处理行业：{industry_name}")

    # 增量更新处理
    nodes_to_process = None

    if change_context:
        removed_nodes = change_context.get('removed_nodes', [])
        added_nodes = change_context.get('added_nodes', [])
        modified_nodes = change_context.get('modified_nodes', [])

        if removed_nodes:
            print(f"检测到已删除节点: {removed_nodes}，开始清理关联数据")
            _cleanup_deleted_nodes_mapping(industry_name, removed_nodes)

        if added_nodes or modified_nodes:
            nodes_to_process = set(added_nodes + modified_nodes)
            print(f"增量模式：只处理变更的节点 {nodes_to_process}")
        elif not removed_nodes:
            existing_count = _count_existing_mappings(industry_name)
            if existing_count > 0:
                print("增量模式：无节点变更，跳过步骤3")
                return []
            print("增量模式：无节点变更，但节点映射表为空，执行全量步骤3")

    cnx = connect_to_mysql()
    if not cnx:
        print(f"无法连接到数据库，程序将退出。")
        return

    create_table(cnx)

    query_nodes = f"""
    SELECT DISTINCT nodes FROM {tables['chain_needcomp']}
    WHERE chain_name = %s
    """

    df_nodes = get_data_from_mysql(query_nodes, params=(industry_name,))
    if df_nodes is None or df_nodes.empty:
        print(f"行业 {industry_name} 没有更多未处理的产业链节点，退出。")
        return

    nodes = df_nodes['nodes'].tolist()

    if nodes_to_process is not None:
        original_nodes = nodes[:]
        nodes = [n for n in nodes if n in nodes_to_process]
        print(f"增量过滤：从 {len(original_nodes)} 个节点中筛选出 {len(nodes)} 个需要处理的节点")
        if not nodes:
            print("没有需要处理的节点，跳过步骤3")
            return []

    # 过滤掉非叶节点
    excluded = {industry_name, '上游', '中游', '下游'}
    valid_nodes = [n for n in nodes if n not in excluded]
    print(f"行业 {industry_name} 待匹配节点（{len(valid_nodes)}个）：{valid_nodes}")

    if not valid_nodes:
        print("过滤后没有需要匹配的节点")
        return []

    # 获取行业名称库
    query = """
    SELECT DISTINCT name, level, full_name FROM mapping_industry_info_new
    """
    df = get_data_from_mysql(query)
    if df is None:
        print("未成功获取数据，程序将退出。")
        return

    name_info = {row['name']: (row['level'], row['full_name']) for _, row in df.iterrows()}
    names = df['name'].tolist()

    # 在函数内创建客户端（避免模块级全局状态在多 worker 下出问题）
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    # 批量系统提示词
    system_prompt = f'''你是一个行业分析专家，也是一个产业链知识专家。
    我会给你多个需要匹配的产业链节点名称，你的任务是为每个节点在已有的行业名称库{names}中找到与{industry_name}相关的1个最匹配的行业名称，并给出你的匹配原因。

    具体匹配逻辑为：
        - 节点与行业名称之间可能是以下关系之一：包含关系、组成关系、相似关系、同类关系。你需要根据这些关系找到与节点最为相关的行业名称。
        - **包含关系**：节点是行业名称的一部分。例如，节点"伺服器"包含于行业名称"伺服器生产制造"。
        - **组成关系**：节点是行业的组成部分。例如，节点"伺服器"是"机器人零部件制造"的组成部分。
        - **相似关系**：节点与行业名称在语义或功能用途上相似。例如，节点"原材料"与行业名称"新材料"语义相似。
        - **同类关系**：节点与行业名称属于同一类别。例如，节点"锂电池"与行业名称"新能源电池制造"属于同一类别。

        注意：
        - 如果存在多个行业名称与节点相关，优先选择更具体、更直接相关的行业名称。
        - 还需要考虑节点在产业链中的位置（上游原材料、中游零部件、下游终端产品）。
        - **重要：你只能在行业名称库{names}中选择行业名称，严禁创造或使用不在库中的行业名称。**
        - **如果某个节点在行业名称库中找不到精确、直接相关的行业（只能找到"其他XX"、"其他专用设备/其他批发业/其他未列明"这类过于宽泛、无法区分该节点的兜底类别），请在该节点的"行业名称"字段返回"无匹配"，不要强行匹配宽泛类别。**

    请你以JSON格式返回所有节点的匹配结果：
    {{
        "matches": [
            {{
                "节点名称": "伺服器",
                "行业名称": "机器人零部件制造",
                "匹配原因": "伺服器是机器人的核心零部件之一，与机器人零部件制造这个行业名称最相关。"
            }},
            {{
                "节点名称": "传感器",
                "行业名称": "传感器制造",
                "匹配原因": "传感器属于传感器制造这一行业分类。"
            }}
        ]
    }}

    注意：
    1. 返回结果中的属性名和属性值都要用双引号括起来
    2. 对每个给定的节点都返回结果，但"行业名称"可以是"无匹配"（表示找不到精确相关的行业，不要强行匹配宽泛类别）
    3. 每个节点只返回一个最相关的行业名称
    4. 请严格按照 {industry_name} 相关的节点进行匹配
    '''

    # 批量匹配
    results = []
    total_batches = (len(valid_nodes) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_start in range(0, len(valid_nodes), BATCH_SIZE):
        batch = valid_nodes[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        nodes_str = "、".join(batch)

        print(f"\n批次 {batch_num}/{total_batches}：匹配 {len(batch)} 个节点: {nodes_str}")

        for attempt in range(MAX_RETRIES):
            try:
                response = client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': f"请为以下节点进行行业匹配：{nodes_str}"}
                    ],
                    response_format={"type": "json_object"}
                )

                raw = response.choices[0].message.content
                cleaned = str(raw).replace("```json", "").replace("```", "").strip()
                parsed = json.loads(cleaned)

                matches = parsed.get('matches', [])
                if isinstance(parsed, list):
                    matches = parsed

                batch_results = []
                for item in matches:
                    validated = _validate_match_item(item, name_info)
                    if validated:
                        batch_results.append(validated)
                        print(f"  {validated['节点名称']} -> {validated['行业名称']}")

                results.extend(batch_results)

                returned_names = {str(item.get('节点名称', '')).strip() for item in matches}
                missing = set(batch) - returned_names
                if missing:
                    logger.warning(f"  批次 {batch_num} 有 {len(missing)} 个节点未返回匹配: {missing}")

                break

            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    logger.warning(f"  批次 {batch_num} 第 {attempt+1} 次失败，{e}，1秒后重试")
                    time.sleep(1)
                else:
                    logger.error(f"  批次 {batch_num} 最终失败: {e}")

    print(f"\n行业 {industry_name} 的匹配结果共 {len(results)} 条")

    # 保存匹配结果
    if results:
        data_to_insert = []
        for item in results:
            matched_industry = item.get('行业名称')
            if matched_industry not in name_info:
                logger.warning(f"保存前校验失败，行业名称不在库中: {matched_industry}")
                continue
            data_to_insert.append(
                (
                    item.get('节点名称', ''),
                    matched_industry,
                    name_info.get(matched_industry, (None, None))[0],
                    name_info.get(matched_industry, (None, None))[1],
                    industry_name,
                    item.get('匹配原因') or f'AI未返回匹配原因，按行业"{matched_industry}"匹配结果保留。'
                )
            )

        if data_to_insert:
            insert_data(tables['nodes_industry_mapping'], data_to_insert)
            print(f"行业 {industry_name} 的数据已成功插入数据库。")
        else:
            logger.warning(f"行业 {industry_name} 没有通过保存前校验的节点映射数据")

    return results


def step3_match_industryry(industry_name, tables, whitelist_data=None, progress_callback=None, change_context=None):
    """步骤3：节点匹配行业（批量优化版）"""
    print(f"\n{'='*40}")
    print(f"步骤3：节点匹配行业（批量模式，每批{BATCH_SIZE}个）")
    print(f"产业链名称: {industry_name}")
    print(f"目标表: {tables['nodes_industry_mapping']}")
    print(f"{'='*40}")

    return process_industry(industry_name, tables, change_context)
