import asyncio
import logging
import json  # 添加json导入
from typing import List, Dict, Any
from datetime import datetime, timedelta  # 添加时间相关导入

from .jina_search_service import JinaSearcher
# 移除不存在的导入
# from database.industrial_chain.industry_db import get_node_article_links
from .report_config import ReportConfig

class ClassifiedWebpage:
    """分类后的网页数据"""
    def __init__(self, url: str, title: str, content: str, category_tags: List[str], classification_score: float):
        self.url = url
        self.title = title
        self.content = content
        self.category_tags = category_tags  # 基础分类标签
        self.classification_score = classification_score  # 分类置信度

class OptimizedWebpageService:
    """优化的网页服务 - 专注数据分类"""
    
    def __init__(self, jina_url: str = None, jina_headers: Dict[str, str] = None, industry_name: str = "测试产业"):
        self.logger = logging.getLogger(__name__)
        self.industry_name = industry_name
        
        # 只在需要时初始化JinaSearcher（用于新内容获取）
        self.jina_searcher = None
        if jina_url and jina_headers:
            self.jina_searcher = JinaSearcher(
                url=jina_url,
                headers=jina_headers,
                industry_name=industry_name
            )
        self.report_config = ReportConfig()

    async def _get_webpages_from_db(self, industry_name: str, limit: int = 100) -> List[Dict[str, str]]:
        """从数据库获取已缓存的网页数据，避免重复调用Jina API"""
        try:
            from database.industrial_chain.connection import get_connection
            
            conn = await get_connection()
            cursor = conn.cursor()
            
            # 修正查询条件：fetch_status应该是数字1，不是字符串'completed'
            query = """
            SELECT url, title, content
            FROM jina_article_content 
            WHERE chain_name = %s AND fetch_status = 1
            ORDER BY created_at DESC 
            LIMIT %s
            """
            
            cursor.execute(query, (industry_name, limit))
            results = cursor.fetchall()
            
            # 获取列名
            columns = [desc[0] for desc in cursor.description]
            
            # 转换为字典格式
            webpages = []
            for row in results:
                webpage_data = dict(zip(columns, row))
                # 确保包含必要的字段
                webpage_data = {
                    'url': webpage_data.get('url', ''),
                    'title': webpage_data.get('title', ''),
                    'content': webpage_data.get('content', '')
                }
                webpages.append(webpage_data)
            
            conn.close()
            self.logger.info(f"从数据库获取到 {len(webpages)} 个网页数据")
            return webpages
            
        except Exception as e:
            self.logger.error(f"从数据库获取网页数据失败: {e}")
            return []

    async def get_classified_webpages(self, industry_name: str = None, limit: int = 100, 
                                    mock_webpages: List[Dict[str, str]] = None,
                                    live_webpages: List[Dict[str, str]] = None) -> List[ClassifiedWebpage]:
        """获取并分类网页数据
        
        Args:
            industry_name: 产业链名称
            limit: 数量限制
            mock_webpages: 测试用模拟数据
            live_webpages: 正式运行时的实时文章数据（从产业链搜索收集）
        """
        try:
            # 优先级：live_webpages > mock_webpages > 数据库
            if live_webpages:
                webpages = live_webpages
                self.logger.info(f"使用产业链搜索收集的实时网页数据: {len(webpages)} 个")
            elif mock_webpages:
                webpages = mock_webpages
                self.logger.info(f"使用模拟网页数据: {len(webpages)} 个")
            elif industry_name:
                webpages = await self._get_webpages_from_db(industry_name, limit)
                if not webpages:
                    self.logger.warning(f"数据库中未找到产业链 {industry_name} 的网页数据")
                    return []
            else:
                self.logger.error("必须提供industry_name、mock_webpages或live_webpages参数")
                return []

            # 分类处理
            classified_webpages = []
            for webpage in webpages:
                try:
                    # 获取分类标签和置信度（移除await）
                    category_tags, classification_score = self._get_category_tags(
                        webpage.get('title', ''), 
                        webpage.get('content', '')
                    )
                    
                    classified_webpage = ClassifiedWebpage(
                        url=webpage.get('url', ''),
                        title=webpage.get('title', ''),
                        content=webpage.get('content', ''),
                        category_tags=category_tags,
                        classification_score=classification_score
                    )
                    
                    classified_webpages.append(classified_webpage)
                    
                except Exception as e:
                    self.logger.error(f"分类网页失败 {webpage.get('url', 'unknown')}: {e}")
                    continue
            
            self.logger.info(f"成功分类 {len(classified_webpages)} 个网页")
            return classified_webpages
            
        except Exception as e:
            self.logger.error(f"获取分类网页数据失败: {e}")
            return []

    def _extract_classification_text(self, webpage: Dict[str, str]) -> str:
        """提取用于分类的文本"""
        title = webpage.get('title', '')
        content = webpage.get('content', '')
        
        # 提取标题和前1000字符用于分类
        classification_text = title + ' ' + content[:1000]
        return classification_text
    
    def _get_category_tags(self, title: str, content: str) -> tuple[List[str], float]:
        """获取分类标签 - 基于BASIC_CATEGORIES的基础分类"""
        # 合并标题和内容进行分类
        text = title + ' ' + content
        category_scores = {}
        
        # 计算每个基础分类的匹配分数
        for category, keywords in self.report_config.BASIC_CATEGORIES.items():
            score = 0
            for keyword in keywords:
                if keyword in text:
                    score += 1
            
            if score > 0:
                # 标准化分数
                normalized_score = score / len(keywords)
                category_scores[category] = normalized_score
        
        # 筛选分类标签（阈值0.1）
        threshold = 0.1
        category_tags = [category for category, score in category_scores.items() if score >= threshold]
        
        # 计算总体分类置信度
        overall_score = sum(category_scores.values()) / len(self.report_config.BASIC_CATEGORIES) if category_scores else 0
        
        return category_tags, overall_score

    async def _fetch_complete_content(self, webpage_links: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """获取完整网页内容"""
        webpages = []
        
        for webpage in webpage_links:
            try:
                url = webpage['url']
                if not url:
                    continue
                
                # 使用Jina获取内容
                content_result = await self.jina_searcher.get_webpage_content(url)
                if content_result and content_result.get('content'):
                    webpage['title'] = content_result.get('title', '')
                    webpage['content'] = content_result.get('content', '')
                    webpages.append(webpage)
                    
            except Exception as e:
                self.logger.error(f"获取网页内容失败 {webpage.get('url', '')}: {e}")
                continue
        
        return webpages