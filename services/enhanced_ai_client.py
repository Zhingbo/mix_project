import os
import asyncio
import time
from typing import List, Dict, Any, Optional
import logging
from openai import OpenAI
from .token_aware_processor import TokenAwareProcessor
from .batch_result_aggregator import BatchResultAggregator

class UnifiedAIClient:
    """统一AI客户端 - 提供基础的AI调用功能"""

    def __init__(self, api_key: str = None, model: str = "deepseek-v4-pro"):
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.model = model
        self.logger = logging.getLogger(__name__)

        self.client = OpenAI(
            api_key=self.api_key,
            base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
        )
    
    async def generate_content(self, prompt: str, **kwargs) -> str:
        """生成内容"""
        try:
            messages = [{"role": "user", "content": prompt}]
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=kwargs.get('temperature', 0.6),
                **kwargs
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            self.logger.error(f"AI内容生成失败: {e}")
            raise

class EnhancedAIClient:
    """增强的AI客户端 - 支持批次处理和结果聚合"""

    def __init__(self, api_key: str = None, model: str = "deepseek-v4-pro"):
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.model = model
        self.logger = logging.getLogger(__name__)
        self.token_processor = TokenAwareProcessor(model)
        self.result_aggregator = BatchResultAggregator()

        self.client = OpenAI(
            api_key=self.api_key,
            base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
        )
    
    async def generate_content_with_batching(self, 
                                           webpages: List[Dict[str, Any]], 
                                           prompt_template: str,
                                           chapter_name: str = "") -> Dict[str, Any]:
        """带批次处理的内容生成"""
        start_time = time.time()
        
        batches = self.token_processor.create_batches(webpages, prompt_template)
        self.logger.info(f"将 {len(webpages)} 个网页分为 {len(batches)} 个批次处理")
        batch_results = []
        semaphore = asyncio.Semaphore(3)  
        
        async def process_batch(batch_idx: int, batch: Dict[str, Any]) -> str:
            async with semaphore:
                try:
                    batch_prompt = self._build_batch_prompt(batch['webpages'], prompt_template, batch_idx, len(batches))
                    
                    result = await self._call_ai_api(batch_prompt)
                    
                    self.logger.info(f"批次 {batch_idx + 1}/{len(batches)} 处理完成")
                    return result
                    
                except Exception as e:
                    self.logger.error(f"批次 {batch_idx + 1} 处理失败: {e}")
                    return f"批次 {batch_idx + 1} 处理失败，请检查数据质量。"
        
        tasks = [process_batch(i, batch) for i, batch in enumerate(batches)]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid_results = []
        for i, result in enumerate(batch_results):
            if isinstance(result, Exception):
                self.logger.error(f"批次 {i + 1} 异常: {result}")
                valid_results.append(f"批次 {i + 1} 处理异常")
            else:
                valid_results.append(result)
        
        final_content = self.result_aggregator.merge_chapter_content(valid_results, chapter_name)
        
        processing_time = time.time() - start_time
        return {
            'content': final_content,
            'metadata': {
                'total_batches': len(batches),
                'successful_batches': len([r for r in valid_results if not r.startswith('批次')]),
                'total_webpages': len(webpages),
                'processing_time': processing_time,
                'estimated_tokens': sum(b['estimated_tokens'] for b in batches)
            }
        }
    
    def _build_batch_prompt(self, webpages: List[Dict[str, Any]], template: str, batch_idx: int, total_batches: int) -> str:
        """构建批次提示词"""
        batch_context = ""
        if total_batches > 1:
            batch_context = f"\n\n【批次信息】这是第 {batch_idx + 1} 批次，共 {total_batches} 批次。请专注分析本批次数据，保持内容完整性。\n\n"
        
        webpages_content = ""
        for i, webpage in enumerate(webpages, 1):
            chunk_info = webpage.get('chunk_info', '')
            chunk_suffix = f" ({chunk_info})" if chunk_info else ""
            
            webpages_content += f"\n\n=== 网页 {i}{chunk_suffix} ===\n"
            webpages_content += f"标题: {webpage.get('title', '')}\n"
            webpages_content += f"URL: {webpage.get('url', '')}\n"
            webpages_content += f"内容: {webpage.get('content', '')}\n"
        
        return template + batch_context + webpages_content
    
    async def _call_ai_api(self, prompt: str) -> str:
        """调用AI API"""
        try:
            messages = [{"role": "user", "content": prompt}]
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.6,
                max_tokens=self.token_processor.config.max_output_tokens if hasattr(self.token_processor, 'config') else 4000
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            self.logger.error(f"AI API调用失败: {e}")
            raise
