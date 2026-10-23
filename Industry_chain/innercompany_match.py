import os
import pandas as pd
import pymysql
from openai import OpenAI
import json
import time
import re
import jieba
import logging
from collections import defaultdict

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("matching_log.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

# 数据库配置
db_config = {
    'user': 'remote_user',
    'password': os.getenv('DB_PASSWORD_REMOTE'),
    'host': '8.141.23.4',
    'database': 'business_data'
}

# 连接数据库
try:
    conn = pymysql.connect(**db_config)
    logger.info("成功连接数据库")
    
    # 读取客户需求数据
    customer_query = """
    SELECT 客户名称, 询盘商品, 商品分类, 询盘型号 
    FROM customer_needs_lianshangugu
    WHERE 询盘商品 IS NOT NULL AND 询盘商品 != ''
    """
    customers_df = pd.read_sql(customer_query, conn)
    logger.info(f"读取客户数据完成，共 {len(customers_df)} 条记录")
    
    # 读取公司数据
    company_query = """
    SELECT entity_name, sells_park_name, product_name, business_scope 
    FROM inner_company_withproduct
    WHERE product_name IS NOT NULL AND product_name != ''
    """
    companies_df = pd.read_sql(company_query, conn)
    logger.info(f"读取公司数据完成，共 {len(companies_df)} 条记录")
    
except Exception as e:
    logger.error(f"数据库连接或查询失败: {e}")
    raise
finally:
    conn.close()
    logger.info("数据库连接已关闭")

# 数据清洗
def clean_text(text):
    """清理文本数据"""
    if pd.isna(text):
        return ""
    # 移除特殊字符和多余空格
    text = re.sub(r'[^\w\s]', '', str(text))
    return re.sub(r'\s+', ' ', text).strip()

# 应用清洗
customers_df['询盘商品'] = customers_df['询盘商品'].apply(clean_text)
customers_df['商品分类'] = customers_df['商品分类'].apply(clean_text)
customers_df['询盘型号'] = customers_df['询盘型号'].apply(clean_text)
companies_df['product_name'] = companies_df['product_name'].apply(clean_text)
companies_df['business_scope'] = companies_df['business_scope'].apply(clean_text)

# 构建关键词索引（更智能的匹配）
logger.info("构建公司关键词索引...")
company_keywords = defaultdict(list)

# 使用jieba分词提取关键词
def extract_keywords(text):
    """提取关键词"""
    if not text:
        return []
    # 使用jieba分词
    words = jieba.cut(text)
    # 过滤停用词和短词
    return [word for word in words if len(word) > 1]

# 构建公司关键词映射
for idx, row in companies_df.iterrows():
    keywords = set()
    # 从产品名提取关键词
    keywords.update(extract_keywords(row['product_name']))
    # 从业务范围提取关键词
    keywords.update(extract_keywords(row['business_scope']))
    
    # 添加到索引
    for keyword in keywords:
        company_keywords[keyword].append(idx)

#品牌，型号必须一致
#业务范围不能单独作为判断标准必须结合产品
# 大模型提示词模板
MATCH_PROMPT = """
## 任务说明
你是一名专业的商业配对分析师，需要根据客户的采购需求，从候选公司中筛选最匹配的供应商。
请严格按以下规则匹配：
1. 核心产品匹配：候选公司的product_name必须与客户"询盘商品"高度相关
2. 业务范围覆盖：候选公司的business_scope必须能覆盖客户的商品分类需求
3. 特殊要求：若客户有"询盘型号"，候选公司产品需具备对应型号能力

## 输出要求
1. 返回JSON格式：{{"matches": [{{"company": "公司名", "reason": "匹配原因"}}]}}
2. 最多返回3个最佳匹配
3. 若无匹配返回空列表
4. 匹配原因需包含具体匹配的产品/业务点

## 当前匹配任务
客户需求：
- 客户名称：{customer_name}
- 询盘商品：{product}
- 商品分类：{category}
- 询盘型号：{model}

候选公司列表（最多10家）：
{candidate_companies}
"""

# MATCH_PROMPT = """
# ## 任务说明
# 您是一名专业的商业配对分析师，需要根据客户的采购需求，从候选公司中筛选最匹配的供应商。
# 请严格按以下优先级规则匹配：

# ### 强制匹配条件（必须全部满足）
# 1. 品牌一致性（当询盘品牌存在时）：
#    - 若客户提供"询盘品牌"，候选公司产品品牌必须完全一致
#    - 品牌匹配优先级：产品品牌字段 > 产品名称中的品牌词

# 2. 型号精确匹配（当询盘型号存在时）：
#    - 若客户提供"询盘型号"，候选公司产品型号必须完全一致
#    - 型号匹配需同时验证型号字段和产品描述

# 3. 核心产品匹配：
#    - 候选公司的product_name必须与客户"询盘商品"高度相关
#    - 产品相关性判定标准：关键词覆盖度 > 产品类别匹配度

# 4. 业务协同验证：
#    - 候选公司的business_scope必须包含客户商品分类
#    - 业务范围验证必须结合产品匹配共同判断

# ## 输出要求
# 1. 返回严格JSON格式：{"matches": [{"company": "公司名", "reason": "匹配原因"}]}
# 2. 匹配原因必须包含：
#    - 品牌匹配状态（如："品牌完全匹配：华为"）
#    - 型号匹配状态（如："型号完全匹配：RTX4090"）
#    - 核心产品匹配证据
#    - 业务范围协同验证说明
# 3. 筛选规则：
#    - 任一强制条件不满足立即淘汰
#    - 最多返回3家最佳匹配
#    - 无合格匹配时返回空列表

# ## 当前匹配任务
# 客户需求：
# - 客户名称：{customer_name}
# - 询盘商品：{product}
# - 商品分类：{category}
# - 询盘型号：{model}
# - 询盘品牌：{brand}  # 新增独立品牌字段

# 候选公司列表（最多10家）：
# {candidate_companies}
# """

# 大模型客户端配置
client = OpenAI(
    api_key=os.getenv("VOLCENGINE_ARK_API_KEY"),
    base_url="https://ark.cn-beijing.volces.com/api/v3",
)

def get_ai_match(customer_data, candidates):
    """调用大模型进行匹配"""
    # 构建候选公司文本
    candidate_text = "\n".join([
        f"{idx+1}. {row['entity_name']} | 产品:{row['product_name']} | 业务:{row['business_scope']}"
        for idx, row in candidates.iterrows()
    ])
    
    # 填充提示词
    model_value = customer_data['询盘型号'] if pd.notna(customer_data['询盘型号']) and customer_data['询盘型号'] else "无"
    category_value = customer_data['商品分类'] if pd.notna(customer_data['商品分类']) and customer_data['商品分类'] else "无"
    
    prompt = MATCH_PROMPT.format(
        customer_name=customer_data['客户名称'],
        product=customer_data['询盘商品'],
        category=category_value,
        model=model_value,
        candidate_companies=candidate_text
    )
    
    # 调用大模型
    try:
        response = client.chat.completions.create(
            model="ep-20250217153205-d7px5",
            messages=[
                {'role': 'system', 'content': '你是有20年经验的国际贸易匹配专家'},
                {'role': 'user', 'content': prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,  # 降低随机性
            max_tokens=500,
            timeout=30  # 增加超时时间
        )
        response_text = response.choices[0].message.content

        response_text = response_text.replace("```", "").replace("json", "")
        print(response_text)
        
        # 尝试解析JSON
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}\n响应内容: {response_text}")
            return {"matches": []}
            
    except Exception as e:
        logger.error(f"API调用失败: {e}")
        return {"matches": []}

def find_candidate_companies(customer_product):
    """更智能地查找候选公司"""
    # 提取客户关键词
    customer_keywords = extract_keywords(customer_product)
    
    # 如果没有关键词，返回空
    if not customer_keywords:
        return pd.DataFrame()
    
    # 查找匹配的公司ID
    matched_indices = set()
    for keyword in customer_keywords:
        if keyword in company_keywords:
            matched_indices.update(company_keywords[keyword])
    
    # 如果找到匹配的公司，返回前10家
    if matched_indices:
        return companies_df.loc[list(matched_indices)].head(10)
    
    # 如果没有直接匹配，尝试模糊匹配
    logger.info(f"尝试模糊匹配: {customer_product}")
    pattern = re.compile(rf"{'|'.join(customer_keywords)}", re.IGNORECASE)
    mask = companies_df.apply(
        lambda row: bool(pattern.search(row['product_name'])) or 
        bool(pattern.search(row['business_scope'])),
        axis=1
    )
    return companies_df[mask].head(10)

# 主处理函数
def match_partners(customers_df, companies_df, batch_size=100, max_retries=3):
    results = []
    total = len(customers_df)
    processed_count = 0
    
    for idx, customer in customers_df.iterrows():
        retry_count = 0
        success = False
        
        while retry_count < max_retries and not success:
            try:
                # 1. 查找候选公司
                candidates = find_candidate_companies(customer['询盘商品'])
                
                if len(candidates) == 0:
                    logger.info(f"客户 {customer['客户名称']} 询盘商品 '{customer['询盘商品']}' 没有找到候选公司")
                    success = True
                    continue
                    
                # 2. 调用大模型精准匹配
                matches = get_ai_match(customer, candidates)
                
                # 3. 记录结果
                for match in matches.get('matches', []):
                    # 获取匹配公司的详细信息
                    matched_company = candidates[candidates['entity_name'] == match['company']]
                    if not matched_company.empty:
                        company_info = matched_company.iloc[0]
                        results.append({
                            "客户名称": customer['客户名称'],
                            "匹配公司": match['company'],
                            "询盘商品": customer['询盘商品'],
                            "商品分类": customer['商品分类'],
                            "询盘型号": customer['询盘型号'],
                            "匹配原因": match['reason'],
                            "园区名字": company_info['sells_park_name'],
                            "产品名称": company_info['product_name'],
                            "业务范围": company_info['business_scope']
                        })
                
                success = True
                processed_count += 1
                
            except Exception as e:
                logger.error(f"处理客户 {customer['客户名称']} 时出错: {e}")
                retry_count += 1
                if retry_count < max_retries:
                    logger.info(f"重试 {retry_count}/{max_retries}...")
                    time.sleep(2)  # 重试前等待
        
        # 进度保存/打印
        if (idx+1) % batch_size == 0:
            logger.info(f"已处理 {idx+1}/{total} 条，成功 {processed_count} 条，当前匹配 {len(results)} 组")
            # 保存临时结果
            if results:
                pd.DataFrame(results).to_excel(f"匹配结果_批次{(idx+1)//batch_size}.xlsx", index=False)
            
        # 避免速率限制
        time.sleep(0.5)
    
    return pd.DataFrame(results)

# 执行匹配
logger.info(f"开始匹配，客户数量: {len(customers_df)}, 公司数量: {len(companies_df)}")
try:
    # 先用100条数据测试
    sample_customers = customers_df.head(12922)
    result_df = match_partners(sample_customers, companies_df, batch_size=20)
    
    # 保存最终结果
    if not result_df.empty:
        result_df.to_excel("客户-供应商匹配结果0701.xlsx", index=False)
        logger.info(f"匹配完成！共生成 {len(result_df)} 组匹配")
    else:
        logger.warning("未生成任何匹配结果")
        
except Exception as e:
    logger.error(f"匹配过程发生严重错误: {e}")
    # 尝试保存当前结果
    if 'result_df' in locals() and not result_df.empty:
        result_df.to_excel("部分匹配结果.xlsx", index=False)
        logger.info("已保存部分结果")