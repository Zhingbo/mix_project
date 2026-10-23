"""
国标行业分类(B口径) → 联东A口径(必须三级) 精确映射脚本 v2

改进:
1. 目标口径只用 level=3 三级 full_name (579个), 不含一二级, 避免映射到粗类
2. 带定义annotation, 让AI更准理解每个三级分类含义
3. 对机器人/AI/集成电路等关键领域给语义引导
4. 强制要求返回三级, 不允许一级二级

用法:
    cd /root/mix_project/scripts
    source /root/acemcp/.venv/bin/activate
    python build_industry_mapping_v2.py
"""

import csv
import json
import os
import time
import re
import pymysql
from typing import List, Dict, Optional
from openai import OpenAI

MATERIALS_DIR = "/root/mix_project/materials"
GB_KEYS_FILE = os.path.join(MATERIALS_DIR, "gb_industry_keys_from_new.csv")
OUTPUT_CSV = os.path.join(MATERIALS_DIR, "industry_mapping_gb_to_custom_v2.csv")
OUTPUT_JSON = os.path.join(MATERIALS_DIR, "industry_mapping_gb_to_custom_v2.json")
RAW_FILE = os.path.join(MATERIALS_DIR, "industry_mapping_raw_v2.json")

API_KEY = os.getenv("DASHSCOPE_API_KEY")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "deepseek-v4-pro"

BATCH_SIZE = 50
MAX_RETRIES = 3


def load_gb_keys() -> List[str]:
    keys = []
    with open(GB_KEYS_FILE, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            fn = row.get("full_name", "").strip()
            if fn:
                keys.append(fn)
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def load_a_level3() -> List[Dict]:
    """从 ent_industry_label 加载 level=3 三级 full_name + 定义"""
    conn = pymysql.connect(host="8.141.5.67", port=3306, user="root",
                           password=os.getenv("DB_PASSWORD"), database="business_data",
                           charset="utf8mb4", connect_timeout=30)
    cur = conn.cursor()
    cur.execute("SELECT full_name, annotation FROM ent_industry_label WHERE level=3 ORDER BY full_name")
    labels = []
    for fn, ann in cur.fetchall():
        labels.append({"full_name": fn, "annotation": ann or ""})
    cur.close()
    conn.close()
    return labels


def build_prompt(gb_batch: List[str], a_level3: List[Dict]) -> str:
    a_lines = []
    for a in a_level3:
        ann = a["annotation"]
        if len(ann) > 80:
            ann = ann[:80] + "..."
        a_lines.append(f'- "{a["full_name"]}"  ({ann})')
    a_block = "\n".join(a_lines)
    gb_block = "\n".join(f'{i+1}. "{k}"' for i, k in enumerate(gb_batch))

    prompt = f"""你是行业分类映射专家。为每条【国标行业分类】在【联东口径】清单中找1个语义最匹配的。

【联东口径三级清单】(共{len(a_level3)}条, 必须严格从中选, 不可创造新值, 必须选三级完整路径):
{a_block}

【国标清单】(共{len(gb_batch)}条, 逐条映射):
{gb_block}

映射规则:
1. 每条国标映射到1个联东三级full_name, 多对一可以.
2. 必须映射到三级(含两个|分隔符的完整路径如"装备制造|机器人|机器人本体制造"), 禁止映射到一级或二级.
3. 匹配依据: 语义最接近. 优先选细分领域最对应的.
4. 关键引导:
   - 国标"通用设备制造业"下"物料搬运/金属加工/通用零部件"等 → 考虑"装备制造|机器人|机器人零部件制造"或"装备制造|机器人|机器人本体制造"
   - 国标"计算机、���信和其他电子设备制造业"下"电子器件/电子元件" → "电子信息|集成电路|集成电路制造"或"电子信息|电子元件制造|敏感元件及传感器制造"
   - 国标"电气机械和器材制造业"下"电池/电机" → "机械设备与零件|电气设备|电池制造"或"电机制造"
   - 国标"仪器仪表制造业" → "电子信息|电子元件制造|敏感元件及传感器制造"或相关检验检测
   - 国标"智能消费设备" → "新一代信息技术|人工智能技术与应用|AI设备制造"
5. 实在找不到对应三级的, 仍必须从清单选最接近的一个, 禁止填"无".

返回JSON数组, 每元素:
{{"gb_full_name":"国标完整路径","match_to":"联东三级完整路径","reason":"一句理由"}}
只返回JSON数组."""
    return prompt


def call_deepseek(client, prompt) -> Optional[str]:
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "你是行业分类映射专家, 严格返回JSON数组, 不要包裹在对象里."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1, max_tokens=8000)
        return resp.choices[0].message.content
    except Exception as e:
        print(f"  API失败: {e}")
        return None


def parse_response(raw, gb_batch) -> List[Dict]:
    if not raw:
        return []
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except:
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except:
            return []
    if isinstance(data, dict):
        if "gb_full_name" in data:
            data = [data]
        else:
            for key in ("mappings", "mapping", "results", "data", "list"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
    if not isinstance(data, list):
        return []
    batch_set = set(gb_batch)
    out = []
    for item in data:
        gb = item.get("gb_full_name", "").strip()
        mt = item.get("match_to", "").strip()
        rs = item.get("reason", "").strip()
        if gb in batch_set:
            out.append({"gb_full_name": gb, "match_to": mt, "reason": rs})
    return out


def main():
    print("=" * 60)
    print("国标 → A口径三级 精确映射 v2")
    print("=" * 60)

    gb_keys = load_gb_keys()
    a_level3 = load_a_level3()
    a_fns = set(a["full_name"] for a in a_level3)
    print(f"国标清单: {len(gb_keys)} 条")
    print(f"A口径三级锚点: {len(a_level3)} 条")

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    all_mappings = []
    raw_responses = []

    batches = [gb_keys[i:i+BATCH_SIZE] for i in range(0, len(gb_keys), BATCH_SIZE)]
    print(f"分 {len(batches)} 批, 每批 {BATCH_SIZE}")

    for bi, batch in enumerate(batches):
        print(f"\n--- 批 {bi+1}/{len(batches)} ({len(batch)}条) ---")
        prompt = build_prompt(batch, a_level3)
        print(f"  prompt {len(prompt)}字", flush=True)

        success = False
        for attempt in range(1, MAX_RETRIES+1):
            print(f"  尝试 {attempt}/{MAX_RETRIES}...", flush=True)
            raw = call_deepseek(client, prompt)
            if raw:
                raw_responses.append({"batch": bi, "attempt": attempt, "raw": raw})
                parsed = parse_response(raw, batch)
                print(f"  解析 {len(parsed)} 条", flush=True)
                if len(parsed) >= len(batch) * 0.8:
                    all_mappings.extend(parsed)
                    # 补缺失
                    got = set(p["gb_full_name"] for p in parsed)
                    missing = [k for k in batch if k not in got]
                    for m in missing:
                        all_mappings.append({"gb_full_name": m, "match_to": "无", "reason": "API未返回"})
                    success = True
                    break
                elif parsed:
                    all_mappings.extend(parsed)
                    got = set(p["gb_full_name"] for p in parsed)
                    missing = [k for k in batch if k not in got]
                    for m in missing:
                        all_mappings.append({"gb_full_name": m, "match_to": "无", "reason": "API部分未返回"})
                    success = True
                    break
            time.sleep(5)
        if not success:
            for k in batch:
                all_mappings.append({"gb_full_name": k, "match_to": "无", "reason": "API全部失败"})

    # 去重
    seen = set()
    deduped = []
    for m in all_mappings:
        if m["gb_full_name"] not in seen:
            seen.add(m["gb_full_name"])
            deduped.append(m)
    all_mappings = deduped

    # 校验: 必须是三级(含两个|) 且在 a_fns 里
    bad = 0
    for m in all_mappings:
        mt = m["match_to"]
        if mt == "无" or mt not in a_fns:
            print(f"  校验失败: {m['gb_full_name']} -> {mt}")
            m["match_to"] = "无(校验失败:" + mt + ")"
            bad += 1
        elif mt.count("|") < 2:
            print(f"  非三级: {m['gb_full_name']} -> {mt}")
            m["match_to"] = "无(非三级:" + mt + ")"
            bad += 1

    matched = sum(1 for m in all_mappings if not m["match_to"].startswith("无"))
    print(f"\n=== 汇总 ===")
    print(f"总: {len(all_mappings)}, 成功: {matched}, 失败: {len(all_mappings)-matched}")

    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["gb_full_name", "match_to", "reason"])
        w.writeheader()
        for m in all_mappings:
            w.writerow(m)
    print(f"CSV: {OUTPUT_CSV}")

    mapping_dict = {m["gb_full_name"]: m["match_to"] for m in all_mappings}
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(mapping_dict, f, ensure_ascii=False, indent=2)
    print(f"JSON: {OUTPUT_JSON}")

    with open(RAW_FILE, "w", encoding="utf-8") as f:
        json.dump(raw_responses, f, ensure_ascii=False, indent=2)
    print(f"原始响应: {RAW_FILE}")


if __name__ == "__main__":
    main()
