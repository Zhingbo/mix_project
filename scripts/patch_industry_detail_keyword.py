# -*- coding: utf-8 -*-
# 给 IndustryDetailView.vue(/)detail 页) 加"关键词增删"面板 + data + 方法
import io
import datetime

FN = '/root/mix_project/liandong-intelligent-agent-master/src/views/IndustryDetailView.vue'
src = io.open(FN, 'r', encoding='utf-8').read()

bkp = FN + '.bak_kw_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
io.open(bkp, 'w', encoding='utf-8').write(src)
print('backup ->', bkp)

# ---- 1. 模板: 在"导出名单"按钮后插入关键词面板 ----
anchor1 = '        <el-button size="mini" type="success" icon="el-icon-download" @click="handleExport">导出名单</el-button>\n'
panel = ('        <el-button size="mini" type="success" icon="el-icon-download" @click="handleExport">导出名单</el-button>\n'
         '        <el-input\n'
         '          v-model="industryKeyword"\n'
         '          size="mini"\n'
         '          placeholder="输入企业名称关键词"\n'
         '          style="width:180px; margin-right:6px;"\n'
         '        ></el-input>\n'
         '        <el-button size="mini" type="warning" icon="el-icon-plus" @click="applyKeywordRule(\'add\')">补充</el-button>\n'
         '        <el-button size="mini" type="danger" icon="el-icon-minus" @click="applyKeywordRule(\'delete\')">删除</el-button>\n')
if 'industryKeyword' in src and 'applyKeywordRule' in src:
    print('已存在, 跳过模板')
else:
    assert anchor1 in src, 'anchor1 未找到'
    src = src.replace(anchor1, panel, 1)
    print('模板插入OK')

# ---- 2. data: 加 industryKeyword ----
anchor2 = '      industryName: this.$route.query.name || \'\','
if 'industryKeyword' in src.split('methods:')[0]:
    print('data已存在, 跳过')
else:
    assert anchor2 in src, 'anchor2 未找到'
    src = src.replace(anchor2, anchor2 + '\n      industryKeyword: \'\',  // 关键词增删企业', 1)
    print('data插入OK')

# ---- 3. 方法: 在 handleExport 前插入 applyKeywordRule ----
anchor3 = '    async handleExport() {'
method = '''    async applyKeywordRule(action) {
      const kw = (this.industryKeyword || '').trim();
      if (!kw) {
        this.$message.warning('请输入企业名称关键词');
        return;
      }
      if (!this.industryName) {
        this.$message.warning('无产业链名称');
        return;
      }
      const token = localStorage.getItem('access_token');
      if (!token) {
        this.$message.error('请先登录');
        return;
      }
      const tokenType = localStorage.getItem('token_type') || 'Bearer';
      try {
        const response = await fetch(`${process.env.VUE_APP_API_SERVER}/api/pipeline/keyword_rule`, {
          method: 'POST',
          headers: {
            'Authorization': `${tokenType} ${token}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ industry_name: this.industryName, keyword: kw, action })
        });
        const result = await response.json();
        if (response.ok) {
          this.$message.success(result.message || '操作成功');
          this.industryKeyword = '';
        } else {
          this.$message.error((result && result.detail) || '操作失败');
        }
      } catch (e) {
        this.$message.error('请求失败: ' + e.message);
      }
    },

    async handleExport() {'''
if 'applyKeywordRule(action' in src:
    print('方法已存在, 跳过')
else:
    assert anchor3 in src, 'anchor3 未找到'
    src = src.replace(anchor3, method, 1)
    print('方法插入OK')

io.open(FN, 'w', encoding='utf-8').write(src)
print('IndustryDetailView 补丁完成')