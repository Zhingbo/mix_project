# -*- coding: utf-8 -*-
import io

FN = '/root/mix_project/liandong-intelligent-agent-master/src/views/IndustryDetailView.vue'
src = io.open(FN, encoding='utf-8').read()

anchor = "      industryName: this.$route.query.name || '',\n"
assert src.count(anchor) == 1, 'anchor 数量错误: %d' % src.count(anchor)
if "      industryKeyword: ''," in src:
    print('已存在')
else:
    src = src.replace(anchor, anchor + "      industryKeyword: '',  // 关键词增删企业\n", 1)
    io.open(FN, 'w', encoding='utf-8').write(src)
    print('data字段已加')