#!/usr/bin/env python3
"""
准确的Jina API Token计算器
根据Jina API的实际计费规则进行计算
"""

import re
import tiktoken
from typing import Optional

class JinaTokenCalculator:
    """Jina API Token精确计算器"""
    
    def __init__(self):
        # Jina API的计费规则（基于官方文档）
        self.search_api_rates = {
            "base_cost": 0.02,  # 每1000次搜索的基础费用
            "token_cost": 0.02  # 每1000个token的费用
        }
        
        self.reader_api_rates = {
            "base_cost": 0.02,  # 每1000次阅读的基础费用  
            "token_cost": 0.02  # 每1000个token的费用
        }
        
        # 初始化tokenizer（使用GPT-3.5的tokenizer作为近似）
        try:
            self.tokenizer = tiktoken.encoding_for_model("gpt-3.5-turbo")
        except:
            self.tokenizer = None
    
    def calculate_search_tokens(self, query: str, results: str = "") -> dict:
        """
        计算搜索API的token消耗
        
        Args:
            query: 搜索查询
            results: 搜索结果内容
            
        Returns:
            包含token数量和成本的字典
        """
        # 搜索API主要按查询计费，结果预览通常很短
        query_tokens = self._count_tokens(query)
        results_preview_tokens = min(self._count_tokens(results), 500)  # 搜索结果预览通常限制在500token内
        
        total_tokens = query_tokens + results_preview_tokens
        cost = (total_tokens / 1000) * self.search_api_rates["token_cost"]
        
        return {
            "query_tokens": query_tokens,
            "results_tokens": results_preview_tokens,
            "total_tokens": total_tokens,
            "cost": cost,
            "api_type": "search"
        }
    
    def calculate_reader_tokens(self, url: str, content: str) -> dict:
        """
        计算阅读API的token消耗
        
        Args:
            url: 要阅读的URL
            content: 阅读获取的完整内容
            
        Returns:
            包含token数量和成本的字典
        """
        # 阅读API按实际获取的内容长度计费
        url_tokens = self._count_tokens(url)
        content_tokens = self._count_tokens(content)
        
        total_tokens = url_tokens + content_tokens
        cost = (total_tokens / 1000) * self.reader_api_rates["token_cost"]
        
        return {
            "url_tokens": url_tokens,
            "content_tokens": content_tokens,
            "total_tokens": total_tokens,
            "cost": cost,
            "api_type": "reader"
        }
    
    def _count_tokens(self, text: str) -> int:
        """准确计算文本的token数量"""
        if not text:
            return 0
            
        if self.tokenizer:
            try:
                return len(self.tokenizer.encode(text))
            except:
                pass
        
        # 备用方法：更准确的估算
        # 中文字符通常是1.5-2个token，英文单词平均1.3个token
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        english_words = len(re.findall(r'\b[a-zA-Z]+\b', text))
        other_chars = len(text) - chinese_chars - sum(len(word) for word in re.findall(r'\b[a-zA-Z]+\b', text))
        
        estimated_tokens = int(chinese_chars * 1.8 + english_words * 1.3 + other_chars * 0.5)
        return max(estimated_tokens, 1)
    
    def calculate_batch_tokens(self, api_calls: list) -> dict:
        """批量计算多个API调用的token消耗"""
        total_search_tokens = 0
        total_reader_tokens = 0
        total_search_cost = 0.0
        total_reader_cost = 0.0
        
        for call in api_calls:
            if call.get("type") == "search":
                result = self.calculate_search_tokens(
                    call.get("query", ""), 
                    call.get("results", "")
                )
                total_search_tokens += result["total_tokens"]
                total_search_cost += result["cost"]
            elif call.get("type") == "reader":
                result = self.calculate_reader_tokens(
                    call.get("url", ""), 
                    call.get("content", "")
                )
                total_reader_tokens += result["total_tokens"]
                total_reader_cost += result["cost"]
        
        return {
            "search_tokens": total_search_tokens,
            "reader_tokens": total_reader_tokens,
            "total_tokens": total_search_tokens + total_reader_tokens,
            "search_cost": total_search_cost,
            "reader_cost": total_reader_cost,
            "total_cost": total_search_cost + total_reader_cost,
            "api_calls": len(api_calls)
        }

# 全局实例
jina_calculator = JinaTokenCalculator()

def calculate_jina_search_tokens(query: str, results: str = "") -> dict:
    """便捷函数：计算搜索token"""
    return jina_calculator.calculate_search_tokens(query, results)

def calculate_jina_reader_tokens(url: str, content: str) -> dict:
    """便捷函数：计算阅读token"""
    return jina_calculator.calculate_reader_tokens(url, content)
