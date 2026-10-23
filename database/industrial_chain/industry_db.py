import pymysql
from datetime import datetime
from typing import List, Dict, Any
from database.industrial_chain.connection import get_connection
from utils.logger import get_logger

logger = get_logger(__name__)

# 状态映射：将字符串状态映射到整数值
STATUS_MAPPING = {
    "未生成": 0,
    "生成中": 1,
    "已完成": 2,
    "已废弃": 3   # 已废弃状态值为3
}

# 反向状态映射：将整数值映射到字符串状态
STATUS_REVERSE_MAPPING = {v: k for k, v in STATUS_MAPPING.items()}

# 将我们的状态术语映射到数据库状态值
PROCESS_STATUS_MAPPING = {
    "处理中": STATUS_MAPPING["生成中"],
    "搜索中": STATUS_MAPPING["生成中"],
    "搜索完成": STATUS_MAPPING["生成中"],
    "提取节点和关系中": STATUS_MAPPING["生成中"],
    "已完成": STATUS_MAPPING["已完成"],
    "已废弃": STATUS_MAPPING["已废弃"]  # 添加已废弃状态映射
}

# 默认搜索网站
DEFAULT_SEARCH_SITES = ["qianzhan.com", "zhihu.com", "askci.com"]

async def create_industry_record(name, user_id, custom_urls=None, sites=None):
    """
    创建产业链分析记录
    
    Args:
        name: 产业链名称
        user_id: 用户ID
        custom_urls: 用户提供的自定义URL列表
        sites: 用户指定的搜索网站列表
    
    Returns:
        新创建记录的ID
    """
    conn = None
    try:
        conn = await get_connection()
        cursor = conn.cursor()
        
        # 首先检查是否已存在同名产业链
        check_sql = "SELECT id FROM industrial_chain_meta WHERE name = %s"
        cursor.execute(check_sql, (name,))
        existing_records = cursor.fetchall()
        
        # 如果存在同名记录，将其状态更新为"已废弃"
        if existing_records and len(existing_records) > 0:
            logger.info(f"发现同名产业链 '{name}'，共 {len(existing_records)} 条记录，将其状态更新为已废弃")
            
            # 更新industrial_chain_meta表中的记录状态
            update_meta_sql = "UPDATE industrial_chain_meta SET status = %s WHERE name = %s"
            cursor.execute(update_meta_sql, (STATUS_MAPPING["已废弃"], name))
            logger.info(f"成功将产业链 '{name}' 的 {cursor.rowcount} 条记录标记为已废弃")
            
            # 同时更新industrial_chain_structure表中对应产业链的记录状态
            update_structure_sql = "UPDATE industrial_chain_structure SET status = %s WHERE chain_name = %s"
            cursor.execute(update_structure_sql, (2, name))  # 根据表结构，已废弃状态值为2
            structure_updated = cursor.rowcount
            logger.info(f"成功将产业链 '{name}' 的 {structure_updated} 条三元组记录标记为已废弃")
        
        # 将自定义URL列表转换为换行符分隔的字符串
        attach_info = '\n'.join(custom_urls) if custom_urls else ''
        
        # 使用用户指定的搜索网站，如果未提供则使用默认值
        search_sites = sites if sites else DEFAULT_SEARCH_SITES
        url_sources = '\n'.join(search_sites)
        
        # 插入记录
        sql = """
        INSERT INTO industrial_chain_meta 
        (name, source, source_note, attach_info, url_sources, status, created_at) 
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.execute(sql, (
            name,
            "用户输入",  # source - 不再指定具体用户ID
            "",  # source_note
            attach_info,
            url_sources,
            STATUS_MAPPING["生成中"],  # 使用整数值表示状态
            datetime.now()
        ))
        
        # 获取新插入记录的ID
        record_id = cursor.lastrowid
        conn.commit()
        return record_id
        
    except Exception as e:
        logger.error(f"创建产业链记录时发生错误: {e}")
        if conn:
            logger.info("回滚事务")
            conn.rollback()
        import traceback
        logger.error(f"详细错误信息: {traceback.format_exc()}")
        raise e
    finally:
        if conn:
            conn.close()

async def update_industry_name(record_id, new_name):
    """
    更新产业链名称（用于清理名称后同步更新meta表）
    
    Args:
        record_id: 记录ID
        new_name: 新的产业链名称
    
    Returns:
        是否更新成功
    """
    conn = None
    try:
        conn = await get_connection()
        cursor = conn.cursor()
        
        sql = """
        UPDATE industrial_chain_meta 
        SET name = %s
        WHERE id = %s
        """
        
        cursor.execute(sql, (new_name, record_id))
        affected_rows = cursor.rowcount
        conn.commit()
        
        logger.info(f"更新产业链名称成功: record_id={record_id}, new_name='{new_name}', 影响行数={affected_rows}")
        return affected_rows > 0
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"更新产业链名称失败: {e}")
        raise e
    finally:
        if conn:
            conn.close()

async def update_industry_status(record_id, status):
    """
    更新产业链分析状态
    
    Args:
        record_id: 记录ID
        status: 新状态（字符串）
    """
    conn = None
    try:
        conn = await get_connection()
        cursor = conn.cursor()
        
        # 准备更新字段
        update_fields = ["status = %s"]
        
        # 将我们的处理状态映射到数据库状态
        db_status = PROCESS_STATUS_MAPPING.get(status, STATUS_MAPPING["生成中"])
        params = [db_status]
        
        # 构建SQL语句
        sql = f"""
        UPDATE industrial_chain_meta 
        SET {', '.join(update_fields)}
        WHERE id = %s
        """
        
        # 添加record_id到参数列表
        params.append(record_id)
        
        # 执行更新
        cursor.execute(sql, params)
        conn.commit()
        
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()

async def get_industry_record(record_id):
    """
    获取产业链分析记录
    
    Args:
        record_id: 记录ID
    
    Returns:
        记录详情字典
    """
    conn = None
    try:
        conn = await get_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        sql = "SELECT * FROM industrial_chain_meta WHERE id = %s"
        cursor.execute(sql, (record_id,))
        
        record = cursor.fetchone()
        
        # 如果找到记录，将整数状态转换为字符串状态
        if record and 'status' in record:
            status_int = record['status']
            record['status_text'] = STATUS_REVERSE_MAPPING.get(status_int, "未知状态")
            
        return record
        
    finally:
        if conn:
            conn.close()

async def get_industry_records_by_name(name):
    """
    按名称查询产业链分析记录
    
    Args:
        name: 产业链名称
    
    Returns:
        记录列表
    """
    conn = None
    try:
        conn = await get_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        sql = "SELECT * FROM industrial_chain_meta WHERE name = %s ORDER BY created_at DESC"
        cursor.execute(sql, (name,))
        
        records = cursor.fetchall()
        
        # 将整数状态转换为字符串状态
        for record in records:
            if 'status' in record:
                status_int = record['status']
                record['status_text'] = STATUS_REVERSE_MAPPING.get(status_int, "未知状态")
                
        return records
        
    finally:
        if conn:
            conn.close()

async def get_industry_chains_by_status() -> Dict[str, List[str]]:
    """
    获取产业链元数据，按状态分组返回已完成、生成中和未生成的产业链名称，
    排除已废弃的产业链(status=3)

    Returns:
        包含已完成、生成中和未生成产业链名称的字典
    """
    connection = None
    try:
        # 获取数据库连接
        connection = await get_connection()
        cursor = connection.cursor(pymysql.cursors.DictCursor)

        # 查询已完成的产业链 (status = 2)
        completed_query = """
        SELECT
            name
        FROM industrial_chain_meta
        WHERE status = 2
        ORDER BY created_at DESC
        """

        cursor.execute(completed_query)
        completed_chains = [row['name'] for row in cursor.fetchall()]

        # 查询生成中的产业链 (status = 1) - 不要求有结构数据或文章链接
        in_progress_query = """
        SELECT
            name
        FROM industrial_chain_meta
        WHERE status = 1
        ORDER BY created_at DESC
        """

        cursor.execute(in_progress_query)
        in_progress_chains = [row['name'] for row in cursor.fetchall()]

        # 查询未生成的产业链 (status = 0)
        not_started_query = """
        SELECT
            name
        FROM industrial_chain_meta
        WHERE status = 0
        ORDER BY created_at DESC
        """

        cursor.execute(not_started_query)
        not_started_chains = [row['name'] for row in cursor.fetchall()]

        logger.info(f"从数据库获取到 {len(completed_chains)} 条已完成产业链，{len(in_progress_chains)} 条生成中产业链，{len(not_started_chains)} 条未生成产业链")

        return {
            "completed": completed_chains,
            "in_progress": in_progress_chains,
            "not_started": not_started_chains
        }

    except Exception as e:
        logger.error(f"获取产业链状态数据时出错: {str(e)}")
        return {
            "completed": [],
            "in_progress": [],
            "not_started": []
        }

    finally:
        if connection:
            connection.close()


async def get_industry_chains_with_details() -> Dict[str, Any]:
    """
    获取产业链列表及详细信息（节点数量、更新时间等）
    优化版本：一次查询返回所有数据，避免N+1查询问题

    Returns:
        包含已完成、生成中和未生成产业链详细信息的字典
    """
    connection = None
    try:
        # 获取数据库连接
        connection = await get_connection()
        cursor = connection.cursor(pymysql.cursors.DictCursor)

        # 一次性查询所有产业链的元数据
        meta_query = """
        SELECT
            name,
            status,
            created_at
        FROM industrial_chain_meta
        WHERE status != 3
        ORDER BY created_at DESC
        """

        cursor.execute(meta_query)
        all_chains = cursor.fetchall()

        # 获取所有已完成的产业链名称，用于批量查询节点数量
        completed_chain_names = [c['name'] for c in all_chains if c['status'] == 2]

        # 批量查询节点数量
        node_count_map = {}
        if completed_chain_names:
            # 使用一条SQL查询所有产业链的节点数量
            # 排除包含"上游"、"中游"、"下游"、"核心"这些关键词的节点
            placeholders = ','.join(['%s'] * len(completed_chain_names))
            node_count_query = f"""
            SELECT
                chain_name,
                COUNT(*) as node_count
            FROM industrial_chain_structure
            WHERE chain_name IN ({placeholders})
                AND nodes IS NOT NULL
                AND status = 1
                AND nodes NOT IN ('上游', '中游', '下游', '核心')
                AND nodes NOT LIKE '%%上游%%'
                AND nodes NOT LIKE '%%中游%%'
                AND nodes NOT LIKE '%%下游%%'
                AND nodes NOT LIKE '%%核心%%'
            GROUP BY chain_name
            """
            cursor.execute(node_count_query, completed_chain_names)
            for row in cursor.fetchall():
                node_count_map[row['chain_name']] = row['node_count']

        # 构建结果
        completed = []
        in_progress = []
        not_started = []

        for chain in all_chains:
            chain_info = {
                "name": chain['name'],
                "nodes": node_count_map.get(chain['name'], '-'),
                "updateTime": chain['created_at'].strftime('%Y-%m-%d %H:%M') if chain['created_at'] else '-'
            }

            if chain['status'] == 2:
                completed.append(chain_info)
            elif chain['status'] == 1:
                in_progress.append(chain_info)
            else:
                not_started.append(chain_info)

        logger.info(f"获取到 {len(completed)} 条已完成，{len(in_progress)} 条生成中，{len(not_started)} 条未开始")

        return {
            "completed": completed,
            "in_progress": in_progress,
            "not_started": not_started
        }

    except Exception as e:
        logger.error(f"获取产业链详细信息时出错: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "completed": [],
            "in_progress": [],
            "not_started": []
        }

    finally:
        if connection:
            connection.close() 