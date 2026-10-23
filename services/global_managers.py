import asyncio
import yaml
from .jina_search_service import JinaSearcher
from services.crawler_service import log_message

# 全局变量
_global_key_manager = None
_global_jina_searcher = None
_key_manager_lock = asyncio.Lock()
_jina_searcher_lock = asyncio.Lock()

# 加载配置
with open("config/settings_show.yaml", "r") as file:
    settings = yaml.load(file, Loader=yaml.FullLoader)

jina_api_keys = settings['system_settings']['jina_api_keys']
jina_api_headers_template = settings['system_settings']['jina_api_headers_template']
jina_api_url = settings['system_settings']['jina_api_url']

class SimpleKeyManager:
    def __init__(self, keys_config, headers_template):
        self.keys_config = keys_config
        self.headers_template = headers_template
        self.current_key_index = 0
        
        # 初始化key状态
        for key_info in self.keys_config:
            if 'status' not in key_info:
                key_info['status'] = 'active'
        
        log_message(None, f"SimpleKeyManager初始化完成，共 {len(self.keys_config)} 个密钥", log_type="INFO")
        log_message(None, f"SimpleKeyManager初始化完成，使用单个密钥: {self.keys_config[0]['name'] if self.keys_config else 'None'}", log_type="INFO")
    
    def get_current_key(self):
        """获取当前可用的API key（简化版本，只使用第一个密钥）"""
        # for i in range(len(self.keys_config)):
        #     key_index = (self.current_key_index + i) % len(self.keys_config)
        #     key_info = self.keys_config[key_index]
            
        #     if key_info['status'] == 'active':
        #         self.current_key_index = key_index
        #         return key_info


        if self.keys_config and len(self.keys_config) > 0:
            return self.keys_config[0]
        return None

    def get_headers(self):
        """获取当前key的请求头"""
        current_key = self.get_current_key()
        if not current_key:
            return None
            
        headers = self.headers_template.copy()
        # 处理模板中的占位符
        if 'Authorization' in headers and '{api_key}' in headers['Authorization']:
            headers['Authorization'] = headers['Authorization'].format(api_key=current_key['key'])
        else:
            headers['Authorization'] = f"Bearer {current_key['key']}"
        return headers
    
    def mark_key_exhausted(self, error_code=None):
        """标记当前key为不可用状态"""
        if not self.keys_config:
            return False
            
        # current_key = self.keys_config[self.current_key_index]
        current_key = self.keys_config[0]
        current_key['status'] = 'exhausted'
        
        log_message(None, f"密钥 {current_key['name']} 标记为不可用 (错误码: {error_code})", log_type="WARNING")
        # 切换到下一个可用key
        # for i in range(1, len(self.keys_config)):
        #     next_index = (self.current_key_index + i) % len(self.keys_config)
        #     next_key = self.keys_config[next_index]
            
        #     if next_key['status'] == 'active':
        #         self.current_key_index = next_index
        #         log_message(None, f"已切换到密钥 {next_key['name']}", log_type="INFO")
        #         return True
        
        # log_message(None, "没有可用的API密钥", log_type="ERROR")
        log_message(None, "使用单个密钥模式，无法切换到其他密钥", log_type="ERROR")
        return False
    
    def reset_all_keys(self):
        """重置所有密钥为可用状态"""
        for key_info in self.keys_config:
            if key_info['status'] == 'exhausted':
                key_info['status'] = 'active'
        log_message(None, "密钥状态已重置为可用", log_type="INFO")
    
    def get_status_summary(self):
        """获取密钥状态摘要"""
        active_count = sum(1 for key in self.keys_config if key['status'] == 'active')
        exhausted_count = sum(1 for key in self.keys_config if key['status'] == 'exhausted')
        
        return {
            'total_keys': len(self.keys_config),
            'active_keys': active_count,
            'exhausted_keys': exhausted_count,
            # 'current_key': self.keys_config[self.current_key_index]['name'] if self.keys_config else None
            'current_key': self.keys_config[0]['name'] if self.keys_config else None
        }

async def get_global_key_manager():
    """获取全局密钥管理器实例（单例模式）"""
    global _global_key_manager
    async with _key_manager_lock:
        if _global_key_manager is None:
            _global_key_manager = SimpleKeyManager(jina_api_keys, jina_api_headers_template)
        return _global_key_manager

async def get_global_jina_searcher(industry_name: str):
    """获取全局JinaSearcher实例（单例模式），但更新产业名称"""
    global _global_jina_searcher
    async with _jina_searcher_lock:
        if _global_jina_searcher is None:
            key_manager = await get_global_key_manager()
            headers = key_manager.get_headers()
            
            _global_jina_searcher = JinaSearcher(
                jina_api_url, 
                headers, 
                industry_name
            )
            log_message(None, f"🔧 创建全局JinaSearcher实例: {industry_name}", log_type="INFO")
        else:
            # 更新现有实例的产业名称
            if _global_jina_searcher.industry_name != industry_name:
                _global_jina_searcher.industry_name = industry_name
                log_message(None, f"🔄 更新全局JinaSearcher产业名称: {industry_name}", log_type="INFO")
        
        return _global_jina_searcher