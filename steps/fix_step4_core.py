# -*- coding: utf-8 -*-
# 给 step4 加"链核心概念词"正向过滤(防爆炸): 匹配到的企业名称/经营范围需含该链核心词
import io

CORE_FN = '''

def _generate_core_keywords(industry_name: str, node_names: list) -> list:
    """让 LLM 生成该链的"核心概念词"——该链企业名称/经营范围里应包含的关键词(正向过滤, 防爆炸)"""
    try:
        client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        node_list = "、".join([str(n) for n in node_names[:80] if str(n) not in ('', 'nan')])
        user_msg = (
            f"产业链名称：{industry_name}\\n"
            f"产业链节点（环节）：{node_list}\\n\\n"
            f"请判断：属于「{industry_name}」产业链的企业，其企业名称或经营范围（产品/业务描述）里通常会包含哪些核心概念词？\\n"
            f"例如：可控核聚变 → 超导、核聚变、托卡马克、等离子体、磁约束、聚变堆；生命健康 → 医药、医疗、医院、制药。\\n"
            f"要求：\\n"
            f"1. 只给能区分「该链企业」和「其它行业企业」的高区分度词，2~8 个汉字；\\n"
            f"2. 不要给"制造/设备/科技/工程/系统/材料/能源"这类几乎所有工业都有的泛词；\\n"
            f"3. 宁缺毋滥，给 5~15 个核心词即可；\\n"
            f"4. 按 JSON 输出：{{\\"core_keywords\\": [\\"词1\\", \\"词2\\", ...]}}"
        )
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是产业链分析专家，负责给出该产业链企业必备的核心概念关键词。"},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        raw = resp.choices[0].message.content
        data = json.loads(raw)
        kws = data.get("core_keywords", []) if isinstance(data, dict) else []
        kws = [str(k).strip() for k in kws if str(k).strip()]
        kws = [k for k in dict.fromkeys(kws) if 2 <= len(k) <= 12 and ' ' not in k and '，' not in k and ',' not in k]
        return kws
    except Exception as e:
        print(f"LLM 核心词生成失败: {e}，跳过核心词过滤")
        return []
'''

def fix(p):
    s = open(p, encoding="utf-8").read()
    # 1) 在 _generate_exclusion_keywords 之后插入 _generate_core_keywords
    anchor = "    except Exception as e:\n        print(f\"LLM 反向排除词生成失败: {e}，跳过反向过滤\")\n        return []\n"
    if anchor in s and "_generate_core_keywords" not in s:
        s = s.replace(anchor, anchor + CORE_FN, 1)
        print(p, "核心词函数已插入")
    else:
        print(p, "核心词函数已存在或锚点未找到")

    # 2) 在 domain_filter 构建后生成核心词
    anchor2 = '    domain_filter = f"AND a.industry_class_first IN ({quoted})"\n    else:\n        domain_filter = ""\n'
    gen2 = ('    domain_filter = f"AND a.industry_class_first IN ({quoted})"\n'
            '    else:\n'
            '        domain_filter = ""\n'
            '\n'
            '    # 生成该链核心概念词(正向过滤, 防爆炸)\n'
            '    core_names = list(dict.fromkeys([str(r[\'name\']) for _, r in nodes_rows]))\n'
            '    core_kws = _generate_core_keywords(industry_name, core_names)\n'
            '    if core_kws:\n'
            '        core_re = "|".join(re.escape(k) for k in core_kws)\n'
            '        core_filter = f"AND (a.company_name REGEXP \'{core_re}\' OR a.explain REGEXP \'{core_re}\')"\n'
            '        print(f"链核心词({len(core_kws)}): {core_kws}")\n'
            '    else:\n'
            '        core_re = ""\n'
            '        core_filter = ""\n'
            '        print("未生成核心词，跳过核心词过滤(可能爆炸)")\n')
    if anchor2 in s and "core_filter" not in s:
        s = s.replace(anchor2, gen2, 1)
        print(p, "核心词生成已接入")
    else:
        print(p, "核心词生成已存在或锚点未找到")

    # 3) 在 _match_one_node 的 SQL 里加 core_filter
    anchor3 = "          (a.industry_class_third LIKE '%强%' OR a.industry_class_third LIKE '%中%')\n          {domain_filter}\n"
    if anchor3 in s and "{core_filter}" not in s:
        s = s.replace(anchor3, "          (a.industry_class_third LIKE '%强%' OR a.industry_class_third LIKE '%中%')\n          {domain_filter}\n          {core_filter}\n", 1)
        print(p, "SQL 已加 core_filter")
    else:
        print(p, "SQL core_filter 已存在或锚点未找到")

    open(p, "w", encoding="utf-8").write(s)

for p in ("step4_company_match_nodes.py", "step4_company_match_nodes_v2.py"):
    fix(p)
print("完成")