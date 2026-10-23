from typing import List, Dict, Any, Optional
import logging

class BatchResultAggregator:
    """批量结果聚合器 - 用于处理和聚合批量AI调用的结果"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def aggregate_results(self, results: List[Dict[str, Any]], strategy: str = "merge") -> Dict[str, Any]:
        """
        聚合批量处理结果
        
        Args:
            results: 批量处理结果列表
            strategy: 聚合策略 ("merge", "concat", "best")
        
        Returns:
            聚合后的结果
        """
        if not results:
            return {}
        
        if strategy == "merge":
            return self._merge_results(results)
        elif strategy == "concat":
            return self._concat_results(results)
        elif strategy == "best":
            return self._select_best_result(results)
        else:
            return results[0] if results else {}
    
    def _merge_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """合并结果"""
        merged = {}
        for result in results:
            if isinstance(result, dict):
                for key, value in result.items():
                    if key in merged:
                        if isinstance(merged[key], list) and isinstance(value, list):
                            merged[key].extend(value)
                        elif isinstance(merged[key], str) and isinstance(value, str):
                            merged[key] = merged[key] + "\n" + value
                        else:
                            merged[key] = value
                    else:
                        merged[key] = value
        return merged
    
    def _concat_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """连接结果"""
        concatenated = {
            "content": "",
            "items": [],
            "metadata": {}
        }
        
        for result in results:
            if isinstance(result, dict):
                if "content" in result:
                    concatenated["content"] += str(result["content"]) + "\n"
                if "items" in result and isinstance(result["items"], list):
                    concatenated["items"].extend(result["items"])
                if "metadata" in result:
                    concatenated["metadata"].update(result["metadata"])
        
        return concatenated
    
    def _select_best_result(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """选择最佳结果"""
        if not results:
            return {}
        
        # 简单策略：选择内容最丰富的结果
        best_result = results[0]
        max_score = self._score_result(best_result)
        
        for result in results[1:]:
            score = self._score_result(result)
            if score > max_score:
                max_score = score
                best_result = result
        
        return best_result
    
    def _score_result(self, result: Dict[str, Any]) -> float:
        """为结果打分"""
        if not isinstance(result, dict):
            return 0.0
        
        score = 0.0
        
        # 内容长度权重
        if "content" in result:
            score += len(str(result["content"])) * 0.1
        
        # 项目数量权重
        if "items" in result and isinstance(result["items"], list):
            score += len(result["items"]) * 10
        
        # 元数据丰富度权重
        if "metadata" in result and isinstance(result["metadata"], dict):
            score += len(result["metadata"]) * 5
        
        return score 