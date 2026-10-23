import os
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime

from .optimized_template_filler import OptimizedTemplateFiller
from .enhanced_report_with_historical import EnhancedReportWithHistorical
from .crawler_service import log_message
from utils.logger import log_webpage_report_progress

class OptimizedReportOrchestrator:
    """优化的报告编排器 - 数据完整性优先"""
    
    def __init__(self):
        self.template_filler = OptimizedTemplateFiller()
        self.enhanced_reporter = EnhancedReportWithHistorical()
        
    def _auto_detect_historical_config(self, historical_config: Dict[str, Any], user_id: str, industry_name: str = None) -> Dict[str, Any]:
        """
        自动检测和验证历史配置
        
        Args:
            historical_config: 传入的历史配置
            user_id: 用户ID
            industry_name: 产业名称，用于匹配默认配置
            
        Returns:
            处理后的历史配置，包含检测结果
        """
        # 工业机器人默认历史配置
        if industry_name and ("工业机器人" in industry_name or "机器人" in industry_name):
            default_robot_config = {
                "enable": True,
                "report_path": "/root/mix_project/historical_data/工业机器人产业相关资料/联东产业研究院-工业机器人研究.pdf",
                "reference_files": [
                    "/root/mix_project/historical_data/工业机器人产业相关资料/2025_09_09_机器人（修改）-2022-4-9/机器人数据合集2023.xlsx",
                    "/root/mix_project/historical_data/工业机器人产业相关资料/2025_09_09_机器人（修改）-2022-4-9/机器人（修改）-2022-4-9.xlsx",
                    "/root/mix_project/historical_data/工业机器人产业相关资料/2025_09_09_机器人（修改）-2022-4-9/机器人产业机会和瓶颈分析-2024.xlsx",
                    "/root/mix_project/historical_data/工业机器人产业相关资料/2025_09_09_机器人（修改）-2022-4-9/机器人企业数据汇总-2022-4-1.xlsx",
                    "/root/mix_project/historical_data/工业机器人产业相关资料/2025_09_09_机器人（修改）-2022-4-9/2024年机器人产业新增目录企业初步名单.20241111.xlsx"
                ]
            }
            
            # 如果用户没有提供历史配置，使用默认的机器人配置
            if not historical_config:
                log_message(user_id, f"检测到{industry_name}产业，自动启用默认历史分析配置", log_type="INFO")
                historical_config = default_robot_config
            # 如果用户提供了配置但没有指定路径，使用默认路径
            elif not historical_config.get("report_path"):
                log_message(user_id, f"为{industry_name}产业补充默认历史报告路径", log_type="INFO")
                historical_config.update(default_robot_config)
        
        if not historical_config:
            log_message(user_id, "未提供历史配置，使用标准报告生成", log_type="INFO")
            return {"enable": False, "detected": False, "reason": "未提供历史配置"}
        
        # 检查是否明确禁用
        if historical_config.get("enable") is False:
            log_message(user_id, "历史分析已被明确禁用", log_type="INFO")
            return {"enable": False, "detected": False, "reason": "用户明确禁用"}
        
        # 自动检测历史报告文件
        report_path = historical_config.get("report_path")
        reference_files = historical_config.get("reference_files", [])
        
        detected_config = {
            "enable": False,
            "detected": True,
            "report_path": report_path,
            "reference_files": [],
            "valid_files": [],
            "invalid_files": [],
            "reason": ""
        }
        
        # 检查历史报告文件
        if report_path:
            if os.path.exists(report_path) and os.path.isfile(report_path):
                detected_config["valid_files"].append(report_path)
                log_message(user_id, f"检测到有效的历史报告文件: {report_path}", log_type="INFO")
            else:
                detected_config["invalid_files"].append(report_path)
                log_message(user_id, f"历史报告文件不存在或无效: {report_path}", log_type="WARNING")
        
        # 检查参考文件
        valid_reference_files = []
        for ref_file in reference_files:
            if os.path.exists(ref_file) and os.path.isfile(ref_file):
                valid_reference_files.append(ref_file)
                detected_config["valid_files"].append(ref_file)
                log_message(user_id, f"检测到有效的参考文件: {ref_file}", log_type="INFO")
            else:
                detected_config["invalid_files"].append(ref_file)
                log_message(user_id, f"参考文件不存在或无效: {ref_file}", log_type="WARNING")
        
        detected_config["reference_files"] = valid_reference_files
        
        # 决策逻辑：至少需要有历史报告文件才启用增强分析
        if report_path and os.path.exists(report_path):
            detected_config["enable"] = True
            detected_config["reason"] = f"检测到有效历史报告文件，启用增强分析。有效文件: {len(detected_config['valid_files'])}个"
            log_message(user_id, f"自动启用历史分析: {detected_config['reason']}", log_type="INFO")
        else:
            detected_config["reason"] = "未检测到有效的历史报告文件，使用标准分析"
            log_message(user_id, f"保持标准分析: {detected_config['reason']}", log_type="INFO")
        
        return detected_config
        
    async def generate_reports(self, industry_data: Dict[str, Any], user_id: str = None, 
                             cancel_flag: asyncio.Event = None, historical_config: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        生成完整的产业链分析报告
        
        Args:
            industry_data: 产业数据
            user_id: 用户ID
            cancel_flag: 取消标志
            historical_config: 历史报告配置 {
                "report_path": "历史报告文件路径",
                "reference_files": ["参考文件路径列表"],
                "enable": True/False/None  # None表示自动检测
            }
        """
        try:
            # 获取产业名称 - 修正数据结构访问
            industry_name = industry_data.get('industry_info', {}).get('name') or industry_data.get('name', '未知产业')
            log_message(user_id, f"开始生成{industry_name}产业链分析报告", log_type="INFO")
            log_webpage_report_progress(user_id, f"报告编排器开始处理{industry_name}产业链分析报告", "INFO")
            
            # 提取收集的文章数据
            collected_articles = industry_data.get('collected_articles', [])
            log_message(user_id, f"报告编排器接收到 {len(collected_articles)} 篇文章", log_type="INFO")
            
            standardized_industry_data = {
                **industry_data,
                'name': industry_name  # 确保有name字段供OptimizedTemplateFiller使用
            }
            
            # 检查是否已取消
            if cancel_flag and cancel_flag.is_set():
                log_message(user_id, f"报告编排被取消: {industry_name}", log_type="INFO")
                return {"reports": {}, "saved_paths": {}, "success": False, "message": "报告生成已被取消"}
            
            # 智能检测历史配置
            detected_config = self._auto_detect_historical_config(historical_config, user_id, industry_name)
            
            # 向用户报告检测结果
            log_webpage_report_progress(user_id, f"历史资料检测: {detected_config['reason']}", "INFO")
            
            # 判断是否使用增强版报告生成（含历史分析）
            if detected_config.get("enable", False):
                log_message(user_id, f"使用增强版报告生成器（含历史分析）: {industry_name}", log_type="INFO")
                log_webpage_report_progress(user_id, f"启动{industry_name}增强版报告生成（含历史分析）", "INFO")
                
                # 使用检测到的有效配置
                validated_config = {
                    "enable": True,
                    "report_path": detected_config["report_path"],
                    "reference_files": detected_config["reference_files"]
                }
                
                # 使用增强版报告生成器
                enhanced_result = await self.enhanced_reporter.generate_enhanced_report(
                    industry_data=standardized_industry_data,
                    industry_name=industry_name,
                    user_id=user_id,
                    collected_articles=collected_articles,
                    historical_config=validated_config,
                    cancel_flag=cancel_flag
                )
                
                if enhanced_result.get("status") == "success":
                    reports = enhanced_result.get("reports", {})
                    log_message(user_id, f"增强版报告生成成功: {industry_name}", log_type="INFO")
                    log_webpage_report_progress(user_id, f"{industry_name}增强版报告生成成功", "INFO")
                else:
                    # 如果增强版失败，回退到标准版本
                    log_message(user_id, f"增强版报告生成失败，回退到标准版本: {enhanced_result.get('error', '未知错误')}", log_type="WARNING")
                    log_webpage_report_progress(user_id, f"增强版分析失败，自动回退到标准分析", "WARNING")
                    reports = await self.template_filler.generate_report_with_webpages(
                        standardized_industry_data, industry_name, user_id, collected_articles, cancel_flag
                    )
            else:
                # 使用标准的模板填充器生成报告
                log_message(user_id, f"使用标准报告生成器: {industry_name}", log_type="INFO")
                log_webpage_report_progress(user_id, f"使用标准分析模式生成{industry_name}报告", "INFO")
            reports = await self.template_filler.generate_report_with_webpages(
                standardized_industry_data, industry_name, user_id, collected_articles, cancel_flag
            )
            
            # 保存报告文件
            log_webpage_report_progress(user_id, f"开始保存{industry_name}报告文件", "INFO")
            saved_paths = await self._save_reports(reports, industry_name, user_id, detected_config.get("enable", False))
            
            log_message(user_id, f"{industry_name}产业链分析报告生成完成", log_type="INFO")
            log_webpage_report_progress(user_id, f"{industry_name}产业链分析报告完整流程处理完成", "INFO")
            
            return {
                "status": "success",
                "reports": reports,
                "saved_paths": saved_paths,
                "industry_name": industry_name,
                "historical_analysis": detected_config.get("enable", False),
                "detection_info": detected_config
            }
            
        except Exception as e:
            log_message(user_id, f"报告生成失败: {e}", log_type="ERROR")
            log_webpage_report_progress(user_id, f"{industry_name}报告编排器处理失败: {e}", "ERROR")
            return {
                "status": "error",
                "error": str(e),
                "reports": None,
                "saved_paths": None
            }
    
    async def _save_reports(self, reports: Dict[str, str], industry_name: str, user_id: str, is_enhanced: bool = False) -> Dict[str, str]:
        """保存报告到文件"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 根据是否使用了历史分析来确定目录名
        prefix = "enhanced" if is_enhanced else "standard"
        report_dir = f"/root/mix_project/filled_reports/{prefix}_{industry_name}_{timestamp}"
        os.makedirs(report_dir, exist_ok=True)
        
        saved_paths = {}
        
        # 保存详细版报告
        if reports.get('detailed_report'):
            report_type = "增强版详细版" if is_enhanced else "详细版"
            detailed_path = os.path.join(report_dir, f"{industry_name}_{report_type}报告_{timestamp}.md")
            with open(detailed_path, 'w', encoding='utf-8') as f:
                f.write(reports['detailed_report'])
            saved_paths['detailed'] = detailed_path
            log_message(user_id, f"{report_type}报告已保存: {detailed_path}", log_type="INFO")
            log_webpage_report_progress(user_id, f"{industry_name}{report_type}报告已保存: {detailed_path}", "INFO")
        
        # 保存精简版报告
        if reports.get('simple_report'):
            report_type = "增强版精简版" if is_enhanced else "精简版"
            simple_path = os.path.join(report_dir, f"{industry_name}_{report_type}报告_{timestamp}.md")
            with open(simple_path, 'w', encoding='utf-8') as f:
                f.write(reports['simple_report'])
            saved_paths['simple'] = simple_path
            log_message(user_id, f"{report_type}报告已保存: {simple_path}", log_type="INFO")
            log_webpage_report_progress(user_id, f"{industry_name}{report_type}报告已保存: {simple_path}", "INFO")
        
        # 如果是增强版，保存额外的分析文件
        if is_enhanced:
            if reports.get('historical_summary'):
                summary_path = os.path.join(report_dir, f"历史数据分析摘要_{timestamp}.md")
                with open(summary_path, 'w', encoding='utf-8') as f:
                    f.write(reports['historical_summary'])
                saved_paths['historical_summary'] = summary_path
                log_message(user_id, f"历史数据分析摘要已保存: {summary_path}", log_type="INFO")
        
        return saved_paths