# -*- coding: utf-8 -*-
# 在 pipeline_routes.py 的 step 循环结束后、# 完成 之前, 插入产业链特殊后置处理钩子
import sys
P = "/root/mix_project/pipeline_routes.py"
s = open(P, encoding="utf-8").read()

anchor = """                # 完成
                final_result = {
                    'industry_name': industry_name,"""

hook = """                # ============ 产业链特殊后置处理(仅特定链, 如工业软件定向优化) ============
                try:
                    from steps.chain_special_processing import apply_chain_special_processing
                    sp_result = await loop.run_in_executor(None, apply_chain_special_processing, industry_name)
                    results.append({'step': 11, 'name': '产业链特殊处理', 'status': sp_result.get('status', 'completed'), 'result': sp_result})
                    await send_message({"step": 11, "step_name": "产业链特殊处理", "message": sp_result.get('reason', str(sp_result))}, "info")
                except Exception as sp_e:
                    logger.error(f"产业链特殊后置处理失败: {sp_e}")
                # ============ 产业链特殊后置处理结束 ============

                # 完成
                final_result = {
                    'industry_name': industry_name,"""

if anchor not in s:
    print("[FAIL] 未找到锚点")
    sys.exit(1)
if "chain_special_processing" in s:
    print("[skip] 钩子已存在")
    sys.exit(0)
s = s.replace(anchor, hook, 1)
open(P, "w", encoding="utf-8").write(s)
print("[done] 钩子已插入")