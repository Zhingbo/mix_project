from database.industrial_chain.industry_db import (
    create_industry_record,
    update_industry_status,
    update_industry_name,
    get_industry_record,
    get_industry_records_by_name,
    STATUS_MAPPING,
    STATUS_REVERSE_MAPPING
)
from utils.logger import get_logger

logger = get_logger(__name__)

class IndustryStorageService:
    """产业链存储服务，负责处理产业链分析结果的存储和查询"""
    
    @staticmethod
    async def initialize_record(industry_name, user_id, custom_urls=None, sites=None):
        """
        初始化产业链分析记录
        
        Args:
            industry_name: 产业链名称
            user_id: 用户ID
            custom_urls: 用户提供的自定义URL列表
            sites: 用户指定的搜索网站列表
            
        Returns:
            新创建记录的ID
        """
        try:
            record_id = await create_industry_record(industry_name, user_id, custom_urls, sites)
            return record_id
        except Exception as e:
            import traceback
            raise
    
    @staticmethod
    async def update_status(record_id, status):
        """
        更新产业链分析状态
        
        Args:
            record_id: 记录ID
            status: 新状态
        """
        try:
            await update_industry_status(record_id, status)
        except Exception as e:
            logger.error(f"更新产业链分析状态失败: {e}")
            # 不抛出异常，避免中断主流程
    
    @staticmethod
    async def update_name(record_id, new_name):
        """
        更新产业链名称（用于清理名称后同步更新meta表）
        
        Args:
            record_id: 记录ID
            new_name: 新的产业链名称
            
        Returns:
            是否更新成功
        """
        try:
            result = await update_industry_name(record_id, new_name)
            if result:
                logger.info(f"成功更新产业链名称: record_id={record_id}, new_name='{new_name}'")
            return result
        except Exception as e:
            logger.error(f"更新产业链名称失败: {e}")
            # 不抛出异常，避免中断主流程
            return False
    
    @staticmethod
    async def complete_record(record_id, result_path):
        """
        完成产业链分析记录
        
        Args:
            record_id: 记录ID
            result_path: 结果文件路径（不再存储到数据库）
        """
        try:
            await update_industry_status(record_id, "已完成")
            logger.info(f"已完成产业链分析记录: ID={record_id}, 结果路径={result_path}")
        except Exception as e:
            logger.error(f"完成产业链分析记录失败: {e}")
            # 不抛出异常，避免中断主流程
    
    @staticmethod
    async def mark_as_failed(record_id, error_message):
        """
        标记产业链分析为已废弃
        
        Args:
            record_id: 记录ID
            error_message: 错误信息（不再存储到数据库）
        """
        try:
            # 首先获取产业链记录，以便获取产业链名称
            record = await get_industry_record(record_id)
            if not record:
                logger.error(f"无法获取ID为{record_id}的产业链记录")
                return
            
            industry_name = record.get('name')
            if not industry_name:
                logger.error(f"ID为{record_id}的产业链记录没有名称")
                return
            
            # 更新产业链状态为已废弃
            await update_industry_status(record_id, "已废弃")
            logger.info(f"已标记产业链分析为已废弃: ID={record_id}, 名称={industry_name}, 错误={error_message}")
            
            # 同时更新该产业链的所有三元组记录状态
            conn = None
            try:
                from database.industrial_chain.connection import get_connection
                
                conn = await get_connection()
                cursor = conn.cursor()
                
                # 更新industrial_chain_structure表中对应产业链的记录状态
                update_structure_sql = "UPDATE industrial_chain_structure SET status = %s WHERE chain_name = %s"
                cursor.execute(update_structure_sql, (2, industry_name))  # 根据表结构，已废弃状态值为2
                structure_updated = cursor.rowcount
                conn.commit()
                
                logger.info(f"成功将产业链 '{industry_name}' 的 {structure_updated} 条三元组记录标记为已废弃")
            except Exception as e:
                logger.error(f"更新三元组状态失败: {e}")
                if conn:
                    conn.rollback()
            finally:
                if conn:
                    conn.close()
                
        except Exception as e:
            logger.error(f"标记产业链分析为已废弃状态失败: {e}")
            # 不抛出异常，避免中断主流程
    
    @staticmethod
    async def get_record(record_id):
        """
        获取产业链分析记录
        
        Args:
            record_id: 记录ID
            
        Returns:
            记录详情字典
        """
        try:
            record = await get_industry_record(record_id)
            return record
        except Exception as e:
            logger.error(f"获取产业链分析记录失败: {e}")
            raise
    
    @staticmethod
    async def get_records_by_name(industry_name):
        """
        按名称查询产业链分析记录
        
        Args:
            industry_name: 产业链名称
            
        Returns:
            记录列表
        """
        try:
            records = await get_industry_records_by_name(industry_name)
            return records
        except Exception as e:
            logger.error(f"按名称查询产业链分析记录失败: {e}")
            raise 