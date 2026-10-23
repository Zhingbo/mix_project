# -*- coding: utf-8 -*-
# 撤销 step6 写死的"非健康"过滤, 改为按链 LLM 排除词(同 step4)
p = "step6_top_company_match.py"
s = open(p, encoding="utf-8").read()

# 1) 删除写死的过滤块
block_start = s.find("NON_HEALTH_RE = (")
block_end = s.find("def _is_non_health_name(name):")
if block_start != -1 and block_end != -1:
    # 块结束到该函数 return 那段的结尾(空行)
    func_end = s.find("def _match", block_end)  # 下一个函数
    if func_end == -1:
        func_end = s.find("def ", block_end + 10)
    s = s[:block_start] + s[func_end:]
    print("写死的非健康过滤块已删除")
else:
    print("未找到过滤块")

# 2) 删除过滤调用行
old_line = "        raw_companies = [c for c in raw_companies if not _is_non_health_name(c)]\n"
if old_line in s:
    s = s.replace(old_line, "", 1)
    print("过滤调用行已删除")
else:
    print("过滤调用行未找到")

# 3) 加按链 LLM 排除 import(如未加)
imp = "from .step4_company_match_nodes import _generate_exclusion_keywords\n"
if imp not in s:
    s = s.replace("from .cancel_token import is_cancelled, reset_token, remove_token\n",
                  "from .cancel_token import is_cancelled, reset_token, remove_token\n" + imp, 1)
    print("import 已加")
else:
    print("import 已存在")

# 4) 在自搜去重前生成按链排除词 + 过滤
anchor = "    # 串行去重（保持顺序一致性）\n"
addition = ("    # 生成该链的\"不该出现\"排除词(LLM, 按链)\n"
            "    _exclude_kws = _generate_exclusion_keywords(industry_name, [industry_name])\n"
            "    if _exclude_kws:\n"
            "        logging.info(f\"该链排除词({len(_exclude_kws)}): {_exclude_kws}\")\n"
            "\n"
            "    # 串行去重（保持顺序一致性）\n")
if anchor in s and "_exclude_kws" not in s.split(anchor)[0]:
    s = s.replace(anchor, addition, 1)
    print("排除词生成已插入")
else:
    print("排除词生成已存在或锚点未找到")

# 5) 在 raw_companies 后进行按链过滤
old2 = "        raw_companies = raw_position_results.get(position, [])\n"
new2 = ("        raw_companies = raw_position_results.get(position, [])\n"
        "        raw_companies = [c for c in raw_companies\n"
        "                         if not any(k in str(c) for k in _exclude_kws)]\n")
if old2 in s and new2 not in s:
    s = s.replace(old2, new2, 1)
    print("按链过滤已插入")
else:
    print("按链过滤已存在或锚点未找到")

open(p, "w", encoding="utf-8").write(s)
print("完成")