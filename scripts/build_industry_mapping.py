"""
国标行业分类(B口径) → 联东项目自定义口径(A口径) 映射脚本

用途:
    ent_industry_class_new.industry_class_third 用的是国标《国民经济行业分类》口径,
    而项目现有 ent_industry_class_old / mapping_industry_info_new / ent_industry_label 用的是
    联东自定义口径(13个一级领域: 机械设备与零件/传统制造业/大健康/...).
    两者口径不一致, 直接切换 ent_industry_class_new 会导致 step4 正则匹配率暴跌.

    本脚本用 DeepSeek 语义匹配, 为 418 条国标 full_name 各找到 1 个(或多个) A口径 full_name,
    产出映射对照表 industry_mapping_gb_to_custom.csv.

    只读: 不动数据库, 不动项目代码. 产出物是本目录下的 CSV/JSON.

成本:
    418 条国标 + 703 条锚点一次性塞入 prompt, 约 1 次 API 调用, 成本 < ¥1.
    若单次输出不稳定, 自动分批重试.

用法:
    cd /root/mix_project/scripts
    source /root/acemcp/.venv/bin/activate   # 或项目用的 conda 环境
    python build_industry_mapping.py

输入文件(已存在):
    /root/mix_project/materials/gb_industry_keys_from_new.csv        # 418 条国标 full_name
    /root/mix_project/materials/a_custom_label_ent_industry_label.csv # 703 条A口径锚点(带定义)

输出文件:
    /root/mix_project/materials/industry_mapping_gb_to_custom.csv   # 映射对照表
    /root/mix_project/materials/industry_mapping_gb_to_custom.json  # JSON 版, 供转换脚本读
"""

import csv
import json
import os
import sys
import time
import re
from typing import List, Dict, Optional

from openai import OpenAI

# ============== 配置 ==============
MATERIALS_DIR = "/root/mix_project/materials"
GB_KEYS_FILE = os.path.join(MATERIALS_DIR, "gb_industry_keys_from_new.csv")
A_LABEL_FILE = os.path.join(MATERIALS_DIR, "a_custom_label_ent_industry_label.csv")
OUTPUT_CSV = os.path.join(MATERIALS_DIR, "industry_mapping_gb_to_custom.csv")
OUTPUT_JSON = os.path.join(MATERIALS_DIR, "industry_mapping_gb_to_custom.json")
RAW_RESPONSE_FILE = os.path.join(MATERIALS_DIR, "industry_mapping_raw_response.json")

# DeepSeek 配置 (与项目生产一致: 阿里云百炼 DashScope 兼容模式)
API_KEY = os.getenv("DASHSCOPE_API_KEY")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "deepseek-v4-pro"

# 分批大小: 418 条一次塞入即可; 若输出截断则自动降到 50 一批
BATCH_SIZE = 50
MAX_RETRIES = 3
RETRY_WAIT = 5


def load_gb_keys() -> List[str]:
    """加载国标 full_name 清单"""
    keys = []
    with open(GB_KEYS_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fn = row.get("full_name", "").strip()
            if fn:
                keys.append(fn)
    # 去重保序
    seen = set()
    out = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def load_a_labels() -> List[Dict]:
    """加载A口径锚点 (带定义)"""
    labels = []
    with open(A_LABEL_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            labels.append({
                "full_name": row.get("full_name", "").strip(),
                "level": row.get("level", "").strip(),
                "annotation": row.get("annotation", "").strip(),
            })
    # 只用 level=3 的叶子节点做映射目标 (full_name 是三级完整路径)
    # 但也保留 level1/2 供模型理解层级
    return labels


def build_prompt(gb_batch: List[str], a_full_names: List[str]) -> str:
    """构造映射 prompt (只传 full_name 不传定义, 控制输入长度)"""
    a_block = "\n".join(f'- "{n}"' for n in a_full_names)
    gb_block = "\n".join(f'{i+1}. "{k}"' for i, k in enumerate(gb_batch))

    prompt = f"""你是行业分类映射专家。为每条【国标行业分类】在【联东口径】清单中找1个语义最匹配的。

【联东口径清单】(必须严格从中选, 不可创造新值):
{a_block}

【国标清单】(共{len(gb_batch)}条, 逐条映射):
{gb_block}

规则:
1. 每条国标映射到1个联东full_name, 多对一可以.
2. 实在没有就填"无".
3. 只能从联东清单选.

返回JSON数组, 每元素:
{{"gb_full_name":"国标完整路径","match_to":"联东完整路径或无","reason":"一句理由"}}
只返回JSON数组."""
    return prompt


def call_deepseek(client: OpenAI, prompt: str) -> Optional[str]:
    """调用 DeepSeek, 返回原始文本"""
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "你是一个行业分类映射专家, 严格按照要求返回JSON数组, 不要包裹在对象里, 直接返回 [...] 形式."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=16000,
        )
        return resp.choices[0].message.content
    except Exception as e:
        print(f"  API 调用失败: {e}")
        return None


def parse_response(raw: str, gb_batch: List[str]) -> List[Dict]:
    """解析返回, 容错多种 JSON 包裹形式"""
    if not raw:
        return []
    text = raw.strip()
    # 去掉 ```json ... ``` 包裹
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 尝试提取首个 [ ... ]
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                print(f"  JSON 解析失败, 原始前500字: {text[:500]}")
                return []
        else:
            print(f"  JSON 解析失败, 原始前500字: {text[:500]}")
            return []
    # data 可能是 list, 也可能是单条 dict, 也可能被包成 {"mappings": [...]} 等
    if isinstance(data, dict):
        # 单条 dict (gb_full_name/match_to/reason)
        if "gb_full_name" in data and "match_to" in data:
            data = [data]
        else:
            for key in ("mappings", "mapping", "results", "data", "list"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
    if not isinstance(data, list):
        print(f"  返回非list, 类型={type(data)}")
        return []
    # 校验: 每个 gb_full_name 都在本批内
    batch_set = set(gb_batch)
    out = []
    for item in data:
        gb = item.get("gb_full_name", "").strip()
        mt = item.get("match_to", "").strip()
        reason = item.get("reason", "").strip()
        if gb in batch_set:
            out.append({"gb_full_name": gb, "match_to": mt, "reason": reason})
    return out


def main():
    print("=" * 60)
    print("国标行业分类 → 联东自定义口径 映射脚本")
    print("=" * 60)

    gb_keys = load_gb_keys()
    a_labels = load_a_labels()
    print(f"国标清单: {len(gb_keys)} 条")
    print(f"A口径锚点: {len(a_labels)} 条")
    print(f"输出: {OUTPUT_CSV}")

    # A 口径可用 full_name 集合 (用于校验和prompt)
    a_full_names = sorted(set(a["full_name"] for a in a_labels))

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    all_mappings: List[Dict] = []
    raw_responses: List[Dict] = []

    # 分批
    batches = [gb_keys[i:i + BATCH_SIZE] for i in range(0, len(gb_keys), BATCH_SIZE)]
    print(f"分 {len(batches)} 批, 每批上限 {BATCH_SIZE}")

    for bi, batch in enumerate(batches):
        print(f"\n--- 批 {bi+1}/{len(batches)} ({len(batch)} 条) ---")
        prompt = build_prompt(batch, a_full_names)
        # 估算输入 token (粗略: 1汉字≈2token)
        approx_in = len(prompt) * 2
        print(f"  prompt 长度 {len(prompt)} 字, 约输入 {approx_in} token")

        success = False
        for attempt in range(1, MAX_RETRIES + 1):
            print(f"  尝试 {attempt}/{MAX_RETRIES} ...")
            raw = call_deepseek(client, prompt)
            if raw:
                raw_responses.append({"batch": bi, "attempt": attempt, "raw": raw})
                parsed = parse_response(raw, batch)
                print(f"  解析得到 {len(parsed)} 条映射")
                if len(parsed) == len(batch):
                    all_mappings.extend(parsed)
                    success = True
                    break
                elif len(parsed) > 0:
                    # 部分成功, 先存着, 继续重试补
                    all_mappings.extend(parsed)
                    success = True
                    # 但要找出缺失的
                    got = set(p["gb_full_name"] for p in parsed)
                    missing = [k for k in batch if k not in got]
                    if missing:
                        print(f"  缺失 {len(missing)} 条, 用空映射兜底")
                        for m in missing:
                            all_mappings.append({"gb_full_name": m, "match_to": "无", "reason": "API未返回, 待人工复核"})
                    break
            time.sleep(RETRY_WAIT)

        if not success:
            print(f"  批 {bi+1} 全部重试失败, 用空映射兜底")
            for k in batch:
                all_mappings.append({"gb_full_name": k, "match_to": "无", "reason": "API失败, 待人工复核"})

    # 去重: 同一 gb_full_name 保留第一条
    seen = set()
    deduped = []
    for m in all_mappings:
        if m["gb_full_name"] not in seen:
            seen.add(m["gb_full_name"])
            deduped.append(m)
    all_mappings = deduped

    # 校验 match_to 是否都在 A 口径里
    bad = 0
    for m in all_mappings:
        if m["match_to"] != "无" and m["match_to"] not in a_full_names:
            print(f"  校验失败: '{m['match_to']}' 不在A口径, gb={m['gb_full_name']}")
            m["match_to"] = "无(原值不在A口径:" + m["match_to"] + ")"
            bad += 1

    print(f"\n=== 汇总 ===")
    print(f"总映射: {len(all_mappings)}")
    matched = sum(1 for m in all_mappings if m["match_to"] not in ("无", "") and not m["match_to"].startswith("无("))
    print(f"成功匹配: {matched}")
    print(f"未匹配/校验失败: {len(all_mappings) - matched}")

    # 写 CSV
    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["gb_full_name", "match_to", "reason"])
        w.writeheader()
        for m in all_mappings:
            w.writerow(m)
    print(f"\nCSV 写入: {OUTPUT_CSV}")

    # 写 JSON (供转换脚本读)
    mapping_dict = {m["gb_full_name"]: m["match_to"] for m in all_mappings}
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(mapping_dict, f, ensure_ascii=False, indent=2)
    print(f"JSON 写入: {OUTPUT_JSON}")

    # 保存原始响应(调试用)
    with open(RAW_RESPONSE_FILE, "w", encoding="utf-8") as f:
        json.dump(raw_responses, f, ensure_ascii=False, indent=2)
    print(f"原始响应: {RAW_RESPONSE_FILE}")

    print("\n完成. 下一步: 人工复核未匹配项, 然后用 convert_new_table_industry.py 转换 new 表.")


if __name__ == "__main__":
    main()
