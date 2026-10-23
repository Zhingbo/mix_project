import asyncio
import aiohttp
from aiohttp_socks import ProxyConnector
import json
import hashlib
import time
import re
from urllib.parse import quote, unquote
from utils.logger import get_logger
from services.crawler_service import log_message
from database.industrial_chain.jina_article_dao import JinaArticleDAO

logger = get_logger(__name__)

# 读取项目配置（延迟加载，避免循环引用）
_jina_config = None

def _get_jina_config():
    """获取Jina配置"""
    global _jina_config
    if _jina_config is None:
        import yaml
        import os
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'settings_show.yaml')
        with open(config_path, "r") as file:
            settings = yaml.load(file, Loader=yaml.FullLoader)
        _jina_config = {
            'url': settings['system_settings'].get('jina_api_url'),
            'headers': settings['system_settings'].get('jina_api_headers_template'),
            'keys': settings['system_settings'].get('jina_api_keys')
        }
    return _jina_config


class JinaSearcher:
    def __init__(self, url=None, headers=None, industry_name="", default_sites=None):
        # 延迟加载配置
        config = _get_jina_config()

        self.search_url = url or config['url']
        self.reader_url = "https://r.jina.ai/"  # Jina Reader API
        self.headers = headers or config['headers']
        self.industry_name = industry_name
        self.default_sites = default_sites or ["qianzhan.com", "askci.com"]

        # 添加缓存机制
        self.search_cache = {}  # 搜索结果缓存
        self.content_cache = {}  # 页面内容缓存
        self.cache_ttl = 3600  # 缓存有效期1小时
        self.max_cache_size = 1000  # 最大缓存条目数

        # 添加词元监控
        self.api_call_count = {'search': 0, 'reader': 0}
        self.estimated_tokens = 0
        self.token_budget = 1000000  # 100万词元预算

        api_key = None
        if self.headers and 'Authorization' in self.headers:
            auth_header = self.headers['Authorization']
            if auth_header.startswith('Bearer '):
                api_key = auth_header.replace('Bearer ', '')
            else:
                api_key = auth_header
        elif config['keys'] and len(config['keys']) > 0:
            first_key = config['keys'][0]
            # 支持字典格式 {'key': 'xxx', ...} 或直接字符串格式
            if isinstance(first_key, dict):
                api_key = first_key.get('key')
            else:
                api_key = first_key

        self.jina_api_key = api_key
        key_display = self.jina_api_key[:20] + '...' if self.jina_api_key and isinstance(self.jina_api_key, str) else 'None'
        log_message(None, f"JinaSearcher初始化完成，产业：{industry_name}，API密钥：{key_display}...", log_type="INFO")

    def _get_cache_key(self, data):
        """生成缓存键"""
        return hashlib.md5(str(data).encode()).hexdigest()
    
    def _is_cache_valid(self, timestamp):
        """检查缓存是否有效"""
        return time.time() - timestamp < self.cache_ttl
    
    def _add_to_cache(self, cache_dict, key, value):
        """添加到缓存，控制缓存大小"""
        if len(cache_dict) >= self.max_cache_size:
            # 删除最旧的缓存项
            oldest_key = min(cache_dict.keys(), key=lambda k: cache_dict[k]['timestamp'])
            del cache_dict[oldest_key]
        
        cache_dict[key] = {
            'data': value,
            'timestamp': time.time()
        }
    
    def _track_api_call(self, api_type, estimated_tokens):
        """跟踪API调用和词元消耗"""
        self.api_call_count[api_type] += 1
        self.estimated_tokens += estimated_tokens
        
        # if self.estimated_tokens > self.token_budget:
        #     log_message(None, f"警告：词元消耗已超过预算 {self.estimated_tokens}/{self.token_budget}", log_type="WARNING")
        log_message(None, f"API调用统计 - 搜索:{self.api_call_count['search']}, 阅读:{self.api_call_count['reader']}, 总词元:{self.estimated_tokens}", log_type="INFO")
    
    async def jina_search(self, limit=20, isNode=False, node="", user_id=None, send_message=None, sites=None, is_retry=False, get_full_content=True, suppress_search_message=False):
        """主搜索方法 - 结合Search API和Reader API"""
        try:
            # 设置当前节点，用于保存文章时关联
            self.current_node = node if isNode else None
            
            search_sites = sites or self.default_sites            
            if isNode:
                query = f"{self.industry_name} {node} 产业链"
            else:
                query = f"{self.industry_name} 产业链"           
            
            # 添加消息发送控制，避免重复发送搜索提示
            if send_message and not is_retry and not suppress_search_message:
                if isNode:
                    search_message = f'正在搜索："{self.industry_name}"产业链相关的"{node}"节点信息，搜索来源：{", ".join(search_sites)}'
                else:
                    search_message = f'正在搜索："{self.industry_name}"的产业链信息，搜索来源：{", ".join(search_sites)}'
                await send_message(search_message, "2")
            
            search_results = await self._get_search_results(query, limit, search_sites, user_id, send_message, is_retry)
            
            if not search_results:
                return None
            
            if get_full_content:
                enhanced_results = await self._enhance_with_full_content(search_results, user_id, send_message)
                return enhanced_results
            else:
                return search_results
                
        except Exception as e:
            log_message(user_id, f"搜索过程中发生错误: {e}", log_type="ERROR")
            return None

    async def _get_search_results(self, query, limit, search_sites, user_id, send_message, is_retry):
        """使用Search API获取搜索结果"""
        results = None
        
        if search_sites:
            for site in search_sites:
                site_query = f"{query} site:{site}"
                log_message(user_id, f"尝试在 {site} 搜索: {site_query}", log_type="DEBUG")
                site_results = await self._search_with_jina(site_query, limit//len(search_sites) + 2, user_id, send_message)
                if site_results:
                    if not results:
                        results = []
                    results.extend(site_results)
                    if len(results) >= limit:
                        results = results[:limit]
                        break
        
        if results:
            return results
            
        if send_message and not is_retry:
            await send_message("特定网站未搜索到相关内容，尝试普通搜索", "2")
        
        general_results = await self._search_with_jina(query, limit, user_id, send_message)
        return general_results

    async def _enhance_with_full_content(self, search_results, user_id, send_message):
        """使用Reader API增强搜索结果，获取完整内容"""
        enhanced_results = []
        
        if send_message:
            await send_message(f"正在获取 {len(search_results)} 个网页的完整内容...", "2")
        
        semaphore = asyncio.Semaphore(3)  
        
        async def get_enhanced_result(result):
            async with semaphore:
                try:
                    full_content = await self.get_page_content(result['url'], user_id)
                    if full_content:
                        enhanced_result = {
                            'title': result['title'],
                            'url': result['url'],
                            'summary': result['content'],  
                            'full_content': full_content,  
                            'content_length': len(full_content)
                        }
                        
                        if send_message:
                            await send_message(f"✓ 已获取完整内容: {result['title']} ({len(full_content)} 字符)", "5")
                        
                        return enhanced_result
                    else:
                        if send_message:
                            await send_message(f"✗ 无法获取完整内容: {result['title']}", "5")
                        return result
                except Exception as e:
                    log_message(user_id, f"获取完整内容失败 {result['url']}: {e}", log_type="ERROR")
                    return result
        
        tasks = [get_enhanced_result(result) for result in search_results]
        enhanced_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid_results = [r for r in enhanced_results if not isinstance(r, Exception)]
        
        if send_message:
            full_content_count = sum(1 for r in valid_results if 'full_content' in r)
            await send_message(f"完成内容获取：{full_content_count}/{len(search_results)} 个网页获取到完整内容", "2")
        
        return valid_results

    async def _search_with_jina(self, query, limit, user_id, send_message=None, retries=3, delay=2):
        """使用Jina搜索API进行搜索"""
        # 直接跳过Jina搜索，使用AI生成
        log_message(user_id, f"⚠️ Jina搜索已禁用，跳过: {query}", log_type="INFO")
        return None

        # 原搜索逻辑已禁用
        log_message(user_id, f"🔍 开始Jina搜索: {query} (limit={limit})", log_type="INFO")

        cache_key = self._get_cache_key({'query': query, 'limit': limit})
        if cache_key in self.search_cache:
            cached_item = self.search_cache[cache_key]
            if self._is_cache_valid(cached_item['timestamp']):
                log_message(user_id, f"使用缓存的搜索结果: {query}", log_type="INFO")
                return cached_item['data']
            else:
                log_message(user_id, f"🗑️ 清除过期缓存: {query}", log_type="DEBUG")
                del self.search_cache[cache_key]

        # if self.estimated_tokens > self.token_budget * 0.9:  
        #     log_message(user_id, f"接近词元预算限制，跳过搜索: {query}", log_type="WARNING")
        #     return None
        
        for attempt in range(retries):
            try:
                log_message(user_id, f"🔄 搜索尝试 {attempt + 1}/{retries}: {query}", log_type="DEBUG")
                
                encoded_query = quote(query)
                # 确保URL格式正确
                base_url = self.search_url.rstrip('/')
                search_url = f"{base_url}/{encoded_query}"
                
                log_message(user_id, f"📡 构建搜索URL: {search_url}", log_type="DEBUG")
                
                # 动态获取当前密钥（支持密钥切换）
                current_api_key = self.jina_api_key
                if self.headers and 'Authorization' in self.headers:
                    auth_header = self.headers['Authorization']
                    if auth_header.startswith('Bearer '):
                        current_api_key = auth_header.replace('Bearer ', '')
                
                headers = {
                    'Authorization': f'Bearer {current_api_key}',
                    'Accept': 'application/json',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                
                log_message(user_id, f"🔑 使用API密钥: {current_api_key[:20]}...{current_api_key[-10:]}", log_type="DEBUG")
                log_message(user_id, f"📤 发送Jina搜索请求: {search_url}", log_type="DEBUG")
                
                async with aiohttp.ClientSession(connector=ProxyConnector.from_url('socks5://127.0.0.1:7891')) as session:
                    async with session.get(search_url, headers=headers, timeout=30) as response:
                        response_text = await response.text()
                        # 确保response_text是字符串类型
                        if not isinstance(response_text, str):
                            response_text = str(response_text)
                        
                        log_message(user_id, f"📥 Jina API响应状态: {response.status}, 内容长度: {len(response_text)}", log_type="INFO")
                        
                        if response.status == 200:
                            if response_text:
                                log_message(user_id, f"📄 响应内容预览: {response_text[:200]}...", log_type="DEBUG")
                                results = self._parse_jina_response(response_text, limit, user_id)
                                if results and len(results) > 0:
                                    self._add_to_cache(self.search_cache, cache_key, results)
                                    # 使用更准确的token计算方法
                                    from services.accurate_token_calculator import calculate_jina_search_tokens
                                    # 传递结果内容而不是数量
                                    results_content = json.dumps(results) if isinstance(results, list) else str(results)
                                    token_info = calculate_jina_search_tokens(query, results_content)
                                    estimated_tokens = token_info['total_tokens']
                                    self._track_api_call('search', estimated_tokens)
                                    
                                    if send_message:
                                        for result in results:
                                            await send_message(f"{result['title']} url:{result['url']}", "5")
                                            if result.get('content'):
                                                await send_message(f"{result['content']}", "5")
                                        
                                    log_message(user_id, f"✅ 成功获取到 {len(results)} 个搜索结果", log_type="INFO")
                                    return results
                                else:
                                    log_message(user_id, f"⚠️ 搜索结果解析失败或为空，响应内容: {response_text[:500]}", log_type="WARNING")
                            else:
                                log_message(user_id, "⚠️ 搜索响应内容为空", log_type="WARNING")
                        else:
                            log_message(user_id, f"❌ HTTP错误 {response.status}: {response_text[:500]}", log_type="ERROR")
                            
                            if response.status == 401:
                                log_message(user_id, "🔐 API密钥无效，请检查配置", log_type="ERROR")
                                return None
                            elif response.status == 402:
                                log_message(user_id, "💳 API密钥余额不足，需要切换密钥", log_type="WARNING")
                                # 抛出异常，让上层的industry_service.py处理密钥切换
                                raise Exception(f"402 Payment Required: {response_text}")
                            elif response.status == 429:
                                log_message(user_id, "🚫 API请求频率限制，等待后重试", log_type="WARNING")
                                await asyncio.sleep(10)
                            elif response.status == 403:
                                log_message(user_id, "🚫 API访问被拒绝，可能是密钥权限问题", log_type="ERROR")
                                return None
                            
            except Exception as e:
                log_message(user_id, f"❌ 搜索请求异常 {attempt + 1}/{retries}: {e}", log_type="ERROR")
                if attempt < retries - 1:
                    log_message(user_id, f"⏳ 等待 {delay * (attempt + 1)} 秒后重试...", log_type="INFO")
            
            if attempt < retries - 1:
                await asyncio.sleep(delay * (attempt + 1))
        
        log_message(user_id, f"❌ 搜索失败，已重试 {retries} 次，查询: {query}", log_type="ERROR")
        return None

    def _parse_jina_response(self, response_text, limit, user_id=None):
        """解析Jina API响应"""
        try:
            log_message(user_id, f"🔍 开始解析Jina响应，内容长度: {len(response_text)}", log_type="DEBUG")
            
            results = []
            
            # 首先尝试JSON解析
            try:
                data = json.loads(response_text)
                log_message(user_id, f"✅ JSON解析成功，数据类型: {type(data)}", log_type="DEBUG")
                results = self._parse_json_results(data, limit, user_id)
                if results:
                    log_message(user_id, f"✅ JSON解析获得 {len(results)} 个结果", log_type="INFO")
                    return results
                else:
                    log_message(user_id, "⚠️ JSON解析未获得有效结果", log_type="WARNING")
            except json.JSONDecodeError as e:
                log_message(user_id, f"⚠️ JSON解析失败: {e}, 尝试文本解析", log_type="DEBUG")
            
            # 如果JSON解析失败，尝试文本解析
            log_message(user_id, "🔍 尝试文本格式解析", log_type="DEBUG")
            results = self._parse_text_results(response_text, limit, user_id)
            if results:
                log_message(user_id, f"✅ 文本解析获得 {len(results)} 个结果", log_type="INFO")
                return results
            else:
                log_message(user_id, "⚠️ 文本解析未获得有效结果", log_type="WARNING")
            
            # 如果以上都失败，尝试从文本中提取URL
            log_message(user_id, "🔍 尝试从文本中提取URL", log_type="DEBUG")
            results = self._extract_urls_from_text(response_text, limit, user_id)
            if results:
                log_message(user_id, f"✅ URL提取获得 {len(results)} 个结果", log_type="INFO")
                return results
            else:
                log_message(user_id, "❌ URL提取未获得有效结果", log_type="WARNING")
            
            # 最后尝试：如果响应包含有用信息但格式不标准，创建一个基本结果
            if len(response_text.strip()) > 50 and ('http' in response_text or 'www.' in response_text):
                log_message(user_id, "🔧 尝试创建基本搜索结果", log_type="DEBUG")
                basic_result = {
                    'title': '搜索结果',
                    'url': 'https://example.com',  # 占位URL
                    'content': response_text[:500].strip()
                }
                log_message(user_id, f"✅ 创建了1个基本搜索结果", log_type="INFO")
                return [basic_result]
            
            log_message(user_id, f"❌ 所有解析方法都失败了，响应内容: {response_text[:200]}...", log_type="ERROR")
            return []
            
        except Exception as e:
            log_message(user_id, f"❌ 响应解析错误: {e}", log_type="ERROR")
            return []

    def _parse_json_results(self, data, limit, user_id=None):
        """解析JSON格式的搜索结果 - 修复以支持Jina API格式"""
        try:
            log_message(user_id, f"🔍 开始JSON结果解析，数据类型: {type(data)}", log_type="DEBUG")
            results = []
            
            if isinstance(data, dict):
                log_message(user_id, f"📊 字典数据，键: {list(data.keys())}", log_type="DEBUG")
                
                # 优先检查Jina API标准格式
                if 'data' in data and isinstance(data['data'], list):
                    items = data['data']
                    log_message(user_id, f"✅ 从Jina API data字段解析到 {len(items)} 个结果", log_type="DEBUG")
                else:
                    # 尝试其他可能的字段名
                    items = (data.get('results') or 
                            data.get('items') or 
                            data.get('organic_results') or 
                            data.get('web_results') or 
                            data.get('search_results') or [])
                    
                    if items:
                        log_message(user_id, f"✅ 从备选字段解析到 {len(items)} 个结果", log_type="DEBUG")
                            
                    # 如果以上都没有，检查是否单个结果对象
                    if not items and 'title' in data and 'url' in data:
                        items = [data]
                        log_message(user_id, f"✅ 检测到单个结果对象", log_type="DEBUG")
            elif isinstance(data, list):
                items = data
                log_message(user_id, f"📋 列表数据，包含 {len(items)} 个项目", log_type="DEBUG")
            else:
                log_message(user_id, f"❌ 无法处理的数据类型: {type(data)}", log_type="ERROR")
                return []
            
            if not items:
                log_message(user_id, "⚠️ 未找到任何搜索结果项", log_type="WARNING")
                return []
            
            log_message(user_id, f"🔍 开始处理 {len(items)} 个结果项（限制: {limit}）", log_type="DEBUG")
            
            for i, item in enumerate(items[:limit]):
                if isinstance(item, dict):
                    # 提取标题，尝试多个可能的字段
                    title = (item.get('title') or 
                            item.get('name') or 
                            item.get('heading') or 
                            item.get('displayLink') or 
                            item.get('snippet', '')[:50] or 
                            f'搜索结果 {i+1}')
                    
                    # 提取URL，尝试多个可能的字段
                    url = (item.get('url') or 
                          item.get('link') or 
                          item.get('href') or 
                          item.get('formattedUrl') or
                          item.get('source'))
                    
                    # 提取内容描述
                    content = (item.get('content') or 
                              item.get('description') or 
                              item.get('snippet') or 
                              item.get('text') or 
                              item.get('htmlSnippet') or 
                              item.get('summary') or '')
                    
                    log_message(user_id, f"📄 处理项目 {i+1}: title='{str(title)[:30]}...', url='{url}', content_len={len(str(content))}", log_type="DEBUG")
                    
                    if url:
                        # 对标题和URL进行URL解码，修复乱码问题
                        decoded_title = unquote(str(title).strip()) if title else f'搜索结果 {i+1}'
                        decoded_url = unquote(str(url).strip()) if url else ''
                        decoded_content = unquote(str(content)[:1000].strip()) if content else ''
                        
                        result = {
                            'title': decoded_title,
                            'url': decoded_url,
                            'content': decoded_content
                        }
                        results.append(result)
                        log_message(user_id, f"✅ 成功添加结果 {i+1}: {result['title']}", log_type="DEBUG")
                    else:
                        log_message(user_id, f"⚠️ 跳过项目 {i+1}: 缺少URL", log_type="DEBUG")
                else:
                    log_message(user_id, f"⚠️ 跳过项目 {i+1}: 不是字典类型 ({type(item)})", log_type="DEBUG")
            
            log_message(user_id, f"✅ JSON解析完成，成功解析到 {len(results)} 个搜索结果", log_type="INFO")
            
            # 如果没有结果，记录原始数据用于调试
            if not results:
                log_message(user_id, f"❌ 未解析到任何结果，原始数据样例: {str(data)[:300]}...", log_type="WARNING")
            
            return results
            
        except Exception as e:
            log_message(user_id, f"❌ JSON结果解析错误: {e}", log_type="ERROR")
            return []

    def _parse_text_results(self, text, limit, user_id=None):
        """解析文本格式的搜索结果"""
        try:
            # 确保text是字符串类型
            if not isinstance(text, str):
                log_message(user_id, f"警告：_parse_text_results接收到非字符串类型数据: {type(text)}", log_type="WARNING")
                text = str(text)
            
            results = []
            lines = text.split('\n')
            current_result = {}
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # 匹配标题格式: [数字] Title: 标题内容
                title_match = re.match(r'\[(\d+)\]\s*Title:\s*(.+)', line)
                if title_match:
                    # 如果有之前的结果，先添加
                    if current_result and current_result.get('title') and current_result.get('url'):
                        results.append(current_result)
                        if len(results) >= limit:
                            break
                    
                    # 开始新的结果
                    current_result = {
                        'title': title_match.group(2).strip(),
                        'url': '',
                        'snippet': '',
                        'content': ''
                    }
                    continue
                
                # 匹配URL格式: [数字] URL Source: URL地址
                url_match = re.match(r'\[(\d+)\]\s*URL Source:\s*(.+)', line)
                if url_match and current_result:
                    current_result['url'] = url_match.group(2).strip()
                    continue
                
                # 匹配描述格式: [数字] Description: 描述内容
                desc_match = re.match(r'\[(\d+)\]\s*Description:\s*(.+)', line)
                if desc_match and current_result:
                    current_result['snippet'] = desc_match.group(2).strip()
                    current_result['content'] = current_result['snippet']
                    continue
                
                # 匹配其他内容格式: [数字] Content: 内容
                content_match = re.match(r'\[(\d+)\]\s*Content:\s*(.+)', line)
                if content_match and current_result:
                    current_result['content'] = content_match.group(2).strip()
                    if not current_result['snippet']:
                        current_result['snippet'] = current_result['content'][:200] + '...'
                    continue
            
            # 添加最后一个结果
            if current_result and current_result.get('title') and current_result.get('url'):
                results.append(current_result)
            
            log_message(user_id, f"从文本格式解析到 {len(results)} 个结果", log_type="DEBUG")
            return results[:limit]
            
        except Exception as e:
            log_message(user_id, f"文本解析错误: {e}", log_type="ERROR")
            return []

    def _extract_urls_from_text(self, text, limit, user_id=None):
        """从文本中提取URL作为后备方案"""
        try:
            results = []
            
            # 使用正则表达式提取所有URL
            url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
            urls = re.findall(url_pattern, text)
            
            # 去重并限制数量
            unique_urls = list(dict.fromkeys(urls))  # 保持顺序的去重
            
            for i, url in enumerate(unique_urls[:limit]):
                # 尝试从文本中找到与URL相关的标题
                title = f"搜索结果 {i+1}"
                snippet = ""
                
                # 在URL附近查找可能的标题
                url_index = text.find(url)
                if url_index > 0:
                    # 查找URL前面的文本作为标题
                    before_text = text[max(0, url_index-200):url_index]
                    lines_before = before_text.split('\n')
                    for line in reversed(lines_before):
                        line = line.strip()
                        if line and len(line) > 10 and not line.startswith('http'):
                            title = line[:100]
                            break
                    
                    # 查找URL后面的文本作为摘要
                    after_text = text[url_index:url_index+300]
                    lines_after = after_text.split('\n')
                    for line in lines_after[1:]:  # 跳过URL本身
                        line = line.strip()
                        if line and len(line) > 20:
                            snippet = line[:200]
                            break
                
                results.append({
                    'title': title,
                    'url': url,
                    'snippet': snippet,
                    'content': snippet
                })
            
            log_message(user_id, f"从文本中提取到 {len(results)} 个URL", log_type="DEBUG")
            return results
            
        except Exception as e:
            log_message(user_id, f"URL提取错误: {e}", log_type="ERROR")
            return []

    async def get_page_content(self, url, user_id=None):
        """使用Jina Reader API获取网页完整内容"""
        try:
            reader_url = f"{self.reader_url}{url}"
            
            # 动态获取当前密钥（支持密钥切换）
            current_api_key = self.jina_api_key
            if self.headers and 'Authorization' in self.headers:
                auth_header = self.headers['Authorization']
                if auth_header.startswith('Bearer '):
                    current_api_key = auth_header.replace('Bearer ', '')
            
            headers = {
                'Authorization': f'Bearer {current_api_key}',
                'Accept': 'text/plain',  
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            log_message(user_id, f"使用Jina Reader获取页面内容: {url}", log_type="DEBUG")
            
            async with aiohttp.ClientSession(connector=ProxyConnector.from_url('socks5://127.0.0.1:7891')) as session:
                async with session.get(reader_url, headers=headers, timeout=60) as response:
                    if response.status == 200:  
                        content = await response.text()
                        cleaned_content = '\n'.join(line.strip() for line in content.split('\n') if line.strip())
                        log_message(user_id, f"成功获取页面内容，原始长度: {len(content)}, 清理后长度: {len(cleaned_content)}", log_type="DEBUG")
                        
                        # 保存文章内容到新表
                        await self._save_article_content(url, None, cleaned_content, 1)
                        
                        return cleaned_content
                    else:
                        log_message(user_id, f"获取页面内容失败: HTTP {response.status}", log_type="ERROR")
                        
                        # 保存失败记录
                        # await self._save_article_content(url, None, None, 0)
                        pass  # 已注释掉文章存储功能
                        
                        return None
                        
        except Exception as e:
            log_message(user_id, f"获取页面内容时出错: {e}", log_type="ERROR")
            
            # 保存失败记录
            # await self._save_article_content(url, None, None, 0)
            pass  # 已注释掉文章存储功能
            
            return None
    
    async def _save_article_content(self, url, title, content, fetch_status):
        """保存文章内容到数据库"""
        try:
            # 从搜索结果中获取标题（如果有的话）
            if not title:
                title = "未知标题"
            
            await JinaArticleDAO.save_article_content(
                url=url,
                title=title,
                content=content or "",
                chain_name=self.industry_name,
                node_name=getattr(self, 'current_node', None),
                fetch_status=fetch_status
            )
        except Exception as e:
            log_message(None, f"保存文章内容到数据库失败: {e}", log_type="ERROR")
    
    async def jina_search(self, limit=20, isNode=False, node="", user_id=None, send_message=None, sites=None, is_retry=False, get_full_content=True, suppress_search_message=False):
        """主搜索方法 - 结合Search API和Reader API"""
        try:
            # 设置当前节点，用于保存文章时关联
            self.current_node = node if isNode else None
            
            search_sites = sites or self.default_sites            
            if isNode:
                query = f"{self.industry_name} {node} 产业链"
            else:
                query = f"{self.industry_name} 产业链"           
            if send_message and not is_retry and not suppress_search_message:
                if isNode:
                    search_message = f'正在搜索："{self.industry_name}"产业链相关的"{node}"节点信息，搜索来源：{", ".join(search_sites)}'
                else:
                    search_message = f'正在搜索："{self.industry_name}"的产业链信息，搜索来源：{", ".join(search_sites)}'
                await send_message(search_message, "2")
            
            search_results = await self._get_search_results(query, limit, search_sites, user_id, send_message, is_retry)
            
            if not search_results:
                return None
            
            # 在_enhance_with_full_content方法中，为每个获取到内容的文章保存标题
            if get_full_content and search_results:
                enhanced_results = await self._enhance_with_full_content(search_results, user_id, send_message)
                return enhanced_results
            
            return search_results
            
        except Exception as e:
            log_message(user_id, f"Jina搜索过程出错: {e}", log_type="ERROR")
            return []
    
    async def _enhance_with_full_content(self, search_results, user_id, send_message):
        """为搜索结果增强完整内容"""
        enhanced_results = []
        
        for result in search_results:
            try:
                url = result.get('url', '')
                title = result.get('title', '未知标题')
                
                # 获取完整内容
                full_content = await self.get_page_content(url, user_id)
                
                if full_content:
                    result['content'] = full_content
                    result['content_length'] = len(full_content)
                    
                    # 更新保存的文章标题
                    # await self._save_article_content(url, title, full_content, 1)
                    pass  # 已注释掉文章存储功能
                else:
                    result['content'] = ""
                    result['content_length'] = 0
                    
                    # 保存失败记录
                    # await self._save_article_content(url, title, None, 0)
                    pass  # 已注释掉文章存储功能

                enhanced_results.append(result)

            except Exception as e:
                log_message(user_id, f"处理搜索结果时出错: {e}", log_type="ERROR")
                enhanced_results.append(result)

        return enhanced_results

    async def search(self, query, limit=10):
        """便捷搜索方法 - 直接搜索查询词"""
        try:
            # 临时保存原产业名并设置搜索查询
            original_industry_name = self.industry_name
            self.industry_name = query

            results = await self.jina_search(
                limit=limit,
                isNode=False,
                node="",
                user_id=None,
                send_message=None,
                sites=None,
                is_retry=False,
                get_full_content=False,
                suppress_search_message=True
            )

            # 恢复原产业名
            self.industry_name = original_industry_name

            if results:
                return {'results': results}
            return None
        except Exception as e:
            log_message(None, f"搜索失败: {e}", log_type="ERROR")
            return None

    async def search_with_site(self, query, site_constraint):
        """按站点约束搜索方法"""
        try:
            # 临时保存原产业名并设置搜索查询
            # 注意：query 可能已经包含 "产业链" 后缀，而 jina_search 会自动添加 "产业链"
            # 所以这里需要去掉 "产业链" 后缀，避免重复
            original_industry_name = self.industry_name
            clean_query = query
            if query.endswith('产业链'):
                clean_query = query[:-3].strip()  # 去掉 "产业链"
            self.industry_name = clean_query

            log_message(None, f"🔎 search_with_site: query={query}, clean_query={clean_query}, site={site_constraint}", log_type="DEBUG")

            # 从site_constraint中提取域名
            if "site:" in site_constraint:
                domain = site_constraint.replace("site:", "")
            else:
                domain = site_constraint

            results = await self.jina_search(
                limit=10,
                isNode=False,
                node="",
                user_id=None,
                send_message=None,
                sites=[domain],
                is_retry=False,
                get_full_content=False,
                suppress_search_message=True
            )

            log_message(None, f"🔎 search_with_site results: {type(results)}, len={len(results) if results else 0}", log_type="DEBUG")

            # 恢复原产业名
            self.industry_name = original_industry_name

            if results:
                return {'results': results}
            return None
        except Exception as e:
            log_message(None, f"站点搜索失败: {e}", log_type="ERROR")
            return None
