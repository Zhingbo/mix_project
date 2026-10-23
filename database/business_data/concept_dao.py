from typing import List, Dict, Any
import pymysql
from database.business_data.connection import get_connection
from utils.logger import get_logger

logger = get_logger(__name__)

class ConceptDAO:
    """
    概念板块数据访问对象，负责数据库操作
    """
    
    @staticmethod
    async def get_top_concepts(limit: int = 4) -> List[Dict[str, Any]]:
        """
        从数据库获取热门概念板块数据，按照top_num字段降序排序（最热门的在前）
        
        Args:
            limit: 返回的记录数量限制
            
        Returns:
            热门概念列表
        """
        connection = None
        try:
            # 获取数据库连接
            connection = await get_connection()
            cursor = connection.cursor(pymysql.cursors.DictCursor)
            
            # 执行查询，按照top_num字段降序排序并限制结果数量
            query = """
            SELECT 
                id, 
                concept_name,
                top_num, 
                up_num,
                DATE_FORMAT(create_time, '%%Y-%%m-%%d %%H:%%i:%%s') as create_time,
                DATE_FORMAT(update_time, '%%Y-%%m-%%d %%H:%%i:%%s') as update_time
            FROM kpl_finance_concept_info 
            ORDER BY top_num DESC 
            LIMIT %s
            """
            
            cursor.execute(query, (limit,))
            result = cursor.fetchall()
            logger.info(f"从数据库获取到 {len(result)} 条热门概念数据")
            return result
            
        except Exception as e:
            logger.error(f"数据库获取热门概念数据时出错: {str(e)}")
            return []
            
        finally:
            if connection:
                connection.close()

    @classmethod
    async def get_top_concepts_with_offset(cls, limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
        """
        获取热门金融概念数据，支持分页查询
        
        Args:
            limit: 获取记录的数量
            offset: 偏移量，从第几条记录开始获取
            
        Returns:
            热门概念列表
        """
        connection = None
        try:
            # 获取数据库连接
            connection = await get_connection()
            cursor = connection.cursor(pymysql.cursors.DictCursor)
            
            # 执行查询，按照top_num字段降序排序并限制结果数量
            query = """
            SELECT 
                id, 
                concept_name,
                top_num, 
                up_num,
                DATE_FORMAT(create_time, '%%Y-%%m-%%d %%H:%%i:%%s') as create_time,
                DATE_FORMAT(update_time, '%%Y-%%m-%%d %%H:%%i:%%s') as update_time
            FROM kpl_finance_concept_info 
            ORDER BY top_num DESC 
            LIMIT %s OFFSET %s
            """
            
            cursor.execute(query, (limit, offset))
            result = cursor.fetchall()
            logger.info(f"从数据库获取到 {len(result)} 条热门概念数据 (偏移量: {offset})")
            return result
            
        except Exception as e:
            logger.error(f"获取带偏移的热门概念数据时出错: {str(e)}")
            return []
            
        finally:
            if connection:
                connection.close() 