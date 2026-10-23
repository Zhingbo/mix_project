import os
import re
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
from datetime import datetime

from .enhanced_ai_client import UnifiedAIClient, EnhancedAIClient
from .optimized_webpage_service import OptimizedWebpageService, ClassifiedWebpage
from .report_config import ReportConfig
from .jina_search_service import JinaSearcher
# from .jina_key_manager import JinaKeyManager
from utils.logger import get_logger
from .crawler_service import log_message
from .global_managers import get_global_key_manager, get_global_jina_searcher

class OptimizedTemplateFiller:
    """优化的模板填充器 - 实现三种填充策略并严格保留模板格式"""
    
    def __init__(self, ai_api_key: str = None):
        # 初始化logger
        self.logger = get_logger(__name__)
        
        # 优先使用增强版AI客户端
        if ai_api_key:
            self.ai_client = EnhancedAIClient(ai_api_key)
            self.use_batching = True
        else:
            self.ai_client = UnifiedAIClient()
            self.use_batching = False
        
        self.webpage_service = OptimizedWebpageService()
        self.report_config = ReportConfig()
        
        # 初始化Jina搜索服务
        self.jina_searcher = None
        
        # 模板路径
        self.detailed_template_path = "/root/mix_project/新版产业链分析报告模板.md"
        self.simple_template_path = "/root/mix_project/产业链分析报告模板-精简版.md"
    
    async def _init_jina_searcher(self, industry_name: str):
        """初始化Jina搜索器 - 使用全局单例"""
        if not self.jina_searcher:
            self.jina_searcher = await get_global_jina_searcher(industry_name)
            log_message(None, f"🔧 Template Filler使用全局JinaSearcher: {industry_name}", log_type="INFO")
    
    def _extract_chapter_content_from_template(self, template_path: str, chapter_title: str) -> str:
        """从模板文件中提取指定章节的原始内容"""
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
            
            lines = template_content.split('\n')
            chapter_content = []
            in_target_chapter = False
            current_level = 0
            
            for line in lines:
                # 匹配章节标题
                header_match = re.match(r'^(#{1,6})\s+(.+)', line)
                if header_match:
                    level = len(header_match.group(1))
                    title = header_match.group(2).strip()
                    
                    # 检查是否是目标章节（模糊匹配）
                    if chapter_title in title or title in chapter_title or any(keyword in title for keyword in chapter_title.split()):
                        in_target_chapter = True
                        current_level = level
                        chapter_content = [line]
                        continue
                    
                    # 如果已经在目标章节中，检查是否遇到同级或更高级标题
                    if in_target_chapter and level <= current_level:
                        break
                
                # 如果在目标章节中，收集内容
                if in_target_chapter:
                    chapter_content.append(line)
            
            return '\n'.join(chapter_content) if chapter_content else f"# {chapter_title}\n\n待填充内容..."
            
        except Exception as e:
            self.logger.error(f"提取章节内容失败 {chapter_title}: {e}")
            return f"# {chapter_title}\n\n待填充内容..."
    
    def _is_protected_content(self, line: str) -> bool:
        """判断是否为受保护的内容（图表、表格等）"""
        line = line.strip()
        
        # Mermaid图表
        if line.startswith('```mermaid') or line == '```':
            return True
        
        # 表格行
        if '|' in line and line.count('|') >= 2:
            return True
        
        # 星级评分
        if re.search(r'[★☆]{3,5}', line):
            return True
        
        # 数值数据格式
        if re.search(r'\d+[万亿千百十]?[元人次个家]', line):
            return True
        
        # 百分比数据
        if re.search(r'\d+\.?\d*%', line):
            return True
        
        return False
    
    async def _strategy_1_classified_articles(self, chapter_title: str, original_content: str, 
                                            industry_data: Dict[str, Any], 
                                            classified_webpages: List[ClassifiedWebpage], 
                                            template_type: str, user_id: str) -> Optional[str]:
        """策略1：使用分类文章匹配填充"""
        try:
            # 使用report_config中的章节配置进行匹配
            matched_webpages = self._find_matching_webpages_by_config(
                chapter_title, classified_webpages, template_type
            )
            
            if not matched_webpages:
                log_message(user_id, f"章节 '{chapter_title}' 未找到匹配的分类文章", log_type="INFO")
                return None
            
            log_message(user_id, f"章节 '{chapter_title}' 找到 {len(matched_webpages)} 篇匹配文章", log_type="INFO")
            
            # 添加内容质量检查
            industry_name = industry_data.get('name', industry_data.get('industry_name', '未知产业'))
            high_quality_webpages = await self._filter_high_quality_webpages(
                matched_webpages, chapter_title, industry_name, user_id, min_relevance=0.6
            )
            
            if not high_quality_webpages:
                log_message(user_id, f"章节 '{chapter_title}' 未找到高质量相关文章，将使用其他策略", log_type="INFO")
                return None
            
            log_message(user_id, f"章节 '{chapter_title}' 筛选出 {len(high_quality_webpages)} 篇高质量文章", log_type="INFO")
            
            # 构建AI提示词，强调保留模板格式
            current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
            
            # 检查是否为详细版报告，添加技术对比要求
            tech_comparison_requirement = ""
            if template_type == "detailed":
                tech_comparison_requirement = """
**特别要求（仅限详细版报告）：**
- 在相关技术章节中，必须包含国内外技术对比分析
- 重点关注国产替代率分析：我们不能做什么，谁能做，能做到什么程度，差距多大
- 分析技术成熟度对比：国外先进技术 vs 国内技术水平
- 识别技术壁垒和突破点，评估国产化可能性
- 提供具体的技术差距数据和时间预期（如有）
- 这是深度版定制的核心分析内容，务必详细展开"""
            
            prompt = f"""
你是一名专业的产业分析报告撰写专家。请基于以下搜索到的相关文章内容，为产业链分析报告的章节生成内容,包括报告头信息和各章节内容。
**报告信息：**
- 报告标题：产业链深度分析报告
- 分析机构：智能产业分析平台
- 报告生成时间：{current_time}


**重要要求：**
1. 严格按照原始模板的格式和结构
2. 不得修改或删除任何图表（mermaid图表、表格等）
3. 不得修改数值数据和统计信息的格式
4. 只填充文本描述部分，保持专业性和准确性
5. 保持原有的markdown格式和层级结构{tech_comparison_requirement}

**章节信息：**
章节标题：{chapter_title}
产业名称：{industry_name}

**原始模板内容：**
{original_content}

**参考文章内容（已通过质量检查）：**
{self._format_content_for_prompt(high_quality_webpages[:5], "webpage")}

请生成填充后的完整章节内容，确保格式与原模板完全一致：
"""
            
            response = await self._handle_ai_generation(prompt, user_id)
            if response and response.strip():
                log_message(user_id, f"策略1成功填充章节: {chapter_title}", log_type="INFO")
                return response
            
            return None
            
        except Exception as e:
            log_message(user_id, f"策略1填充章节失败 {chapter_title}: {e}", log_type="ERROR")
            return None
    
    async def _strategy_2_jina_search(self, chapter_title: str, original_content: str, 
                                    industry_data: Dict[str, Any], user_id: str, report_type: str = "simple") -> Optional[str]:
        """策略2：使用Jina搜索填充"""
        try:
            industry_name = industry_data.get('name', '未知产业')
            
            # 初始化Jina搜索器
            await self._init_jina_searcher(industry_name)
            
            # 确保Jina搜索器已正确初始化
            if not self.jina_searcher:
                log_message(user_id, f"Jina搜索器初始化失败，跳过策略2", log_type="ERROR")
                return None
            
            # 提取章节关键词并构建搜索查询
            chapter_keywords = self._extract_chapter_keywords(chapter_title)
            search_query = f"{industry_name} {chapter_keywords}"
            
            log_message(user_id, f"为章节 '{chapter_title}' 执行Jina搜索，查询: {search_query}", log_type="INFO")
            
            # 执行搜索
            search_results = await self.jina_searcher.jina_search(
                limit=15,  # 从15增加到25
                isNode=False,
                user_id=user_id,
                get_full_content=False
            )
            
            if not search_results or 'results' not in search_results or not search_results['results']:
                log_message(user_id, f"章节 '{chapter_title}' Jina搜索无结果", log_type="INFO")
                return None
            
            log_message(user_id, f"章节 '{chapter_title}' Jina搜索找到 {len(search_results['results'])} 篇文章", log_type="INFO")
            
            # 构建AI提示词
            current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
            
            # 检查是否为详细版报告，添加技术对比要求
            tech_comparison_requirement = ""
            if report_type == "detailed":
                tech_comparison_requirement = """
**特别要求（仅限详细版报告）：**
- 在相关技术章节中，必须包含国内外技术对比分析
- 重点关注国产替代率分析：我们不能做什么，谁能做，能做到什么程度，差距多大
- 分析技术成熟度对比：国外先进技术 vs 国内技术水平
- 识别技术壁垒和突破点，评估国产化可能性
- 提供具体的技术差距数据和时间预期（如有）
- 这是深度版定制的核心分析内容，务必详细展开"""
            
            prompt = f"""
你是一名专业的产业分析报告撰写专家。请基于以下搜索到的相关文章内容，为产业链分析报告的章节生成内容,包括报告头信息和各章节内容。
**报告信息：**
- 报告标题：产业链深度分析报告
- 分析机构：智能产业分析平台
- 报告生成时间：{current_time}

**重要要求：**
1. 严格按照原始模板的格式和结构
2. 不得修改或删除任何图表（mermaid图表、表格等）
3. 不得修改数值数据和统计信息的格式
4. 只填充文本描述部分，保持专业性和准确性
5. 保持原有的markdown格式和层级结构
6. 绝对不要在报告中包含任何技术内部数据（如nodes、node_level、id等）
7. 确保所有mermaid图表语法正确{tech_comparison_requirement}

**章节信息：**
章节标题：{chapter_title}
产业名称：{industry_data.get('name', '未知产业')}

**原始模板内容：**
{original_content}

**搜索结果内容：**
{self._format_search_results_for_prompt(search_results['results'][:5])}

请生成填充后的完整章节内容，确保格式与原模板完全一致：
"""
            
            response = await self._handle_ai_generation(prompt, user_id)
            if response and response.strip():
                log_message(user_id, f"策略2成功填充章节: {chapter_title}", log_type="INFO")
                return response
            
            return None
            
        except Exception as e:
            log_message(user_id, f"策略2填充章节失败 {chapter_title}: {e}", log_type="ERROR")
            return None
    
    async def _strategy_3_ai_analysis(self, chapter_title: str, original_content: str, 
                                    industry_data: Dict[str, Any], user_id: str, report_type: str = "simple") -> str:
        """策略3：AI自行分析填充"""
        try:
            log_message(user_id, f"章节 '{chapter_title}' 使用AI自行分析填充", log_type="INFO")
            
            # 构建AI提示词
            current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
            
            # 检查是否为详细版报告，添加技术对比要求
            tech_comparison_requirement = ""
            if report_type == "detailed":
                tech_comparison_requirement = """
**特别要求（仅限详细版报告）：**
- 在相关技术章节中，必须包含国内外技术对比分析
- 重点关注国产替代率分析：我们不能做什么，谁能做，能做到什么程度，差距多大
- 分析技术成熟度对比：国外先进技术 vs 国内技术水平
- 识别技术壁垒和突破点，评估国产化可能性
- 提供具体的技术差距数据和时间预期（如有）
- 这是深度版定制的核心分析内容，务必详细展开"""
            
            prompt = f"""
你是一名专业的产业分析报告撰写专家。请基于以下信息，为产业链分析报告的章节生成内容。
**报告信息：**
- 报告标题：产业链深度分析报告
- 分析机构：智能产业分析平台
- 报告生成时间：{current_time}


**重要要求：**
1. 严格按照原始模板的格式和结构
2. 不得修改或删除任何图表（mermaid图表、表格等）
3. 不得修改数值数据和统计信息的格式
4. 只填充文本描述部分，基于行业通用知识进行专业分析
5. 保持原有的markdown格式和层级结构
6. 如果缺乏具体数据，请说明并提供行业一般性分析
7. 绝对不要在报告中包含任何技术内部数据（如nodes、node_level、id等）
8. 确保所有mermaid图表语法正确{tech_comparison_requirement}

**章节信息：**
章节标题：{chapter_title}
产业名称：{industry_data.get('name', '未知产业')}
产业描述：{industry_data.get('description', '暂无描述')}
**原始模板内容：**
{original_content}

**产业基础数据：**
{self._format_industry_data_for_prompt(industry_data)}

请生成填充后的完整章节内容，确保格式与原模板完全一致，不包含任何技术内部数据：
"""
            
            response = await self._handle_ai_generation(prompt, user_id, original_content)
            log_message(user_id, f"策略3完成章节填充: {chapter_title}", log_type="INFO")
            return response
            
        except Exception as e:
            log_message(user_id, f"策略3填充章节失败 {chapter_title}: {e}", log_type="ERROR")
            return original_content  # 返回原始内容作为最后备选
    
    def _find_matching_webpages_by_config(self, chapter_title: str, 
                                         classified_webpages: List[ClassifiedWebpage],
                                         template_type: str) -> List[ClassifiedWebpage]:
        """使用report_config配置匹配网页到章节"""
        # 清理章节标题，移除markdown标记
        clean_title = re.sub(r'^#{1,6}\s+', '', chapter_title).strip()
        
        # 获取章节关键词
        chapter_keywords = self.report_config.get_chapter_keywords_by_template(
            clean_title, template_type
        )
        
        if not chapter_keywords:
            # 如果没有找到配置的关键词，尝试从标题提取
            chapter_keywords = [self._extract_chapter_keywords(chapter_title)]
        
        matched_webpages = []
        
        for webpage in classified_webpages:
            score = self._calculate_matching_score_by_keywords(webpage, chapter_keywords)
            if score > 0:
                matched_webpages.append((webpage, score))
        
        # 按分数排序并返回
        matched_webpages.sort(key=lambda x: x[1], reverse=True)
        return [webpage for webpage, score in matched_webpages]
    
    def _calculate_matching_score_by_keywords(self, webpage: ClassifiedWebpage, 
                                            chapter_keywords: List[str]) -> float:
        """根据关键词计算匹配分数"""
        score = 0
        webpage_tags = [tag.lower() for tag in webpage.category_tags]
        webpage_title = webpage.title.lower()
        webpage_content = webpage.content.lower() if webpage.content else ""
        
        for keyword in chapter_keywords:
            keyword_lower = keyword.lower()
            
            # 标签匹配（权重最高）
            if any(keyword_lower in tag for tag in webpage_tags):
                score += 3
            
            # 标题匹配
            if keyword_lower in webpage_title:
                score += 2
            
            # 内容匹配（权重最低）
            if keyword_lower in webpage_content:
                score += 1
        
        return score
    
    def _extract_chapter_keywords(self, chapter_title: str) -> str:
        """从章节标题中提取关键词"""
        # 移除章节编号和markdown标记
        keywords = re.sub(r'^#{1,6}\s+', '', chapter_title)
        keywords = re.sub(r'^第.+章\s*', '', keywords)
        keywords = re.sub(r'^\d+\.\d*\s*', '', keywords)
        
        # 移除常见的报告术语
        stop_words = ['分析', '研究', '概述', '总结', '介绍', '说明', '报告']
        for word in stop_words:
            keywords = keywords.replace(word, '')
        
        return keywords.strip()
    
    async def _check_content_relevance(self, webpage: ClassifiedWebpage, chapter_title: str, 
                                     industry_name: str, user_id: str) -> float:
        """检查文章内容与章节的相关性，返回相关性分数(0-1)"""
        try:
            # 清理章节标题
            clean_chapter_title = re.sub(r'^#{1,6}\s+', '', chapter_title).strip()
            
            # 提取章节关键词
            chapter_keywords = self._extract_chapter_keywords(chapter_title)
            
            # 构建相关性检查提示词
            prompt = f"""
请评估以下文章内容与报告章节的相关性。

**评估标准：**
1. 内容是否直接涉及指定产业
2. 内容是否与章节主题相关
3. 信息质量和可信度
4. 内容的时效性和准确性

**产业名称：** {industry_name}
**章节标题：** {clean_chapter_title}
**章节关键词：** {chapter_keywords}

**文章信息：**
标题：{webpage.title}
分类标签：{', '.join(webpage.category_tags)}
内容预览：{webpage.content[:500]}...

请给出0-1之间的相关性分数，其中：
- 0.8-1.0：高度相关，内容直接对应章节主题
- 0.6-0.8：较为相关，内容部分对应章节主题
- 0.4-0.6：一般相关，内容间接涉及章节主题
- 0.2-0.4：弱相关，内容略微涉及相关领域
- 0.0-0.2：不相关，内容与章节主题无关

只需要返回数字分数，不需要解释：
"""
            
            response = await self._handle_ai_generation(prompt, user_id)
            
            # 提取分数
            try:
                score_match = re.search(r'([0-1](?:\.[0-9]+)?)', response.strip())
                if score_match:
                    score = float(score_match.group(1))
                    return max(0.0, min(1.0, score))  # 确保分数在0-1范围内
                else:
                    log_message(user_id, f"无法解析相关性分数: {response}", log_type="WARNING")
                    return 0.5  # 默认中等相关性
            except ValueError:
                log_message(user_id, f"相关性分数格式错误: {response}", log_type="WARNING")
                return 0.5
                
        except Exception as e:
            log_message(user_id, f"检查内容相关性失败: {e}", log_type="ERROR")
            return 0.5  # 出错时返回中等相关性
    
    async def _filter_high_quality_webpages(self, webpages: List[ClassifiedWebpage], 
                                          chapter_title: str, industry_name: str, 
                                          user_id: str, min_relevance: float = 0.6) -> List[ClassifiedWebpage]:
        """过滤高质量文章，基于内容相关性和质量指标"""
        try:
            high_quality_webpages = []
            
            log_message(user_id, f"开始质量检查，共 {len(webpages)} 篇文章，最低相关性阈值: {min_relevance}", log_type="INFO")
            
            for i, webpage in enumerate(webpages):
                try:
                    # 基础质量检查
                    if not webpage.content or len(webpage.content.strip()) < 100:
                        log_message(user_id, f"文章 {i+1} 内容过短，跳过", log_type="DEBUG")
                        continue
                    
                    if not webpage.title or len(webpage.title.strip()) < 5:
                        log_message(user_id, f"文章 {i+1} 标题过短，跳过", log_type="DEBUG")
                        continue
                    
                    # 检查内容相关性
                    relevance_score = await self._check_content_relevance(
                        webpage, chapter_title, industry_name, user_id
                    )
                    
                    log_message(user_id, f"文章 {i+1} 相关性分数: {relevance_score:.2f}", log_type="DEBUG")
                    
                    # 根据相关性阈值过滤
                    if relevance_score >= min_relevance:
                        high_quality_webpages.append(webpage)
                        log_message(user_id, f"文章 {i+1} 通过质量检查 (相关性: {relevance_score:.2f})", log_type="DEBUG")
                    else:
                        log_message(user_id, f"文章 {i+1} 相关性不足 (分数: {relevance_score:.2f} < {min_relevance})", log_type="DEBUG")
                        
                except Exception as e:
                    log_message(user_id, f"检查文章 {i+1} 质量时出错: {e}", log_type="ERROR")
                    continue
            
            log_message(user_id, f"质量检查完成，{len(webpages)} 篇文章中有 {len(high_quality_webpages)} 篇通过检查", log_type="INFO")
            return high_quality_webpages
            
        except Exception as e:
            log_message(user_id, f"文章质量过滤失败: {e}", log_type="ERROR")
            # 出错时返回原始列表的前5篇，避免完全失败
            return webpages[:5]
    
    def _format_search_results_for_prompt(self, search_results: List[Dict]) -> str:
        """格式化搜索结果用于AI提示词"""
        if not search_results:
            return "暂无相关搜索结果"
        
        formatted_results = []
        for i, result in enumerate(search_results, 1):
            title = result.get('title', '未知标题')
            content = result.get('content', result.get('description', '无内容'))
            url = result.get('url', '')
            
            formatted_results.append(f"""
        **文章{i}：{title}**
        来源：{url}
        内容摘要：{content[:1000]}...
        """)
        
        return "\n".join(formatted_results)
    
    def _format_content_for_prompt(self, items: List, item_type: str = "webpage") -> str:
        """统一的内容格式化方法，替换重复的格式化函数"""
        formatted_content = []
        for i, item in enumerate(items, 1):
            if item_type == "webpage":
                title = item.title
                content = item.content
                tags = f"   标签：{', '.join(item.category_tags)}\n" if hasattr(item, 'category_tags') else ""
            else:  # search result
                title = item.get('title', '未知标题')
                content = item.get('content', '')
                tags = ""
            
            content_preview = content[:800] + "..." if len(content) > 800 else content
            formatted_content.append(
                f"{i}. 标题：{title}\n"
                f"{tags}"
                f"   内容：{content_preview}\n"
            )
        return "\n".join(formatted_content)

    def _format_industry_data_for_prompt(self, industry_data: Dict[str, Any]) -> str:
        """格式化产业数据用于AI提示词 - 过滤掉技术内部数据"""
        # 定义需要过滤掉的技术内部字段
        filtered_keys = {
            'nodes', 'relations', 'node_level', 'parent_id', 'id',
            'status', 'created_at', 'updated_at', 'chain_name'
        }

        formatted_data = []
        for key, value in industry_data.items():
            # 跳过技术内部数据和空��
            if key in filtered_keys or not value or not str(value).strip():
                continue

            # 只保留用户友好的描述性信息
            if key in ['name', 'industry_name', 'description']:
                formatted_data.append(f"- {key}: {value}")
        return "\n".join(formatted_data)

    def _generate_fallback_report(self, industry_name: str, report_type: str) -> str:
        """生成备用报告（当模板文件不存在时）"""
        current_time = datetime.now().strftime("%Y年%m月%d日")

        if report_type == "simple":
            return f"""# {industry_name}产业链分析报告（精简版）

**报告生成时间：** {current_time}
**分析机构：** 智能产业分析平台

---

## 执行摘要

本报告对{industry_name}产业链进行了全面分析，涵盖产业概览、产业链结构、市场技术分析、竞争环境、风险机遇等内容。

---

## 第一章 产业概览

### 1.1 产业定义

{industry_name}是指...[待填充详细产业定义]

### 1.2 产业重要性

| 价值维度 | 描述 |
|---------|------|
| 经济价值 | [待分析填充] |
| 战略意义 | [待分析填充] |
| 技术影响 | [待分析填充] |

---

## 第二章 产业链结构

### 2.1 产业链架构

```mermaid
graph TB
    上游[上游：基础要素] --> 中游[中游：核心制造]
    中游 --> 下游[下游：应用服务]
```

### 2.2 上游分析

**关键要素：** [待分析填充]
**主要供应商：** [待分析填充]

### 2.3 中游分析

**核心环节：** [待分析填充]
**主要厂商：** [待分析填充]

### 2.4 下游分析

**主要应用：** [待分析填充]
**客户类型：** [待分析填充]

---

## 第三章 市场与技术分析

### 3.1 市场规模

[待分析填充市场规模数据]

### 3.2 核心技术

**关键技术：** [待分析填充]
**技术趋势：** [待分析填充]

---

## 第四章 竞争与政策环境

### 4.1 竞争格局

[待分析填充竞争格局]

### 4.2 政策环境

**支持政策：** [待分析填充]
**政策趋势：** [待分析填充]

---

## 第五章 风险机遇与投资分析

### 5.1 主要风险

[待分析填充风险]

### 5.2 发展机遇

[待分析填充机遇]

### 5.3 投资建议

[待分析填充投资建议]

---

## 结论与建议

### 核心结论

[待分析填充结论]

---

**报告说明：** 本报告使用了备用模板生成。部分内容待后续填充完善。
"""
        else:  # detailed
            return f"""# {industry_name}产业链深度分析报告

**报告生成时间：** {current_time}
**分析机构：** 智能产业分析平台

---

## 执行摘要

### 核心发现

[待填充核心发现]

### 关键数据指标

| 指标名称 | 数值 | 同比变化 |
|---------|------|---------|
| 市场规模 | [待填充] | [待填充] |
| 增长率 | [待填充] | [待填充] |

---

## 第一章 产业概览与定义

### 1.1 产业定义与边界

#### 1.1.1 标准定义

[待填充：{industry_name}的官方定义和标准]

#### 1.1.2 产业范围

[待填充：核心产业、关联产业和边缘产业]

#### 1.1.3 产业特征

| 特征维度 | 描述 |
|---------|------|
| 技术密集度 | [待填充] |
| 资本密集度 | [待填充] |
| 人才密集度 | [待填充] |

### 1.2 产业发展历程

[待填充发展历程和里程碑]

### 1.3 产业重要性评估

[待填充：经济价值、战略价值、社会价值]

---

## 第二章 产业链结构深度分析

### 2.1 产业链整体架构

```mermaid
graph TB
    subgraph 上游
        A[原材料供应]
        B[核心技术]
        C[基础设施]
    end
    subgraph 中游
        D[研发设计]
        E[生产制造]
    end
    subgraph 下游
        G[终端应用]
        H[客户服务]
    end
    A --> D
    B --> D
    C --> D
    D --> E
    E --> G
```

### 2.2 上游分析：基础要素层

[待填充上游分析]

### 2.3 中游分析：核心制造层

[待填充中游分析]

### 2.4 下游分析：应用服务层

[待填充下游分析]

---

## 第三章 市场规模与增长分析

### 3.1 市场规模现状

[待填充市场规模数据]

### 3.2 市场预测与展望

[待填充市场预测]

### 3.3 区域市场分析

[待填充区域市场分析]

---

## 第四章 技术发展与创新分析

### 4.1 技术现状评估

[待填充技术现状]

### 4.2 创新生态分析

[待填充创新生态]

### 4.3 技术发展趋势

[待填充技术趋势]

---

## 第五章 竞争格局与企业分析

### 5.1 整体竞争格局

[待填充竞争格局]

### 5.2 重点企业深度分析

[待填充企业分析]

### 5.3 竞争策略分析

[待填充竞争策略]

---

## 第六章 政策环境与影响分析

### 6.1 政策环境概述

[待填充政策环境]

### 6.2 政策影响评估

[待填充政策影响]

### 6.3 政策趋势预判

[待填充政策趋势]

---

## 第七章 风险评估与挑战分析

### 7.1 风险识别与分类

[待填充风险识别]

### 7.2 重点风险深度分析

[待填充风险分析]

### 7.3 风险管控建议

[待填充风险管控]

---

## 第八章 发展机遇与前景展望

### 8.1 发展机遇识别

[待填充发展机遇]

### 8.2 发展前景展望

[待填充发展前景]

### 8.3 发展路径建议

[待填充发展路径]

---

## 第九章 投资分析与建议

### 9.1 投资价值评估

[待填充投资价值]

### 9.2 投资机会识别

[待填充投资机会]

### 9.3 投资建议与策略

[待填充投资建议]

---

## 结论与建议

### 核心结论

[待填充核心结论]

### 行动建议

[待填充行动建议]

---

**报告说明：** 本报告使用了备用模板生成。部分内容待后续填充完善。
"""

    async def _handle_ai_generation(self, prompt: str, user_id: str = None, fallback_content: str = "") -> str:
        """统一的AI内容生成处理方法"""
        try:
            if self.use_batching and hasattr(self.ai_client, 'generate_content_batch'):
                response = await self.ai_client.generate_content_batch([prompt])
                return response[0] if response else fallback_content
            else:
                response = await self.ai_client.generate_content(prompt)
                return response if response else fallback_content
        except Exception as e:
            if user_id:
                log_message(user_id, f"AI生成内容失败: {e}", log_type="ERROR")
            self.logger.error(f"AI生成内容失败: {e}")
            return fallback_content

    async def _fill_template_with_strategies(self, template_path: str, industry_data: Dict[str, Any],
                                           classified_webpages: List[Dict], report_type: str, user_id: str,
                                           cancel_flag: asyncio.Event = None) -> str:
        """使用三种策略填充模板"""
        # 检查模板文件是否存在
        if not os.path.exists(template_path):
            log_message(user_id, f"模板文件不存在: {template_path}", log_type="ERROR")
            industry_name = industry_data.get('name', industry_data.get('industry_name', '未知产业'))
            return self._generate_fallback_report(industry_name, report_type)

        chapter_titles = ReportConfig.get_chapters_by_template(report_type)

        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                filled_content = f.read()
        except Exception as e:
            log_message(user_id, f"读取模板文件失败: {e}", log_type="ERROR")
            industry_name = industry_data.get('name', industry_data.get('industry_name', '未知产业'))
            return self._generate_fallback_report(industry_name, report_type)
        
        # 首先替换时间占位符
        current_time = datetime.now()
        filled_content = filled_content.replace("[YYYY年MM月]", current_time.strftime("%Y年%m月%d日"))
        filled_content = filled_content.replace("[产业名称]", industry_data.get('name', '未知产业'))
        
        log_message(user_id, f"已替换基础占位符：时间和产业名称", log_type="INFO")
        
        for chapter_title in chapter_titles:
            try:
                # 检查是否已取消（每个章节前检查）
                if cancel_flag and cancel_flag.is_set():
                    log_message(user_id, f"章节填充被取消: {chapter_title}", log_type="INFO")
                    break
                    
                log_message(user_id, f"开始填充章节: {chapter_title}", log_type="INFO")
                
                log_message(user_id, f"开始填充章节: {chapter_title}", log_type="INFO")
                
                original_content = self._extract_chapter_content_from_template(template_path, chapter_title)
                
                filled_chapter = None
                
                # 策略1：分类文章匹配填充
                if classified_webpages:
                    filled_chapter = await self._strategy_1_classified_articles(
                        chapter_title, original_content, industry_data, 
                        classified_webpages, report_type, user_id  # 修复变量名
                    )
                
                # 策略2：Jina搜索填充
                if not filled_chapter:
                    filled_chapter = await self._strategy_2_jina_search(
                        chapter_title, original_content, industry_data, user_id, report_type
                    )
                
                # 策略3：AI自行分析填充
                if not filled_chapter:
                    filled_chapter = await self._strategy_3_ai_analysis(
                        chapter_title, original_content, industry_data, user_id, report_type
                    )
                
                # 替换章节内容
                if filled_chapter:
                    if original_content in filled_content:
                        filled_content = filled_content.replace(original_content, filled_chapter)
                        log_message(user_id, f"章节填充完成: {chapter_title}", log_type="INFO")
                    else:
                        log_message(user_id, f"警告：章节 '{chapter_title}' 的原始内容在模板中未找到，无法替换", log_type="WARNING")
                        log_message(user_id, f"原始内容长度: {len(original_content)}, 模板长度: {len(filled_content)}", log_type="DEBUG")
                else:
                    log_message(user_id, f"警告：章节 '{chapter_title}' 填充内容为空", log_type="WARNING")
                
            except Exception as e:
                log_message(user_id, f"章节填充失败 {chapter_title}: {e}", log_type="ERROR")
                continue
        
        return filled_content
    
    async def generate_report_with_webpages(self, industry_data: Dict[str, Any], 
                                          industry_name: str, user_id: str,
                                          collected_articles: List[Dict[str, str]] = None,
                                          cancel_flag: asyncio.Event = None) -> Dict[str, str]:
        """使用三种策略生成报告的主入口方法"""
        try:
            # 检查是否已取消
            if cancel_flag and cancel_flag.is_set():
                log_message(user_id, f"报告生成已被取消: {industry_name}", log_type="INFO")
                return {"detailed_report": "", "simple_report": ""}
            
            log_message(user_id, f"开始为产业 '{industry_name}' 生成报告（使用三种填充策略）", log_type="INFO")
            
            # 获取分类网页
            classified_webpages = []
            try:
                # 优先使用收集的文章数据
                if collected_articles and len(collected_articles) > 0:
                    log_message(user_id, f"使用产业链搜索收集的 {len(collected_articles)} 篇文章", log_type="INFO")
                    classified_webpages = await self.webpage_service.get_classified_webpages(
                        industry_name, limit=100, live_webpages=collected_articles
                    )
                else:
                    # 备用方案：从数据库获取
                    log_message(user_id, "未找到收集的文章，尝试从数据库获取", log_type="INFO")
                    classified_webpages = await self.webpage_service.get_classified_webpages(
                        industry_name, limit=100
                    )
                
                log_message(user_id, f"获取到 {len(classified_webpages)} 个分类网页", log_type="INFO")
            except Exception as e:
                log_message(user_id, f"获取分类网页失败: {e}，将使用搜索和AI分析策略", log_type="WARNING")
            
            # 检查是否已取消
            if cancel_flag and cancel_flag.is_set():
                log_message(user_id, f"报告生成在获取分类网页后被取消: {industry_name}", log_type="INFO")
                return {"detailed_report": "", "simple_report": ""}
            
            # 生成详细版报告
            log_message(user_id, "开始生成详细版报告", log_type="INFO")
            detailed_report = await self._fill_template_with_strategies(
                self.detailed_template_path, industry_data, classified_webpages, "detailed", user_id, cancel_flag
            )
            
            # 检查是否已取消
            if cancel_flag and cancel_flag.is_set():
                log_message(user_id, f"报告生成在详细版完成后被取消: {industry_name}", log_type="INFO")
                return {"detailed_report": detailed_report, "simple_report": ""}
            
            # 生成精简版报告
            log_message(user_id, "开始生成精简版报告", log_type="INFO")
            simple_report = await self._fill_template_with_strategies(
                self.simple_template_path, industry_data, classified_webpages, "simple", user_id, cancel_flag
            )
            
            log_message(user_id, f"报告生成完成 - 详细版: {len(detailed_report)} 字符, 精简版: {len(simple_report)} 字符", log_type="INFO")
            
            return {
                "detailed_report": detailed_report,
                "simple_report": simple_report
            }
            
        except Exception as e:
            log_message(user_id, f"生成报告失败: {e}", log_type="ERROR")
            self.logger.error(f"生成报告失败: {e}")

            industry_display_name = industry_data.get('name') or industry_data.get('industry_name', '未知产业')
            return {
                "detailed_report": f"# {industry_display_name}产业链分析报告\n\n报告生成失败，请稍后重试。",
                "simple_report": f"# {industry_display_name}产业链分析报告（精简版）\n\n报告生成失败，请稍后重试。"
            }


