import os
import pymysql
import collections

cfg = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
           database="business_data", charset="utf8mb4")

DOMAINS = {
    "医院/诊所/机构": ["医院", "诊所", "门诊", "卫生院", "卫生所", "妇幼", "体检", "急救", "医联体", "互联网医院"],
    "专科医疗": ["口腔", "眼科", "牙科", "齿科", "骨科", "妇产", "儿科", "肾病", "血液", "血透", "肿瘤", "整形", "皮肤科", "植发", "助听", "义齿", "假肢", "矫形", "耳鼻喉"],
    "医药/中药": ["医药", "制药", "药业", "药房", "药店", "药品", "药物", "制剂", "原料药", "中药", "中成药", "饮片", "西药", "药械", "医疗器械"],
    "生物/基因/细胞": ["生物医药", "生物药", "生物制品", "生物科技", "生物技术", "基因", "细胞", "干细胞", "免疫", "抗体", "疫苗", "血液制品", "血浆", "蛋白", "多肽", "核酸", "单抗", "分子诊断", "测序", "生物"],
    "健康管理/康养": ["健康管理", "康复", "护理", "养老", "康养", "理疗", "针灸", "推拿", "月子", "养生", "保健"],
    "医学检验/影像": ["医学检验", "医学影像", "影像诊断", "检验所", "诊断", "医疗", "医学", "医护", "医生"],
}

def hit_domains(text):
    hits = []
    for dom, kws in DOMAINS.items():
        for k in kws:
            if k in text:
                hits.append((dom, k))
    return hits

conn = pymysql.connect(**cfg)
cur = conn.cursor(pymysql.cursors.SSCursor)
cur.execute("""SELECT company_name, `explain`, industry_class_second
               FROM ent_industry_class_chain_scope_20260928_converted
               WHERE industry_class_first = '其他'""")

total = 0
health = 0
by_second = collections.Counter()
by_domain = collections.Counter()
kw_freq = collections.Counter()
samples = []          # (name, explain, second, matched)
false_sample = []     # 命中"生物"但不是医药生物的样例, 人工复核用

for name, explain, second in cur:
    total += 1
    text = (name or "") + " " + (explain or "")
    hs = hit_domains(text)
    if not hs:
        continue
    health += 1
    by_second[second] += 1
    for dom, k in hs:
        by_domain[dom] += 1
        kw_freq[k] += 1
    # 记录样例: 每个 domain 最多存 8 条
    if len(samples) < 120:
        samples.append((name, explain, second, [k for _, k in hs]))

cur.close(); conn.close()

print("=" * 70)
print("方案2 预览: 其他(一级)里疑似生命健康的企业")
print("=" * 70)
print(f"扫描 其他 总量          = {total}")
print(f"疑似健康命中            = {health}  ({health/total*100:.2f}%)")
print()
print("--- 命中分布(按当前二级, Top15) ---")
for s, c in by_second.most_common(15):
    print(f"  {s}: {c}")
print()
print("--- 命中分布(按健康域) ---")
for s, c in by_domain.most_common():
    print(f"  {s}: {c}")
print()
print("--- 命中关键词 Top30 ---")
for k, c in kw_freq.most_common(30):
    print(f"  {k}: {c}")
print()
print("--- 命样例(前60条) ---")
for name, explain, second, ks in samples[:60]:
    e = (explain or "")[:60]
    print(f"  [{second}] {name}")
    print(f"        命中: {','.join(ks[:6])}  | explain: {e}")
print()
print("--- 存样例到文件 ---")
with open("/root/mix_project/preview_health_hits.txt", "w") as f:
    for name, explain, second, ks in samples:
        f.write(f"{second}\t{name}\t{','.join(ks[:8])}\t{(explain or '')[:200]}\n")
print("完成, 样例已存 /root/mix_project/preview_health_hits.txt")