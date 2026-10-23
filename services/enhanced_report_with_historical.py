"""
增强报告生成器 - 集成历史报告分析
临时集成脚本，用于在报告生成过程中集成22年历史报告分析
"""

import os
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime

from .optimized_template_filler import OptimizedTemplateFiller
from .historical_report_analyzer import analyze_and_integrate_historical_data
from .crawler_service import log_message
from utils.logger import log_webpage_report_progress


class EnhancedReportWithHistorical:
    def __init__(self):
        self.template_filler = OptimizedTemplateFiller()
        
    async def generate_enhanced_report(self, industry_data: Dict[str, Any], 
                                     industry_name: str,
                                     user_id: str = None,
                                     collected_articles: List[Dict] = None,
                                     historical_config: Dict[str, Any] = None,
                                     cancel_flag: asyncio.Event = None) -> Dict[str, Any]:
        """
        生成增强版报告，集成历史报告分析
        
        Args:
            industry_data: 产业数据
            industry_name: 产业名称
            user_id: 用户ID
            collected_articles: 收集的文章
            historical_config: 历史报告配置 {
                "report_path": "历史报告路径",
                "reference_files": ["参考文件路径列表"],
                "enable": True/False
            }
            cancel_flag: 取消标志
        """
        try:
            log_message(user_id, f"开始生成{industry_name}增强版报告（含历史分析）", log_type="INFO")
            log_webpage_report_progress(user_id, f"启动{industry_name}增强版报告生成", "INFO")
            
            # 检查取消标志
            if cancel_flag and cancel_flag.is_set():
                return self._create_cancelled_response()
            
            # 第一步：分析历史报告（如果配置了）
            historical_data = None
            if historical_config and historical_config.get("enable", False):
                log_webpage_report_progress(user_id, f"开始分析{industry_name}历史报告", "INFO")
                historical_data = await self._analyze_historical_data(
                    historical_config, industry_name, user_id, cancel_flag
                )
                
                if cancel_flag and cancel_flag.is_set():
                    return self._create_cancelled_response()
            
            # 第二步：生成基础报告
            log_webpage_report_progress(user_id, f"生成{industry_name}基础报告", "INFO")
            base_reports = await self.template_filler.generate_report_with_webpages(
                industry_data, industry_name, user_id, collected_articles or [], cancel_flag
            )
            
            if cancel_flag and cancel_flag.is_set():
                return self._create_cancelled_response()
            
            # 第三步：集成历史数据生成增强报告
            enhanced_reports = {}
            if historical_data and historical_data.get("available"):
                log_webpage_report_progress(user_id, f"集成历史数据生成{industry_name}增强报告", "INFO")
                enhanced_reports = await self._generate_enhanced_reports(
                    base_reports, historical_data, industry_name, user_id, cancel_flag
                )
            else:
                log_webpage_report_progress(user_id, f"历史数据不可用，使用基础报告", "INFO")
                enhanced_reports = base_reports
            
            # 第四步：生成历史数据分析摘要
            historical_summary = None
            if historical_data:
                historical_summary = await self._generate_historical_summary(
                    historical_data, industry_name, user_id
                )
            
            result = {
                "success": True,
                "industry_name": industry_name,
                "generation_timestamp": datetime.now().isoformat(),
                "base_reports": base_reports,
                "enhanced_reports": enhanced_reports,
                "historical_analysis": historical_data,
                "historical_summary": historical_summary,
                "integration_status": "completed" if historical_data else "no_historical_data"
            }
            
            log_message(user_id, f"{industry_name}增强版报告生成完成", log_type="INFO")
            log_webpage_report_progress(user_id, f"{industry_name}增强版报告生成完成", "SUCCESS")
            
            return result
            
        except Exception as e:
            log_message(user_id, f"增强版报告生成失败: {e}", log_type="ERROR")
            log_webpage_report_progress(user_id, f"{industry_name}增强版报告生成失败: {e}", "ERROR")
            return {
                "success": False,
                "error": str(e),
                "industry_name": industry_name
            }
    
    async def _analyze_historical_data(self, historical_config: Dict[str, Any],
                                     industry_name: str, user_id: str,
                                     cancel_flag: asyncio.Event) -> Optional[Dict[str, Any]]:
        """分析历史数据"""
        try:
            report_path = historical_config.get("report_path")
            reference_files = historical_config.get("reference_files", [])
            
            if not report_path or not os.path.exists(report_path):
                log_message(user_id, f"历史报告路径无效: {report_path}", log_type="WARNING")
                return None
            
            # 检查参考文件
            valid_reference_files = [f for f in reference_files if os.path.exists(f)]
            if len(valid_reference_files) != len(reference_files):
                log_message(user_id, f"部分参考文件不存在，有效文件数: {len(valid_reference_files)}", log_type="WARNING")
            
            # 分析历史数据
            historical_data = await analyze_and_integrate_historical_data(
                report_path, valid_reference_files, industry_name, user_id
            )
            
            return historical_data
            
        except Exception as e:
            log_message(user_id, f"历史数据分析失败: {e}", log_type="ERROR")
            return None
    
    async def _generate_enhanced_reports(self, base_reports: Dict[str, str],
                                       historical_data: Dict[str, Any],
                                       industry_name: str, user_id: str,
                                       cancel_flag: asyncio.Event) -> Dict[str, str]:
        """生成增强版报告"""
        enhanced_reports = {}
        
        try:
            # 为每个基础报告生成增强版本
            for report_type, base_content in base_reports.items():
                if cancel_flag and cancel_flag.is_set():
                    break
                    
                log_webpage_report_progress(user_id, f"增强{report_type}报告", "INFO")
                
                enhanced_content = await self._enhance_single_report(
                    base_content, historical_data, report_type, industry_name, user_id
                )
                
                enhanced_reports[f"enhanced_{report_type}"] = enhanced_content
            
            return enhanced_reports
            
        except Exception as e:
            log_message(user_id, f"生成增强报告失败: {e}", log_type="ERROR")
            return base_reports  # 返回基础报告作为后备
    
    async def _enhance_single_report(self, base_content: str, 
                                   historical_data: Dict[str, Any],
                                   report_type: str, industry_name: str, 
                                   user_id: str) -> str:
        """增强单个报告"""
        try:
            # 提取历史数据中的关键信息
            key_data = historical_data.get("key_data", {})
            metrics = historical_data.get("metrics", {})
            quality_score = historical_data.get("quality_score", 0)
            recommendations = historical_data.get("recommendations", [])
            
            enhancement_prompt = f"""
请基于以下历史数据分析结果，增强{industry_name}产业的{report_type}报告：

原始报告内容：
{base_content}

历史数据分析结果：
- 数据质量评分: {quality_score}/10
- 关键历史数据: {key_data}
- 重要指标: {metrics}
- 使用建议: {recommendations}

请按以下要求增强报告：
1. 如果历史数据质量高（>7分），重点集成历史趋势分析
2. 如果历史数据质量中等（5-7分），谨慎引用，并标注数据来源年份
3. 如果历史数据质量低（<5分），仅作为背景参考，重点使用最新数据
4. 在相关章节中加入"历史对比分析"
5. 突出显示数据的时间跨度和发展趋势
6. 保持报告的整体结构和逻辑性

增强后的报告应该：
- 更加全面和深入
- 包含历史发展脉络
- 数据更加丰富
- 分析更加客观

请返回完整的增强版报告内容。
"""
            
            enhanced_content = await self.template_filler.llm_service.generate_response(
                enhancement_prompt, user_id
            )
            
            return enhanced_content
            
        except Exception as e:
            log_message(user_id, f"增强{report_type}报告失败: {e}", log_type="ERROR")
            return base_content  # 返回原始内容作为后备
    
    async def _generate_historical_summary(self, historical_data: Dict[str, Any],
                                         industry_name: str, user_id: str) -> str:
        """生成历史数据分析摘要"""
        try:
            quality_score = historical_data.get("quality_score", 0)
            recommendations = historical_data.get("recommendations", [])
            key_data = historical_data.get("key_data", {})
            
            summary_prompt = f"""
基于对{industry_name}产业历史报告的分析，生成一份简洁的分析摘要：

分析结果：
- 数据质量评分: {quality_score}/10
- 关键发现: {key_data}
- 使用建议: {recommendations}

请生成一份包含以下内容的摘要：
1. 历史报告质量评估
2. 主要数据发现
3. 数据可信度分析
4. 使用建议
5. 对当前报告的价值评估

摘要应该简洁明了，便于决策参考。
"""
            
            summary = await self.template_filler.llm_service.generate_response(
                summary_prompt, user_id
            )
            
            return summary
            
        except Exception as e:
            log_message(user_id, f"生成历史数据摘要失败: {e}", log_type="ERROR")
            return "历史数据摘要生成失败"
    
    def _create_cancelled_response(self) -> Dict[str, Any]:
        """创建取消响应"""
        return {
            "success": False,
            "cancelled": True,
            "message": "增强版报告生成已被取消"
        }
    
    async def save_enhanced_reports(self, enhanced_result: Dict[str, Any], 
                                  user_id: str = None) -> Dict[str, str]:
        """保存增强版报告"""
        try:
            if not enhanced_result.get("success"):
                return {}
            
            industry_name = enhanced_result.get("industry_name", "未知产业")
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # 创建报告目录
            report_dir = f"/root/mix_project/filled_reports/enhanced_{industry_name}_{timestamp}"
            os.makedirs(report_dir, exist_ok=True)
            
            saved_paths = {}
            
            # 保存增强版报告
            enhanced_reports = enhanced_result.get("enhanced_reports", {})
            for report_type, content in enhanced_reports.items():
                file_path = os.path.join(report_dir, f"{report_type}_{timestamp}.md")
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                saved_paths[report_type] = file_path
                log_message(user_id, f"{report_type}已保存: {file_path}", log_type="INFO")
            
            # 保存历史数据分析摘要
            historical_summary = enhanced_result.get("historical_summary")
            if historical_summary:
                summary_path = os.path.join(report_dir, f"历史数据分析摘要_{timestamp}.md")
                with open(summary_path, 'w', encoding='utf-8') as f:
                    f.write(historical_summary)
                saved_paths["historical_summary"] = summary_path
                log_message(user_id, f"历史数据分析摘要已保存: {summary_path}", log_type="INFO")
            
            # 保存完整分析结果（JSON格式）
            result_path = os.path.join(report_dir, f"完整分析结果_{timestamp}.json")
            import json
            with open(result_path, 'w', encoding='utf-8') as f:
                json.dump(enhanced_result, f, ensure_ascii=False, indent=2)
            saved_paths["full_analysis"] = result_path
            
            log_message(user_id, f"增强版报告已保存到: {report_dir}", log_type="INFO")
            return saved_paths
            
        except Exception as e:
            log_message(user_id, f"保存增强版报告失败: {e}", log_type="ERROR")
            return {}


# 便捷函数 - 用于快速集成到现有流程
async def generate_report_with_historical_analysis(industry_data: Dict[str, Any],
                                                 industry_name: str,
                                                 collected_articles: List[Dict],
                                                 historical_report_path: str,
                                                 reference_files: List[str],
                                                 user_id: str = None,
                                                 cancel_flag: asyncio.Event = None) -> Dict[str, Any]:
    """
    便捷函数：生成包含历史分析的增强报告
    
    Args:
        industry_data: 产业数据
        industry_name: 产业名称  
        collected_articles: 收集的文章
        historical_report_path: 22年报告路径
        reference_files: 参考文件路径列表
        user_id: 用户ID
        cancel_flag: 取消标志
    """
    generator = EnhancedReportWithHistorical()
    
    historical_config = {
        "enable": True,
        "report_path": historical_report_path,
        "reference_files": reference_files
    }
    
    # 生成增强报告
    result = await generator.generate_enhanced_report(
        industry_data, industry_name, user_id, collected_articles,
        historical_config, cancel_flag
    )
    
    # 保存报告
    if result.get("success"):
        saved_paths = await generator.save_enhanced_reports(result, user_id)
        result["saved_paths"] = saved_paths
    
    return result


if __name__ == "__main__":
    # 测试脚本
    async def test_enhanced_generator():
        # 示例配置
        industry_data = {"name": "新能源汽车", "industry_info": {"name": "新能源汽车"}}
        collected_articles = []
        historical_report_path = "/path/to/2022_新能源汽车报告.md"
        reference_files = [
            "/path/to/reference1.pdf",
            "/path/to/reference2.xlsx"
        ]
        
        result = await generate_report_with_historical_analysis(
            industry_data, "新能源汽车", collected_articles,
            historical_report_path, reference_files, "test_user"
        )
        
        print("增强报告生成结果:", result.get("success"))
        print("保存路径:", result.get("saved_paths", {}))
    
    # asyncio.run(test_enhanced_generator()) 