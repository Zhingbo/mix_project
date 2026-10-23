# -*- coding: utf-8 -*-
# step6: 榜单企业搜出来后, 底表查不到行业/产品的, 用 DeepSeek 补企业画像(细分行业+主营产品)
import sys
P = "/root/mix_project/steps/step6_top_company_match.py"
s = open(P, encoding="utf-8").read()

# 1. 改函数签名
old_sig = '''def _batch_lookup_company_info(company_names: List[str]) -> Dict[str, dict]:
    """批量查询企业真实业务信息（一次连接、IN 查询，替代逐家建连接）"""'''
new_sig = '''def _batch_lookup_company_info(company_names: List[str], industry_name: str = None) -> Dict[str, dict]:
    """批量查询企业真实业务信息；底表查不到的用 DeepSeek 补行业/产品"""'''
if old_sig not in s:
    print("[FAIL] 未找到函数签名"); sys.exit(1)
s = s.replace(old_sig, new_sig, 1)
print("[ok] 签名已改")

# 2. 结尾加兜底
old_end = '''    logging.info(f"批量查询企业信息: 请求 {len(company_names)} 家，命中 {len(info_map)} 家")
    return info_map'''
new_end = '''    logging.info(f"批量查询企业信息: 请求 {len(company_names)} 家，命中 {len(info_map)} 家")

    # 兜底: 底表没命中的企业, 用 DeepSeek 补行业/产品(便于更精准挂载)
    missing = [n for n in company_names if n and n not in info_map]
    if missing:
        logging.info(f"底表未命中 {len(missing)} 家, 改用 DeepSeek 补行业/产品")
        for i in range(0, len(missing), 50):
            batch = missing[i:i + 50]
            try:
                info_map.update(_llm_enrich_company_info(batch, industry_name))
            except Exception as e:
                logging.warning(f"DeepSeek 补行业/产品失败: {e}")
    return info_map'''
if old_end not in s:
    print("[FAIL] 未找到函数结尾"); sys.exit(1)
s = s.replace(old_end, new_end, 1)
print("[ok] 兜底已加")

# 3. 插入 _llm_enrich_company_info 函数(在 _batch_lookup_company_info 之前)
anchor = '''def _batch_lookup_company_info(company_names: List[str], industry_name: str = None) -> Dict[str, dict]:'''
newfunc = '''def _llm_enrich_company_info(company_names: List[str], industry_name: str = None) -> Dict[str, dict]:
    """用 DeepSeek 批量生成企业细分行业 + 主营产品(底表查不到时的兜底)"""
    if not company_names:
        return {}
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    names = "\\n".join(company_names)
    prompt = (f'你是企业信息专家。请根据每家企业名称，判断其所属细分行业和主营产品。\\n'
              f'输出JSON：{{"companies":[{{"name":"企业全称","industry":"细分行业","product":"主营产品一句话"}}]}}\\n'
              f'行业尽量具体(如基因检测/创新药/生物试剂/CDMO/医学影像/半导体设备)，不要只写大类。\\n'
              f'企业列表：\\n{names}')
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or ""
        obj = json.loads(raw.replace("```json", "").replace("```", "").strip())
        out = {}
        for c in obj.get("companies", []):
            nm = str(c.get("name", "")).strip()
            if nm:
                prod = str(c.get("product", "")).strip()
                ind = str(c.get("industry", "")).strip()
                out[nm] = {
                    "product": prod,
                    "business": prod,
                    "industry": ind,
                    "industry_class": "",
                }
        return out
    except Exception as e:
        logging.warning(f"DeepSeek 企业画像生成失败: {e}")
        return {}


''' + anchor
if anchor not in s:
    print("[FAIL] 未找到插入锚点"); sys.exit(1)
s = s.replace(anchor, newfunc, 1)
print("[ok] 函数已插入")

# 4. 调用处传 industry_name
old_call = '''    company_info_map = _batch_lookup_company_info(company_names_list)'''
new_call = '''    company_info_map = _batch_lookup_company_info(company_names_list, industry_name)'''
if old_call not in s:
    print("[FAIL] 未找到调用行"); sys.exit(1)
s = s.replace(old_call, new_call, 1)
print("[ok] 调用处已传 industry_name")

open(P, "w", encoding="utf-8").write(s)
print("[done]")