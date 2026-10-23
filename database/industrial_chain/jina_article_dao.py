import pymysql
from datetime import datetime
from typing import List, Dict, Any, Optional
from database.industrial_chain.connection import get_connection
from utils.logger import get_logger

logger = get_logger(__name__)

class JinaArticleDAO:
    """Jina文章内容数据访问对象"""
    
    @staticmethod
    async def save_article_content(url: str, title: str, content: str, 
                                 chain_name: str, node_name: str = None, 
                                 fetch_status: int = 1) -> bool:
        """
        保存文章内容到数据库
        
        Args:
            url: 文章URL
            title: 文章标题
            content: 文章完整内容
            chain_name: 产业链名称
            node_name: 节点名称（可选）
            fetch_status: 获取状态，1=成功，0=失败
            
        Returns:
            bool: 保存是否成功
        """
        conn = None
        try:
            conn = await get_connection()
            cursor = conn.cursor()
            
            # 清理数据，防止过长
            if title and len(title) > 500:
                title = title[:500]
            
            content_length = len(content) if content else 0
            
            sql = """
            INSERT INTO jina_article_content 
            (url, title, content, chain_name, node_name, content_length, fetch_status) 
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
            title = VALUES(title),
            content = VALUES(content),
            content_length = VALUES(content_length),
            fetch_status = VALUES(fetch_status),
            updated_at = CURRENT_TIMESTAMP
            """
            
            cursor.execute(sql, (url, title, content, chain_name, node_name, content_length, fetch_status))
            conn.commit()
            
            logger.info(f"保存文章内容成功: {chain_name} - {title[:50]}...")
            return True
            
        except Exception as e:
            logger.error(f"保存文章内容失败: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()
    
    @staticmethod
    async def get_articles_by_chain(chain_name: str, node_name: str = None, 
                                  limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """
        根据产业链名称获取文章列表
        
        Args:
            chain_name: 产业链名称
            node_name: 节点名称（可选）
            limit: 限制数量
            offset: 偏移量
            
        Returns:
            List[Dict]: 文章列表
        """
        conn = None
        try:
            conn = await get_connection()
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            
            if node_name:
                sql = """
                SELECT id, url, title, chain_name, node_name, content_length, 
                       fetch_status, created_at, updated_at
                FROM jina_article_content 
                WHERE chain_name = %s AND node_name = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """
                cursor.execute(sql, (chain_name, node_name, limit, offset))
            else:
                sql = """
                SELECT id, url, title, chain_name, node_name, content_length, 
                       fetch_status, created_at, updated_at
                FROM jina_article_content 
                WHERE chain_name = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """
                cursor.execute(sql, (chain_name, limit, offset))
            
            results = cursor.fetchall()
            return results
            
        except Exception as e:
            logger.error(f"获取文章列表失败: {e}")
            return []
        finally:
            if conn:
                conn.close()
    
    @staticmethod
    async def get_article_content(article_id: int) -> Optional[Dict[str, Any]]:
        """
        根据ID获取文章完整内容
        
        Args:
            article_id: 文章ID
            
        Returns:
            Dict: 文章详细信息，包含完整内容
        """
        conn = None
        try:
            conn = await get_connection()
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            
            sql = """
            SELECT * FROM jina_article_content WHERE id = %s
            """
            cursor.execute(sql, (article_id,))
            
            result = cursor.fetchone()
            return result
            
        except Exception as e:
            logger.error(f"获取文章内容失败: {e}")
            return None
        finally:
            if conn:
                conn.close()
    
    @staticmethod
    async def get_statistics(chain_name: str = None) -> Dict[str, Any]:
        """
        获取文章统计信息
        
        Args:
            chain_name: 产业链名称（可选）
            
        Returns:
            Dict: 统计信息
        """
        conn = None
        try:
            conn = await get_connection()
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            
            if chain_name:
                sql = """
                SELECT 
                    COUNT(*) as total_articles,
                    COUNT(DISTINCT node_name) as unique_nodes,
                    SUM(content_length) as total_content_length,
                    AVG(content_length) as avg_content_length,
                    SUM(CASE WHEN fetch_status = 1 THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN fetch_status = 0 THEN 1 ELSE 0 END) as failed_count
                FROM jina_article_content 
                WHERE chain_name = %s
                """
                cursor.execute(sql, (chain_name,))
            else:
                sql = """
                SELECT 
                    COUNT(*) as total_articles,
                    COUNT(DISTINCT chain_name) as unique_chains,
                    COUNT(DISTINCT node_name) as unique_nodes,
                    SUM(content_length) as total_content_length,
                    AVG(content_length) as avg_content_length,
                    SUM(CASE WHEN fetch_status = 1 THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN fetch_status = 0 THEN 1 ELSE 0 END) as failed_count
                FROM jina_article_content
                """
                cursor.execute(sql)
            
            result = cursor.fetchone()
            return result or {}
            
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}
        finally:
            if conn:
                conn.close()
    
    @staticmethod
    async def delete_articles_by_chain(chain_name: str) -> bool:
        """
        删除指定产业链的所有文章
        
        Args:
            chain_name: 产业链名称
            
        Returns:
            bool: 删除是否成功
        """
        conn = None
        try:
            conn = await get_connection()
            cursor = conn.cursor()
            
            sql = "DELETE FROM jina_article_content WHERE chain_name = %s"
            cursor.execute(sql, (chain_name,))
            affected_rows = cursor.rowcount
            conn.commit()
            
            logger.info(f"删除产业链文章成功: {chain_name}, 删除数量: {affected_rows}")
            return True
            
        except Exception as e:
            logger.error(f"删除产业链文章失败: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()