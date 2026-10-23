"""
步骤2：生成节点定义

功能：使用AI为产业链节点自动生成定义
优化：批量发送节点到LLM（每批最多8个），减少API请求次数；复用客户端和数据库连接；失败自动重试
"""

import os
import json
import time
import pymysql
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("DASHSCOPE_API_KEY", os.getenv("DASHSCOPE_API_KEY"))
OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL = "deepseek-v4.1-flash"
BATCH_SIZE = 8
MAX_RETRIES = 3


def _cleanup_deleted_nodes_from_mapping(industry_name: str, removed_nodes: list) -> int:
    """清理已删除节点的行业映射数据"""
    if not removed_nodes:
        return 0

    conn = pymysql.connect(
        host='8.141.5.67',
        user='root',
        password=os.getenv('DB_PASSWORD'),
        database='business_data'
    )
    cursor = conn.cursor()

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

    conn.commit()
    cursor.close()
    conn.close()

    logger.info(f"清理已删除节点 {removed_nodes} 的行业映射数据，共 {deleted_count} 条")
    return deleted_count


def step2_generate_definition(industry_name, tables, whitelist_data=None, progress_callback=None, change_context=None):
    """
    为产业链节点生成定义（批量优化版）

    优化点：
    - 每批最多8个节点发送给LLM，减少请求次数（原来每个节点一次请求）
    - 复用OpenAI客户端，避免重复建立TLS连接
    - 复用数据库连接，避免每个节点创建新连接
    - 失败自动重试（最多3次）

    Args:
        industry_name: 产业链名称
        tables: 表名配置字典
        whitelist_data: 白名单数据（可选）
        progress_callback: 进度回调函数
        change_context: 变更上下文（增量更新时使用）
    """
    host = '8.141.5.67'
    user = 'root'
    password = os.getenv('DB_PASSWORD')
    database = 'business_data'
    port = 3306

    table_name = tables['chain_needcomp']

    system_prompt = f'''下边是产业链名称({industry_name})和该产业链中的多个节点名称，你需要结合产业链对每个节点给出一个简短的定义。

结果输出：请以JSON格式返回每个节点的定义，格式如下:
{{
    "definitions": [
        {{"节点名称": "内饰", "节点定义": "内饰包括汽车内部装饰材料和部件，如座椅、仪表盘、门板等。"}},
        {{"节点名称": "变速箱", "节点定义": "变速箱是汽车传动系统的核心部件..."}}
    ]
}}

注意：
1. 必须为每个给定的节点都给出定义，不要遗漏任何节点
2. 节点名称必须与输入的节点名称完全一致，不要修改
3. 定义要简短精练，一两句话即可
'''

    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    print(f"\n{'='*40}")
    print(f"步骤2：为产业链节点生成定义（批量模式，每批{BATCH_SIZE}个）")
    print(f"产业链名称: {industry_name}")
    print(f"目标表: {table_name}")

    # 增量更新处理
    nodes_to_process = None

    if change_context:
        removed_nodes = change_context.get('removed_nodes', [])
        added_nodes = change_context.get('added_nodes', [])
        modified_nodes = change_context.get('modified_nodes', [])

        if removed_nodes:
            print(f"检测到已删除节点: {removed_nodes}，开始清理关联数据")
            _cleanup_deleted_nodes_from_mapping(industry_name, removed_nodes)

        if added_nodes or modified_nodes:
            nodes_to_process = set(added_nodes + modified_nodes)
            print(f"增量模式：只处理变更的节点 {nodes_to_process}")
        elif not removed_nodes:
            print("增量模式：无节点变更，跳过步骤2")
            return {"step": 2, "name": "生成节点定义", "status": "skipped", "reason": "无节点变更"}

    conn = pymysql.connect(host=host, user=user, password=password, database=database, port=port)
    cursor = conn.cursor()

    try:
        sql = f"SELECT chain_name, nodes FROM {table_name} WHERE chain_name = %s"
        cursor.execute(sql, (industry_name,))
        rows = cursor.fetchall()

        print(f"查询到 {len(rows)} 条节点记录")

        if nodes_to_process is not None:
            rows = [(c, n) for c, n in rows if n in nodes_to_process]
            print(f"增量过滤后需要处理 {len(rows)} 条节点记录")
            if not rows:
                print("没有需要处理的节点，跳过步骤2")
                return {"step": 2, "name": "生成节点定义", "status": "skipped", "reason": "无需要处理的节点"}

        total_batches = (len(rows) + BATCH_SIZE - 1) // BATCH_SIZE
        updated_count = 0

        for batch_start in range(0, len(rows), BATCH_SIZE):
            batch = rows[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            batch_nodes = [node for _, node in batch]
            chain_name = batch[0][0]

            nodes_str = "、".join(batch_nodes)
            user_content = f"产业链名称：{chain_name}，节点名称：{nodes_str}"
            print(f"\n批次 {batch_num}/{total_batches}：处理 {len(batch_nodes)} 个节点: {nodes_str}")

            for attempt in range(MAX_RETRIES):
                try:
                    response = client.chat.completions.create(
                        model=LLM_MODEL,
                        messages=[
                            {'role': 'system', 'content': system_prompt},
                            {'role': 'user', 'content': user_content}
                        ],
                        temperature=0.6,
                        response_format={"type": "json_object"}
                    )

                    content = response.choices[0].message.content
                    result = json.loads(content)

                    definitions = result.get('definitions', [])
                    if isinstance(result, list):
                        definitions = result

                    for item in definitions:
                        node_name = str(item.get('节点名称', '')).strip()
                        node_def = str(item.get('节点定义', '')).strip()
                        if node_name and node_def:
                            update_sql = f"UPDATE {table_name} SET nodes_definition = %s WHERE chain_name = %s AND nodes = %s"
                            cursor.execute(update_sql, (node_def, chain_name, node_name))
                            updated_count += 1
                            print(f"  更新成功：{node_name}")

                    conn.commit()

                    returned_names = {str(item.get('节点名称', '')).strip() for item in definitions}
                    missing = set(batch_nodes) - returned_names
                    if missing:
                        logger.warning(f"  批次 {batch_num} 有 {len(missing)} 个节点未返回定义: {missing}")

                    break

                except Exception as e:
                    if attempt < MAX_RETRIES - 1:
                        logger.warning(f"  批次 {batch_num} 第 {attempt+1} 次失败，{e}，1秒后重试")
                        time.sleep(1)
                    else:
                        logger.error(f"  批次 {batch_num} 最终失败: {e}")

        print(f"\n步骤2完成，共更新 {updated_count} 个节点定义")

    except Exception as e:
        print(f"执行失败：{e}")
    finally:
        cursor.close()
        conn.close()

    return {"step": 2, "name": "生成节点定义", "status": "completed"}


if __name__ == "__main__":
    step2_generate_definition("氢能产业", None)
