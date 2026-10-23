import requests

class ExternalAPI:
    """外部API服务类"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url
    
    def get_data(self, endpoint: str, params: dict = None):
        """
        从外部API获取数据
        
        Args:
            endpoint: API端点
            params: 请求参数
            
        Returns:
            API响应数据
        """
        try:
            url = f"{self.base_url}/{endpoint}"
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            return response.json()
        except Exception as e:
            return None
    
    def post_data(self, endpoint: str, data: dict):
        """
        向外部API发送数据
        
        Args:
            endpoint: API端点
            data: 请求数据
            
        Returns:
            API响应数据
        """
        try:
            url = f"{self.base_url}/{endpoint}"
            
            response = requests.post(url, json=data)
            response.raise_for_status()
            
            return response.json()
        except Exception as e:
            return None

# 创建示例外部API服务
example_api = ExternalAPI("https://api.example.com") 