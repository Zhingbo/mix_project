"""
快照表创建脚本

用于增量更新功能的变更检测：
- whitelist_snapshot: 白名单处理快照
- graph_node_snapshot: 图谱节点处理快照
"""

import os

import pymysql
from utils.logger import get_logger

logger = get_logger(__name__)

DB_CONFIG = {
    'host': os.getenv('DB_HOST', '8.141.5.67'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_NAME', 'business_data')
}


def create_snapshot_tables():
    """创建快照表"""

    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        # 1. 创建白名单快照表
        create_whitelist_snapshot_sql = """
        CREATE TABLE IF NOT EXISTS whitelist_snapshot (
            id INT AUTO_INCREMENT PRIMARY KEY,
            industry_name VARCHAR(100) NOT NULL COMMENT '产业链名称',
            company_name VARCHAR(255) NOT NULL COMMENT '企业名称',
            position VARCHAR(50) COMMENT '上游/中游/下游',
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '处理时间',
            UNIQUE KEY uk_industry_company (industry_name, company_name),
            INDEX idx_industry_name (industry_name),
            INDEX idx_processed_at (processed_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='白名单处理快照'
        """
        cursor.execute(create_whitelist_snapshot_sql)
        logger.info("表 whitelist_snapshot 已确保存在")

        # 2. 创建图谱节点快照表
        create_graph_snapshot_sql = """
        CREATE TABLE IF NOT EXISTS graph_node_snapshot (
            id INT AUTO_INCREMENT PRIMARY KEY,
            industry_name VARCHAR(100) NOT NULL COMMENT '产业链名称',
            node_name VARCHAR(255) NOT NULL COMMENT '节点名称',
            node_definition TEXT COMMENT '节点定义内容',
            node_hash VARCHAR(64) COMMENT '节点定义的哈希值（MD5）',
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '处理时间',
            UNIQUE KEY uk_industry_node (industry_name, node_name),
            INDEX idx_industry_name (industry_name),
            INDEX idx_processed_at (processed_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='图谱节点处理快照'
        """
        cursor.execute(create_graph_snapshot_sql)
        logger.info("表 graph_node_snapshot 已确保存在")

        conn.commit()
        logger.info("快照表创建完成")

        return True

    except Exception as e:
        logger.error(f"创建快照表失败: {e}")
        conn.rollback()
        return False

    finally:
        cursor.close()
        conn.close()


def init_whitelist_snapshot(industry_name: str) -> int:
    """
    初始化白名单快照（从现有白名单数据导入）

    Args:
        industry_name: 产业链名称

    Returns:
        导入的记录数
    """
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        # 检查是否已有快照数据
        cursor.execute(
            "SELECT COUNT(*) FROM whitelist_snapshot WHERE industry_name = %s",
            (industry_name,)
        )
        existing_count = cursor.fetchone()[0]

        if existing_count > 0:
            logger.info(f"产业链 {industry_name} 已有白名单快照，跳过初始化")
            return existing_count

        # 从 whitelist_company 导入
        insert_sql = """
        INSERT INTO whitelist_snapshot (industry_name, company_name, position)
        SELECT industry_name, company_name, position
        FROM whitelist_company
        WHERE industry_name = %s
        """
        cursor.execute(insert_sql, (industry_name,))
        conn.commit()

        count = cursor.rowcount
        logger.info(f"初始化产业链 {industry_name} 的白名单快照，导入 {count} 条记录")
        return count

    except Exception as e:
        logger.error(f"初始化白名单快照失败: {e}")
        conn.rollback()
        return 0

    finally:
        cursor.close()
        conn.close()


def init_graph_snapshot(industry_name: str) -> int:
    """
    初始化图谱节点快照（从现有节点数据导入）

    Args:
        industry_name: 产业链名称

    Returns:
        导入的记录数
    """
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        # 检查是否已有快照数据
        cursor.execute(
            "SELECT COUNT(*) FROM graph_node_snapshot WHERE industry_name = %s",
            (industry_name,)
        )
        existing_count = cursor.fetchone()[0]

        if existing_count > 0:
            logger.info(f"产业链 {industry_name} 已有图谱节点快照，跳过初始化")
            return existing_count

        # 从 chain_needcomp 导入
        import hashlib

        insert_sql = """
        INSERT INTO graph_node_snapshot (industry_name, node_name, node_definition, node_hash)
        SELECT chain_name, nodes,
               COALESCE(nodes_definition, ''),
               MD5(COALESCE(nodes_definition, ''))
        FROM chain_needcomp
        WHERE chain_name = %s
        """
        cursor.execute(insert_sql, (industry_name,))
        conn.commit()

        count = cursor.rowcount
        logger.info(f"初始化产业链 {industry_name} 的图谱节点快照，导入 {count} 条记录")
        return count

    except Exception as e:
        logger.error(f"初始化图谱节点快照失败: {e}")
        conn.rollback()
        return 0

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    # 创建表
    if create_snapshot_tables():
        print("快照表创建成功")

        # 可以在这里初始化现有产业链的快照
        # init_whitelist_snapshot("测试产业")
        # init_graph_snapshot("测试产业")
