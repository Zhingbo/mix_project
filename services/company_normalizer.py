"""
公司名称标准化服务
功能：将公司简称/别名统一转换为工商注册全称，然后进行去重
数据源：爱企查API + 本地缓存映射表 + AI推断
"""

import os
import re
import time
import requests
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
from collections import defaultdict
import mysql.connector
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class CompanyInfo:
    """公司信息"""
    input_name: str          # 输入的名称
    standard_name: str       # 工商注册标准名称
    credit_code: str         # 统一社会信用代码
    status: str              # 查询状态: success/not_found/error
    source: str              # 数据来源: cache/api/ai/preset


class CompanyNormalizer:
    """公司名称标准化服务"""
    
    def __init__(self, db_config: dict = None):
        self.db_config = db_config or {
            'host': os.getenv('DB_HOST', '8.141.5.67'),
            'port': 3306,
            'user': os.getenv('DB_USER', 'root'),
            'password': os.getenv('DB_PASSWORD'),
            'database': os.getenv('DB_NAME', 'business_data')
        }
        self._init_cache_table()
        
        # 常见后缀，用于提取核心名称
        self.suffixes = [
            '股份有限公司', '有限责任公司', '有限公司', '集团有限公司', 
            '集团股份有限公司', '集团', '公司', '控股', '科技', '技术',
            '（中国）', '(中国)', '（上海）', '(上海)', '（北京）', '(北京)',
            '（深圳）', '(深圳)', '（广州）', '(广州)', '（杭州）', '(杭州)'
        ]
        
        # 知名公司简称->全称映射（预置常见的）
        self.known_mappings = {
            '华为': '华为技术有限公司',
            '腾讯': '深圳市腾讯计算机系统有限公司',
            '阿里': '阿里巴巴（中国）有限公司',
            '阿里巴巴': '阿里巴巴（中国）有限公司',
            '百度': '北京百度网讯科技有限公司',
            '字节跳动': '北京字节跳动科技有限公司',
            '字节': '北京字节跳动科技有限公司',
            '小米': '小米科技有限责任公司',
            '京东': '北京京东世纪贸易有限公司',
            '美团': '北京三快科技有限公司',
            '滴滴': '北京小桔科技有限公司',
            '网易': '广州网易计算机系统有限公司',
            '比亚迪': '比亚迪股份有限公司',
            '宁德时代': '宁德时代新能源科技股份有限公司',
            '特斯拉': '特斯拉（上海）有限公司',
            '蔚来': '蔚来汽车科技（安徽）有限公司',
            '小鹏': '广州小鹏汽车科技有限公司',
            '小鹏汽车': '广州小鹏汽车科技有限公司',
            '理想': '北京车和家信息技术有限公司',
            '理想汽车': '北京车和家信息技术有限公司',
            '大疆': '深圳市大疆创新科技有限公司',
            '商汤': '商汤科技开发有限公司',
            '商汤科技': '商汤科技开发有限公司',
            '旷视': '北京旷视科技有限公司',
            '旷视科技': '北京旷视科技有限公司',
            '科大讯飞': '科大讯飞股份有限公司',
            '寒武纪': '中科寒武纪科技股份有限公司',
            '地平线': '北京地平线机器人技术研发有限公司',
            '中芯国际': '中芯国际集成电路制造有限公司',
            '台积电': '台湾积体电路制造股份有限公司',
            '三星': '三星（中国）投资有限公司',
            '英特尔': '英特尔（中国）有限公司',
            '英伟达': '英伟达半导体科技（上海）有限公司',
            'NVIDIA': '英伟达半导体科技（上海）有限公司',
            '高通': '高通无线通信技术（中国）有限公司',
            '博世': '博世（中国）投资有限公司',
            '大陆集团': '大陆汽车投资（上海）有限公司',
            '采埃孚': '采埃孚（中国）投资有限公司',
            'ZF': '采埃孚（中国）投资有限公司',
            '宇通': '郑州宇通客车股份有限公司',
            '宇通客车': '郑州宇通客车股份有限公司',
            '上汽': '上海汽车集团股份有限公司',
            '上汽集团': '上海汽车集团股份有限公司',
            '一汽': '中国第一汽车集团有限公司',
            '东风': '东风汽车集团有限公司',
            '长安': '重庆长安汽车股份有限公司',
            '长安汽车': '重庆长安汽车股份有限公司',
            '吉利': '浙江吉利控股集团有限公司',
            '吉利汽车': '浙江吉利控股集团有限公司',
            '长城': '长城汽车股份有限公司',
            '长城汽车': '长城汽车股份有限公司',
            '广汽': '广州汽车集团股份有限公司',
            '广汽集团': '广州汽车集团股份有限公司',
            '北汽': '北京汽车集团有限公司',
            '北汽集团': '北京汽车集团有限公司',
        }
    
    def _init_cache_table(self):
        """初始化缓存表"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS company_name_cache (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    input_name VARCHAR(255) NOT NULL,
                    standard_name VARCHAR(255),
                    credit_code VARCHAR(50),
                    status VARCHAR(20) DEFAULT 'success',
                    source VARCHAR(20) DEFAULT 'api',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_input_name (input_name),
                    INDEX idx_standard_name (standard_name)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            conn.commit()
            cursor.close()
            conn.close()
            logger.info("缓存表初始化完成")
        except Exception as e:
            logger.error(f"初始化缓存表失败: {e}")
    
    def _get_from_cache(self, company_name: str) -> Optional[CompanyInfo]:
        """从缓存获取公司信息"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT * FROM company_name_cache WHERE input_name = %s",
                (company_name,)
            )
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if row:
                return CompanyInfo(
                    input_name=row['input_name'],
                    standard_name=row['standard_name'] or company_name,
                    credit_code=row['credit_code'] or '',
                    status=row['status'],
                    source='cache'
                )
            return None
        except Exception as e:
            logger.error(f"查询缓存失败: {e}")
            return None
    
    def _save_to_cache(self, info: CompanyInfo):
        """保存到缓存"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO company_name_cache (input_name, standard_name, credit_code, status, source)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    standard_name = VALUES(standard_name),
                    credit_code = VALUES(credit_code),
                    status = VALUES(status),
                    source = VALUES(source)
            """, (info.input_name, info.standard_name, info.credit_code, info.status, info.source))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"保存缓存失败: {e}")
    
    def _extract_core_name(self, company_name: str) -> str:
        """提取公司核心名称"""
        core = company_name
        for suffix in self.suffixes:
            core = core.replace(suffix, '')
        core = re.sub(r'[（(][^）)]*[）)]', '', core)
        return core.strip()
    
    def _query_aiqicha(self, company_name: str) -> Optional[CompanyInfo]:
        """查询爱企查API获取公司标准名称"""
        try:
            search_url = "https://aiqicha.baidu.com/s"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Referer': 'https://aiqicha.baidu.com/',
            }
            
            params = {'q': company_name}
            response = requests.get(search_url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(response.text, 'html.parser')
                
                company_elem = soup.select_one('.header-title-name')
                if company_elem:
                    standard_name = company_elem.get_text(strip=True)
                    credit_code = ''
                    credit_elem = soup.select_one('.basic-item-value')
                    if credit_elem:
                        credit_code = credit_elem.get_text(strip=True)
                    
                    return CompanyInfo(
                        input_name=company_name,
                        standard_name=standard_name,
                        credit_code=credit_code,
                        status='success',
                        source='api'
                    )
            return None
        except Exception as e:
            logger.error(f"爱企查查询失败 [{company_name}]: {e}")
            return None
    
    def _use_ai_normalize(self, company_name: str) -> Optional[CompanyInfo]:
        """使用AI模型推断公司全称（备用方案）"""
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=os.getenv('DASHSCOPE_API_KEY', os.getenv('DASHSCOPE_API_KEY')),
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
            
            prompt = f"""请将以下公司名称转换为其工商注册的标准全称。
如果是简称或别名，请返回其正式的工商注册名称。
如果无法确定，请返回原名称。

公司名称：{company_name}
请只返回公司全称，不要有任何其他内容。"""

            response = client.chat.completions.create(
                model="deepseek-v4-pro",
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.1,
                max_tokens=100
            )
            
            standard_name = response.choices[0].message.content.strip()
            if standard_name and len(standard_name) >= len(company_name) * 0.5:
                return CompanyInfo(
                    input_name=company_name,
                    standard_name=standard_name,
                    credit_code='',
                    status='success',
                    source='ai'
                )
            return None
        except Exception as e:
            logger.error(f"AI标准化失败 [{company_name}]: {e}")
            return None
    
    def normalize(self, company_name: str, use_api: bool = True) -> CompanyInfo:
        """将公司名称标准化为工商注册全称"""
        if not company_name or not company_name.strip():
            return CompanyInfo(company_name or '', company_name or '', '', 'error', 'none')
        
        company_name = company_name.strip()
        
        # 1. 先检查预置映射表
        core_name = self._extract_core_name(company_name)
        if core_name in self.known_mappings:
            return CompanyInfo(
                input_name=company_name,
                standard_name=self.known_mappings[core_name],
                credit_code='',
                status='success',
                source='preset'
            )
        
        # 2. 检查缓存
        cached = self._get_from_cache(company_name)
        if cached:
            logger.info(f"缓存命中: {company_name} -> {cached.standard_name}")
            return cached
        
        # 3. 如果名称已经看起来像全称，直接返回
        if any(suffix in company_name for suffix in ['有限公司', '股份有限公司', '有限责任公司']):
            info = CompanyInfo(
                input_name=company_name,
                standard_name=company_name,
                credit_code='',
                status='success',
                source='direct'
            )
            self._save_to_cache(info)
            return info
        
        # 4. 使用API查询
        if use_api:
            info = self._query_aiqicha(company_name)
            if info and info.status == 'success':
                self._save_to_cache(info)
                logger.info(f"API查询成功: {company_name} -> {info.standard_name}")
                return info
            
            info = self._use_ai_normalize(company_name)
            if info and info.status == 'success':
                self._save_to_cache(info)
                logger.info(f"AI推断成功: {company_name} -> {info.standard_name}")
                return info
        
        # 5. 都失败了，返回原名称
        info = CompanyInfo(
            input_name=company_name,
            standard_name=company_name,
            credit_code='',
            status='not_found',
            source='fallback'
        )
        self._save_to_cache(info)
        return info
    
    def normalize_batch(self, company_names: List[str], use_api: bool = True, 
                       delay: float = 0.5) -> List[CompanyInfo]:
        """批量标准化公司名称"""
        results = []
        for i, name in enumerate(company_names):
            info = self.normalize(name, use_api)
            results.append(info)
            
            if info.source == 'api' and i < len(company_names) - 1:
                time.sleep(delay)
            
            if (i + 1) % 10 == 0:
                logger.info(f"已处理 {i + 1}/{len(company_names)} 个公司")
        
        return results
    
    def deduplicate(self, company_names: List[str], use_api: bool = True) -> Tuple[List[str], Dict]:
        """对公司名称列表进行智能去重"""
        logger.info(f"开始去重，原始数量: {len(company_names)}")
        
        normalized = self.normalize_batch(company_names, use_api)
        
        groups = defaultdict(list)
        for info in normalized:
            groups[info.standard_name].append(info.input_name)
        
        unique_names = list(groups.keys())
        
        stats = {
            'original_count': len(company_names),
           'unique_count': len(unique_names),
            'duplicates_removed': len(company_names) - len(unique_names),
            'duplicate_groups': {k: v for k, v in groups.items() if len(v) > 1}
        }
        
        logger.info(f"去重完成: {stats['original_count']} -> {stats['unique_count']} "
                   f"(移除 {stats['duplicates_removed']} 个重复)")
        
        if stats['duplicate_groups']:
            logger.info("发现的重复组:")
            for standard, originals in stats['duplicate_groups'].items():
                logger.info(f"  {standard}: {originals}")
        
        return unique_names, n    
    def add_mapping(self, short_name: str, full_name: str):
        """手动添加简称->全称映射"""
        self.known_mappings[short_name] = full_name
        info = CompanyInfo(
            input_name=short_name,
            standard_name=full_name,
            credit_code='',
            status='success',
            source='manual'
        )
        self._save_to_cache(info)
        logger.info(f"已添加映射: {short_name} -> {full_name}")


def normalize_company_name(name: str) -> str:
    """便捷函数：标准化单个公司名称"""
    normalizer = CompanyNormalizer()
    return normalizer.normalize(name).standard_name


def deduplicate_companies(names: List[str]) -> List[str]:
    """便捷函数：去重公司名称列表"""
    normalizer = CompanyNormalizer()
    unique, _ = normalizer.deduplicate(names)
    return unique


if __name__ == '__main__':
    normalizer = CompanyNormalizer()
    
    test_names = [
        "华为", "华为技术有限公司",
        "宁德时代", "宁德时代新能源科技股份有限公司",
        "比亚迪", "蔚来", "小鹏汽车", "理想汽车", "特斯拉",
    ]
    
    print("=" * 60)
    print("公司名称标准化测试")
    print("=" * 60)
    
    for name in test_names:
        info = normalizer.normalize(name, use_api=False)
        print(f"{name:20} -> {info.standard_name:40} [{info.source}]")
    
    print("\n" + "=" * 60)
    print("去重测试")
    print("=" * 60)
    
    unique, stats = normalizer.deduplicate(test_names, use_api=False)
    print(f"\n去重结果: {len(test_names)} -> {len(unique)}")
    print(f"唯一公司: {unique}")
