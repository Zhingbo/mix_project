"""
更新企业名称为全称

功能：
1. 读取 company_nodes_finallist0421.xlsx
2. 识别简称/全称
3. 对简称调用 DeepSeek API 转换为全称（多线程）
4. 处理同一企业既有全称又有简称：保留记录数多的版本，删除另一个
5. 更新为企业全称
"""
import os

import pandas as pd
import json
from openai import OpenAI
from tqdm import tqdm
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# ==================== API 配置 ====================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# ==================== 多线程配置 ====================
MAX_WORKERS = 20
INPUT_FILE = "/root/mix_project/company_nodes_finallist0421.xlsx"
OUTPUT_FILE = "/root/mix_project/company_nodes_finallist_updated.xlsx"

# ==================== 系统提示词 ====================
SYSTEM_PROMPT = """你是一个企业信息查询专家。你的任务是根据用户输入的企业简称，返回该企业的完整工商注册名称。

重要规则：
1. 必须返回公司的完整工商注册名称，包含"有限公司"、"股份有限公司"、"集团"等后缀
2. 如果不确定公司全称，请尽量返回最可能的全称
3. 只返回公司名称，不要添加任何额外解释

请以 JSON 格式返回：
{
    "企业全称": "华为技术有限公司"
}
"""


# 常见公司后缀，用于判断是否为全称
FULL_NAME_SUFFIXES = [
    '股份有限公司', '有限责任公司', '有限公司',
    '集团有限公司', '集团股份有限公司',
    '（中国）', '(中国)', '（上海）', '(上海)',
    '（北京）', '(北京)', '（深圳）', '(深圳)',
    '（广州）', '(广州)', '公司'
    # 移除 "集团"，让 "XX集团" 也作为简称查询
]


def is_full_name(company_name):
    """判断企业名称是否为全称"""
    if pd.isna(company_name) or not company_name:
        return False
    for suffix in FULL_NAME_SUFFIXES:
        if suffix in company_name:
            return True
    return False


def get_full_company_name(company_short_name):
    """使用 DeepSeek API 查询企业全称"""
    try:
        client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL
        )

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': f'请查询企业的完整名称：{company_short_name}'}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )

        result = response.choices[0].message.content
        result = result.replace("```json", "").replace("```", "").strip()
        result_json = json.loads(result)

        return result_json.get('企业全称', company_short_name)

    except Exception as e:
        print(f"  API查询失败 [{company_short_name}]: {e}")
        return company_short_name


def query_single_company(short_name):
    """单个企业查询（用于多线程）"""
    full_name = get_full_company_name(short_name)
    return {short_name: full_name}


def extract_core_name(company_name):
    """提取公司核心名称（用于匹配同一家公司）"""
    import re
    core_name = company_name
    for suffix in FULL_NAME_SUFFIXES:
        core_name = core_name.replace(suffix, '')
    core_name = re.sub(r'[（(][^）)]*[）)]', '', core_name)
    return core_name.strip()


def process_companies(df):
    """处理企业名称"""
    print("=" * 80)
    print("处理企业名称")
    print("=" * 80)

    print(f"原始记录数: {len(df)}")
    unique_companies = df['company_name'].nunique()
    print(f"唯一企业数: {unique_companies}")

    # 1. 按唯一企业名称分类：全称 vs 简称
    unique_names = df['company_name'].unique()
    is_full_mapping = {name: is_full_name(name) for name in unique_names}

    full_name_count = sum(is_full_mapping.values())
    short_name_count = len(unique_names) - full_name_count

    print(f"全称企业: {full_name_count} 个, 简称企业: {short_name_count} 个")

    # 2. 对简称调用 API 获取全称（多线程）
    short_names = [name for name, is_full in is_full_mapping.items() if not is_full]
    print(f"\n需要查询的简称企业数: {len(short_names)}")
    print(f"并发线程数: {MAX_WORKERS}")

    name_mapping = {}  # 简称 -> API查询的全称
    name_mapping_lock = threading.Lock()

    def update_mapping(result):
        """更新映射结果的线程安全函数"""
        with name_mapping_lock:
            name_mapping.update(result)

    if short_names:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(query_single_company, name): name for name in short_names}

            with tqdm(total=len(short_names), desc="查询简称") as pbar:
                for future in as_completed(futures):
                    result = future.result()
                    update_mapping(result)
                    pbar.update(1)

    # 3. 确定每个企业保留哪个名称版本（记录数多的优先）
    print("\n确定企业保留版本...")
    df['core_name'] = df['company_name'].apply(extract_core_name)

    # 统计每个（核心名称, 原始名称）的记录数
    name_count = df.groupby(['core_name', 'company_name']).size().reset_index(name='count')

    # 对每个核心名称，选择保留的原始名称（记录数多的优先）
    keep_names = {}  # core_name -> 要保留的原始名称
    final_names = {}  # core_name -> 最终的企业全称

    for core_name in df['core_name'].unique():
        core_df = name_count[name_count['core_name'] == core_name]

        # 选择记录数最多的原始名称
        max_count_name = core_df.nlargest(1, 'count')['company_name'].values[0]
        keep_names[core_name] = max_count_name

        # 确定最终全称：
        # 如果保留的是简称，尝试用 API 结果或找到对应的全称
        if not is_full_name(max_count_name):
            # 优先使用 API 查询结果
            if max_count_name in name_mapping:
                final_names[core_name] = name_mapping[max_count_name]
            else:
                # 查看该核心名称下是否有全称
                full_names_in_core = core_df[core_df['company_name'].apply(is_full_name)]['company_name'].tolist()
                if full_names_in_core:
                    final_names[core_name] = full_names_in_core[0]  # 取第一个全称
                else:
                    final_names[core_name] = max_count_name
        else:
            final_names[core_name] = max_count_name

    # 4. 只保留选中的名称版本的记录，删除其他版本
    print(f"删除重复版本...")
    df_final = df[df['company_name'].isin(keep_names.values())].copy()

    removed_count = len(df) - len(df_final)
    print(f"删除了 {removed_count} 条记录")

    # 5. 更新为企业全称
    print("\n更新企业全称...")
    df_final['company_name_updated'] = df_final['core_name'].map(final_names)

    updated_count = (df_final['company_name'] != df_final['company_name_updated']).sum()
    print(f"更新了 {updated_count} 条记录的企业名称")

    # 清理临时列，重命名
    df_result = df_final.drop(columns=['company_name', 'core_name'])
    df_result = df_result.rename(columns={'company_name_updated': 'company_name'})

    return df_result


def main():
    print("=" * 80)
    print("更新企业名称为全称")
    print("=" * 80)
    print(f"输入文件: {INPUT_FILE}")
    print(f"输出文件: {OUTPUT_FILE}")

    # 读取 Excel
    print("\n读取文件...")
    df = pd.read_excel(INPUT_FILE)
    print(f"原始记录数: {len(df)}")

    # 处理
    df_updated = process_companies(df)

    # 保存结果
    print("\n保存结果...")
    df_updated.to_excel(OUTPUT_FILE, index=False, engine='openpyxl')
    print(f"更新完成，共 {len(df_updated)} 条记录")
    print(f"输出文件: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
