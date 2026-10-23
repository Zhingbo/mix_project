"""
测试 DeepSeek API 查询企业全称

功能：
输入企业简称，通过 DeepSeek API 查询企业完整名称
"""
import os

import json
from openai import OpenAI

# ==================== API 配置 ====================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# ==================== 测试用例（写死） ====================
TEST_COMPANY = "上海交通大学氢科学中心"  # 修改这里测试不同企业

# ==================== 系统提示词 ====================
SYSTEM_PROMPT = """你是一个企业信息查询专家。你的任务是根据用户输入的企业/组织简称，返回该企业/组织的完整官方名称。

重要规则：
1. 必须返回完整的官方注册名称，包含"有限公司"、"股份有限公司"、"集团"、"中心"、"研究所"等完整后缀
2. 如果是大学/科研院所的附属机构，必须包含母体机构的完整名称
3. 特别注意：
   - "一汽集团" → "中国第一汽车集团有限公司"
   - "上汽集团" → "上海汽车集团股份有限公司"
   - "交大氢科学中心" → "上海交通大学氢科学中心有限公司" 或 "上海交通大学"
4. 如果输��的名称已经是完整官方名称，则原样返回

请以 JSON 格式返回：
{
    "企业全称": "华为技术有限公司"
}
"""


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

        print(f"\n输入: {company_short_name}")
        print(f"全称: {result_json.get('企业全称', '未找到')}")

        return result_json

    except Exception as e:
        print(f"查询失败: {e}")
        return None


if __name__ == "__main__":
    print("=" * 60)
    print("DeepSeek API 查询企业全称测试")
    print("=" * 60)

    get_full_company_name(TEST_COMPANY)
