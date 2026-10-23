import pymysql
from datetime import datetime
from database.industrial_chain.connection import get_connection
from utils.logger import get_logger

logger = get_logger(__name__)

async def store_industry_structure(chain_name, node_name=None, parent_node=None, parent_id=None, node_level=0, chain_id=None, from_node_id=None, to_node_id=None, relation_type=None):
    """
    存储产业链结构节点或关系
    
    Args:
        chain_name: 产业链名称
        node_name: 节点名称
        parent_node: 父节点名称
        parent_id: 父节点ID
        node_level: 节点层级
        chain_id: 产业链ID，对应industrial_chain_meta表的id
        from_node_id: 起始节点ID（用于存储关系）
        to_node_id: 目标节点ID（用于存储关系）
        relation_type: 关系类型（用于存储关系）
    
    Returns:
        新创建记录的ID
    """
    conn = None
    try:
        conn = await get_connection()
        cursor = conn.cursor()
        
        now = datetime.now()
        
        # 根据参数判断是存储节点还是关系
        if from_node_id and to_node_id:
            # 存储节点之间的关系
            sql = """
            INSERT INTO industrial_chain_structure
            (chain_name, from_node_id, to_node_id, relation_type, create_time, update_time, chain_id, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """

            cursor.execute(sql, (
                chain_name,
                from_node_id,
                to_node_id,
                relation_type,
                now,
                now,
                chain_id if chain_id else 0,  # 如果没有chain_id，使用0作为默认值
                1  # 默认状态为"使用中"(1)
            ))
        else:
            # 存储节点
            sql = """
            INSERT INTO industrial_chain_structure
            (chain_name, nodes, parent_node, parent_id, node_level, create_time, update_time, chain_id, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """

            cursor.execute(sql, (
                chain_name,
                node_name,
                parent_node,
                parent_id,
                node_level,
                now,
                now,
                chain_id if chain_id else 0,  # 如果没有chain_id，使用0作为默认值
                1  # 默认状态为"使用中"(1)
            ))
        
        # 获取新插入记录的ID
        record_id = cursor.lastrowid
        conn.commit()
        return record_id
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"存储产业链结构节点失败: {e}")
        raise e
    finally:
        if conn:
            conn.close()

async def get_node_id_by_name(chain_name, node_name):
    """
    根据产业链名称和节点名称获取节点ID

    Args:
        chain_name: 产业链名称
        node_name: 节点名称

    Returns:
        节点ID，如果不存在则返回None
    """
    conn = None
    try:
        conn = await get_connection()
        cursor = conn.cursor()

        sql = """
        SELECT id FROM industrial_chain_structure
        WHERE chain_name = %s AND nodes = %s
        ORDER BY status DESC, id DESC
        LIMIT 1
        """

        cursor.execute(sql, (chain_name, node_name))
        result = cursor.fetchone()

        # 正常返回结果，无论是否找到都不打印错误
        return result[0] if result else None

    except Exception as e:
        # 只在发生真正的异常时记录错误，而不是查询没有结果
        if str(e) != '0':  # 不是简单的0值错误
            logger.error(f"获取节点ID失败: {e}")
        return None
    finally:
        if conn:
            conn.close()

async def clear_industry_structure(chain_name):
    """
    清除指定产业链的所有结构数据
    
    Args:
        chain_name: 产业链名称
    """
    conn = None
    try:
        conn = await get_connection()
        cursor = conn.cursor()
        
        sql = "DELETE FROM industrial_chain_structure WHERE chain_name = %s"
        
        cursor.execute(sql, (chain_name,))
        conn.commit()
        
        logger.info(f"已清除产业链 {chain_name} 的结构数据")
        return True
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"清除产业链结构数据失败: {e}")
        return False
    finally:
        if conn:
            conn.close()

# 已删除 get_industry_nodes 函数 - 该函数用于获取产业链的所有节点

# 已删除 get_industry_relations 函数 - 该函数用于获取产业链的所有关系

# 已删除 update_industry_structure 函数 - 该函数用于更新产业链结构数据 