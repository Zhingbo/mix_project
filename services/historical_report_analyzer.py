"""
历史报告分析器 - 临时脚本
用于分析22年的报告和参考文件，提取有用数据用于当前报告生成
使用完毕后可以方便删除
"""

import os
import json
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime

from .crawler_service import log_message
from .enhanced_ai_client import UnifiedAIClient


class HistoricalReportAnalyzer:
    def __init__(self):
        self.llm_service = UnifiedAIClient()
        
    async def analyze_historical_data(self, historical_report_path: str, 
                                    reference_files: List[str], 
                                    industry_name: str,
                                    user_id: str = None) -> Dict[str, Any]:
        """
        分析历史报告和参考文件
        
        Args:
            historical_report_path: 22年报告文件路径
            reference_files: 参考文件路径列表
            industry_name: 产业名称
            user_id: 用户ID
            
        Returns:
            包含分析结果的字典
        """
        try:
            log_message(user_id, f"开始分析{industry_name}的历史报告和参考文件", log_type="INFO")
            
            # 读取历史报告
            historical_content = await self._read_file(historical_report_path)
            if not historical_content:
                log_message(user_id, f"无法读取历史报告: {historical_report_path}", log_type="ERROR")
                return {"success": False, "message": "无法读取历史报告"}
            
            # 读取参考文件
            reference_contents = []
            for ref_file in reference_files:
                content = await self._read_file(ref_file)
                if content:
                    reference_contents.append({
                        "file_path": ref_file,
                        "content": content,
                        "file_name": os.path.basename(ref_file)
                    })
            
            log_message(user_id, f"成功读取历史报告和{len(reference_contents)}个参考文件", log_type="INFO")
            
            # 分析报告质量和合理性
            quality_analysis = await self._analyze_report_quality(
                historical_content, reference_contents, industry_name, user_id
            )
            
            # 提取有用数据
            useful_data = await self._extract_useful_data(
                historical_content, reference_contents, industry_name, user_id
            )
            
            # 生成数据验证报告
            validation_report = await self._validate_data_consistency(
                historical_content, reference_contents, industry_name, user_id
            )
            
            result = {
                "success": True,
                "industry_name": industry_name,
                "analysis_timestamp": datetime.now().isoformat(),
                "historical_report_path": historical_report_path,
                "reference_files_count": len(reference_contents),
                "quality_analysis": quality_analysis,
                "useful_data": useful_data,
                "validation_report": validation_report,
                "extracted_metrics": self._extract_key_metrics(useful_data),
                "recommendations": self._generate_recommendations(quality_analysis, useful_data)
            }
            
            # 保存分析结果
            await self._save_analysis_result(result, industry_name, user_id)
            
            log_message(user_id, f"{industry_name}历史报告分析完成", log_type="INFO")
            return result
            
        except Exception as e:
            log_message(user_id, f"历史报告分析失败: {e}", log_type="ERROR")
            return {"success": False, "message": f"分析失败: {e}"}
    
    async def _read_file(self, file_path: str) -> Optional[str]:
        """读取文件内容"""
        try:
            if not os.path.exists(file_path):
                return None
                
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"读取文件失败 {file_path}: {e}")
            return None
    
    async def _analyze_report_quality(self, report_content: str, 
                                    reference_contents: List[Dict], 
                                    industry_name: str, user_id: str) -> Dict[str, Any]:
        """分析报告质量和合理性"""
        try:
            # 构建分析提示
            reference_summary = "\n\n".join([
                f"参考文件 {ref['file_name']}:\n{ref['content'][:2000]}..." 
                for ref in reference_contents
            ])
            
            prompt = f"""
请分析以下{industry_name}产业的历史报告质量和合理性：

历史报告内容：
{report_content[:5000]}...

参考文件内容：
{reference_summary}

请从以下几个维度进行分析：
1. 数据准确性：报告中的数据是否与参考文件一致？
2. 逻辑合理性：报告的分析逻辑是否合理？
3. 信息完整性：报告是否涵盖了产业的关键方面？
4. 数据时效性：报告中的数据是否符合22年的时间背景？
5. 参考依据：报告的结论是否有充分的参考依据支撑？

请以JSON格式返回分析结果：
{{
    "overall_score": "整体评分(1-10)",
    "data_accuracy": {{"score": "数据准确性评分", "issues": ["发现的问题"]}},
    "logic_reasonableness": {{"score": "逻辑合理性评分", "issues": ["发现的问题"]}},
    "information_completeness": {{"score": "信息完整性评分", "missing_aspects": ["缺失的方面"]}},
    "data_timeliness": {{"score": "数据时效性评分", "outdated_info": ["过时的信息"]}},
    "reference_support": {{"score": "参考依据评分", "weak_claims": ["缺乏依据的观点"]}},
    "strengths": ["报告的优点"],
    "weaknesses": ["报告的缺点"],
    "improvement_suggestions": ["改进建议"]
}}
"""
            
            response = await self.llm_service.generate_content(prompt)
            
            # 尝试解析JSON响应
            try:
                return json.loads(response)
            except json.JSONDecodeError:
                # 如果JSON解析失败，返回原始响应
                return {"raw_analysis": response, "parse_error": True}
                
        except Exception as e:
            return {"error": f"质量分析失败: {e}"}
    
    async def _extract_useful_data(self, report_content: str, 
                                 reference_contents: List[Dict], 
                                 industry_name: str, user_id: str) -> Dict[str, Any]:
        """提取有用数据"""
        try:
            reference_summary = "\n\n".join([
                f"参考文件 {ref['file_name']}:\n{ref['content'][:2000]}..." 
                for ref in reference_contents
            ])
            
            prompt = f"""
从以下{industry_name}产业的历史报告和参考文件中提取对当前报告生成有用的数据：

历史报告：
{report_content[:5000]}...

参考文件：
{reference_summary}

请提取以下类型的有用数据：
1. 关键统计数据（市场规模、增长率、占比等）
2. 重要企业信息（龙头企业、市场份额等）
3. 技术发展趋势
4. 政策影响分析
5. 产业链结构信息
6. 风险因素识别
7. 发展机遇分析

请以JSON格式返回：
{{
    "key_statistics": {{
        "market_size": "市场规模相关数据",
        "growth_rate": "增长率数据",
        "market_share": "市场份额数据"
    }},
    "important_companies": [
        {{"name": "企业名称", "role": "角色定位", "data": "相关数据"}}
    ],
    "technology_trends": ["技术发展趋势"],
    "policy_impacts": ["政策影响分析"],
    "industry_chain": {{
        "upstream": ["上游环节"],
        "midstream": ["中游环节"],
        "downstream": ["下游环节"]
    }},
    "risk_factors": ["风险因素"],
    "opportunities": ["发展机遇"],
    "data_sources": ["数据来源说明"],
    "reliability_score": "数据可靠性评分(1-10)"
}}
"""
            
            response = await self.llm_service.generate_content(prompt)
            
            try:
                return json.loads(response)
            except json.JSONDecodeError:
                return {"raw_extraction": response, "parse_error": True}
                
        except Exception as e:
            return {"error": f"数据提取失败: {e}"}
    
    async def _validate_data_consistency(self, report_content: str, 
                                       reference_contents: List[Dict], 
                                       industry_name: str, user_id: str) -> Dict[str, Any]:
        """验证数据一致性"""
        try:
            prompt = f"""
请验证{industry_name}产业历史报告与参考文件之间的数据一致性：

历史报告（前3000字符）：
{report_content[:3000]}

参考文件摘要：
{chr(10).join([f"{ref['file_name']}: {ref['content'][:1000]}" for ref in reference_contents])}

请检查：
1. 数值数据的一致性
2. 时间序列的连贯性
3. 结论与数据的匹配度
4. 不同来源数据的冲突

以JSON格式返回验证结果：
{{
    "consistency_score": "一致性评分(1-10)",
    "data_conflicts": ["发现的数据冲突"],
    "timeline_issues": ["时间序列问题"],
    "conclusion_mismatches": ["结论与数据不匹配的地方"],
    "reliable_data_points": ["可靠的数据点"],
    "questionable_data_points": ["存疑的数据点"],
    "validation_summary": "验证总结"
}}
"""
            
            response = await self.llm_service.generate_content(prompt)
            
            try:
                return json.loads(response)
            except json.JSONDecodeError:
                return {"raw_validation": response, "parse_error": True}
                
        except Exception as e:
            return {"error": f"数据验证失败: {e}"}
    
    def _extract_key_metrics(self, useful_data: Dict[str, Any]) -> Dict[str, Any]:
        """提取关键指标"""
        if useful_data.get("parse_error") or useful_data.get("error"):
            return {"error": "无法提取关键指标"}
        
        key_metrics = {}
        
        # 提取统计数据
        if "key_statistics" in useful_data:
            key_metrics["statistics"] = useful_data["key_statistics"]
        
        # 提取企业数据
        if "important_companies" in useful_data:
            key_metrics["top_companies"] = useful_data["important_companies"][:5]  # 取前5家
        
        # 提取增长趋势
        if "technology_trends" in useful_data:
            key_metrics["trends"] = useful_data["technology_trends"]
        
        return key_metrics
    
    def _generate_recommendations(self, quality_analysis: Dict[str, Any], 
                                useful_data: Dict[str, Any]) -> List[str]:
        """生成使用建议"""
        recommendations = []
        
        # 基于质量分析的建议
        if not quality_analysis.get("parse_error") and not quality_analysis.get("error"):
            overall_score = quality_analysis.get("overall_score", "0")
            try:
                score = float(str(overall_score).replace("分", ""))
                if score >= 8:
                    recommendations.append("历史报告质量较高，可以作为重要参考")
                elif score >= 6:
                    recommendations.append("历史报告质量中等，建议谨慎使用其中的数据")
                else:
                    recommendations.append("历史报告质量较低，建议仅作为辅助参考")
            except:
                recommendations.append("建议人工审核历史报告质量")
        
        # 基于数据可靠性的建议
        if not useful_data.get("parse_error") and not useful_data.get("error"):
            reliability = useful_data.get("reliability_score", "0")
            try:
                score = float(str(reliability).replace("分", ""))
                if score >= 8:
                    recommendations.append("提取的数据可靠性高，建议在新报告中重点使用")
                elif score >= 6:
                    recommendations.append("提取的数据可靠性中等，建议结合其他数据源验证")
                else:
                    recommendations.append("提取的数据可靠性较低，建议仅作为参考")
            except:
                recommendations.append("建议人工验证提取数据的可靠性")
        
        if not recommendations:
            recommendations.append("建议结合当前市场情况，谨慎使用历史数据")
        
        return recommendations
    
    async def _save_analysis_result(self, result: Dict[str, Any], 
                                  industry_name: str, user_id: str):
        """保存分析结果"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            result_dir = "/root/mix_project/historical_analysis_results"
            os.makedirs(result_dir, exist_ok=True)
            
            result_file = os.path.join(result_dir, f"{industry_name}_历史报告分析_{timestamp}.json")
            
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            log_message(user_id, f"历史报告分析结果已保存: {result_file}", log_type="INFO")
            
        except Exception as e:
            log_message(user_id, f"保存分析结果失败: {e}", log_type="ERROR")
    
    def get_integration_data(self, analysis_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        获取可集成到报告生成中的数据
        这个方法返回格式化后的数据，可以直接用于报告生成
        """
        if not analysis_result.get("success"):
            return {"available": False, "reason": analysis_result.get("message", "分析失败")}
        
        integration_data = {
            "available": True,
            "source": "historical_analysis",
            "timestamp": analysis_result.get("analysis_timestamp"),
            "quality_score": self._extract_quality_score(analysis_result.get("quality_analysis", {})),
            "key_data": analysis_result.get("useful_data", {}),
            "metrics": analysis_result.get("extracted_metrics", {}),
            "recommendations": analysis_result.get("recommendations", []),
            "validation": analysis_result.get("validation_report", {})
        }
        
        return integration_data
    
    def _extract_quality_score(self, quality_analysis: Dict[str, Any]) -> float:
        """提取质量评分"""
        try:
            overall_score = quality_analysis.get("overall_score", "0")
            return float(str(overall_score).replace("分", ""))
        except:
            return 0.0


# 集成函数 - 用于在报告生成过程中调用
async def analyze_and_integrate_historical_data(historical_report_path: str,
                                              reference_files: List[str],
                                              industry_name: str,
                                              user_id: str = None) -> Dict[str, Any]:
    """
    分析历史数据并返回可集成的数据
    这是一个便捷函数，用于在报告生成过程中快速集成历史数据分析
    """
    analyzer = HistoricalReportAnalyzer()
    analysis_result = await analyzer.analyze_historical_data(
        historical_report_path, reference_files, industry_name, user_id
    )
    
    return analyzer.get_integration_data(analysis_result)


if __name__ == "__main__":
    # 测试脚本
    async def test_analyzer():
        analyzer = HistoricalReportAnalyzer()
        
        # 示例用法
        historical_report = "/path/to/2022_report.md"
        reference_files = [
            "/path/to/reference1.pdf",
            "/path/to/reference2.xlsx"
        ]
        
        result = await analyzer.analyze_historical_data(
            historical_report, reference_files, "新能源汽车", "test_user"
        )
        
        print("分析结果:", json.dumps(result, ensure_ascii=False, indent=2))
    
    # asyncio.run(test_analyzer()) 