from typing import Dict, List, Any
from database.industrial_chain.industry_db import get_industry_chains_by_status, get_industry_chains_with_details
from utils.logger import get_logger

logger = get_logger(__name__)

class IndustryStatusService:
    """
    产业链状态服务，提供产业链状态相关的业务逻辑
    """

    @staticmethod
    async def get_industry_chains_by_status() -> Dict[str, List[str]]:
        """
        获取已完成、生成中和未生成的产业链名称

        Returns:
            包含已完成、生成中和未生成产业链名称的字典
        """
        try:
            # 通过DB模块获取数据
            result = await get_industry_chains_by_status()

            logger.info(f"获取到 {len(result['completed'])} 条已完成产业链，{len(result['in_progress'])} 条生成中产业链，{len(result['not_started'])} 条未生成产业链")
            return result

        except Exception as e:
            logger.error(f"获取产业链状态数据时出错: {str(e)}")
            return {
                "completed": [],
                "in_progress": [],
                "not_started": []
            }

    @staticmethod
    async def get_industry_chains_with_details() -> Dict[str, List[Dict[str, Any]]]:
        """
        获取已完成、生成中和未生成的产业链详细信息（包括节点数量、更新时间等）
        优化版本：一次查询返回所有数据，避免N+1查询问题

        Returns:
            包含已完成、生成中和未生成产业链详细信息的字典
        """
        try:
            result = await get_industry_chains_with_details()

            logger.info(f"获取到 {len(result['completed'])} 条已完成，{len(result['in_progress'])} 条生成中，{len(result['not_started'])} 条未开始")
            return result

        except Exception as e:
            logger.error(f"获取产业链详细信息时出错: {str(e)}")
            return {
                "completed": [],
                "in_progress": [],
                "not_started": []
            } 