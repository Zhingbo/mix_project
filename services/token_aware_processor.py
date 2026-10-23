import tiktoken
import asyncio
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
import logging

@dataclass
class BatchConfig:
    """批次配置"""
    max_input_tokens: int = 3000  # 输入Token限制
    max_output_tokens: int = 1000  # 输出Token限制
    overlap_tokens: int = 200     # 批次间重叠Token数
    safety_margin: float = 0.8    # 安全边距(80%)

class TokenAwareProcessor:
    """Token感知处理器 - 智能分批处理"""
    
    def __init__(self, model_name: str = "gpt-3.5-turbo"):
        self.logger = logging.getLogger(__name__)
        self.encoding = tiktoken.encoding_for_model(model_name)
        self.config = BatchConfig()
        
    def count_tokens(self, text: str) -> int:
        """精确计算Token数量"""
        return len(self.encoding.encode(text))
    
    def split_content_by_tokens(self, content: str, max_tokens: int) -> List[str]:
        """按Token数量智能分割内容"""
        if self.count_tokens(content) <= max_tokens:
            return [content]
        
        # 按段落分割
        paragraphs = content.split('\n\n')
        chunks = []
        current_chunk = ""
        current_tokens = 0
        
        for paragraph in paragraphs:
            para_tokens = self.count_tokens(paragraph)
            
            # 如果单个段落就超过限制，需要进一步分割
            if para_tokens > max_tokens:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                    current_tokens = 0
                
                # 按句子分割超长段落
                sentences = paragraph.split('。')
                for sentence in sentences:
                    sentence = sentence.strip() + '。'
                    sent_tokens = self.count_tokens(sentence)
                    
                    if current_tokens + sent_tokens <= max_tokens:
                        current_chunk += sentence
                        current_tokens += sent_tokens
                    else:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                        current_chunk = sentence
                        current_tokens = sent_tokens
            else:
                # 正常段落处理
                if current_tokens + para_tokens <= max_tokens:
                    current_chunk += paragraph + '\n\n'
                    current_tokens += para_tokens
                else:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = paragraph + '\n\n'
                    current_tokens = para_tokens
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks
    
    def create_batches(self, webpages: List[Dict[str, Any]], prompt_template: str) -> List[Dict[str, Any]]:
        """创建智能批次"""
        batches = []
        current_batch = []
        current_tokens = 0
        
        # 计算提示词Token数
        prompt_tokens = self.count_tokens(prompt_template)
        available_tokens = int(self.config.max_input_tokens * self.config.safety_margin) - prompt_tokens
        
        for webpage in webpages:
            # 计算网页内容Token数
            content = f"标题: {webpage.get('title', '')}\n内容: {webpage.get('content', '')}"
            content_tokens = self.count_tokens(content)
            
            # 如果单个网页内容过长，需要分割
            if content_tokens > available_tokens:
                # 先处理当前批次
                if current_batch:
                    batches.append({
                        'webpages': current_batch.copy(),
                        'estimated_tokens': current_tokens
                    })
                    current_batch = []
                    current_tokens = 0
                
                # 分割超长内容
                content_chunks = self.split_content_by_tokens(webpage['content'], available_tokens - 100)
                for i, chunk in enumerate(content_chunks):
                    chunk_webpage = webpage.copy()
                    chunk_webpage['content'] = chunk
                    chunk_webpage['chunk_info'] = f"第{i+1}部分，共{len(content_chunks)}部分"
                    
                    batches.append({
                        'webpages': [chunk_webpage],
                        'estimated_tokens': self.count_tokens(f"标题: {chunk_webpage['title']}\n内容: {chunk}")
                    })
            else:
                # 检查是否可以加入当前批次
                if current_tokens + content_tokens <= available_tokens:
                    current_batch.append(webpage)
                    current_tokens += content_tokens
                else:
                    # 当前批次已满，创建新批次
                    if current_batch:
                        batches.append({
                            'webpages': current_batch.copy(),
                            'estimated_tokens': current_tokens
                        })
                    current_batch = [webpage]
                    current_tokens = content_tokens
        
        # 处理最后一个批次
        if current_batch:
            batches.append({
                'webpages': current_batch.copy(),
                'estimated_tokens': current_tokens
            })
        
        self.logger.info(f"创建了 {len(batches)} 个批次，平均每批次 {sum(b['estimated_tokens'] for b in batches) / len(batches):.0f} tokens")
        return batches