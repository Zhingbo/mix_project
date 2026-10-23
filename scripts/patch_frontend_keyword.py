# -*- coding: utf-8 -*-
# 给 ChatContainer.vue 加"关键词增删"面板 + data + 方法
import io
import datetime

FN = '/root/mix_project/liandong-intelligent-agent-master/src/components/ChatContainer.vue'
src = io.open(FN, 'r', encoding='utf-8').read()

bkp = FN + '.bak_kw_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
io.open(bkp, 'w', encoding='utf-8').write(src)
print('backup ->', bkp)

# ---- 1. 模板: 在 ✓处理完成 标签后插入关键词面板 ----
anchor1 = '''                                  <el-tag v-if="getIndustryState(step.data.industry_name).completed" type="success" size="small">
                                    ✓ 处理完成
                                  </el-tag>
'''
panel = '''                                  <el-tag v-if="getIndustryState(step.data.industry_name).completed" type="success" size="small">
                                    ✓ 处理完成
                                  </el-tag>
                                  <!-- 关键词增删企业 -->
                                  <div class="keyword-rule-panel" v-if="!getIndustryState(step.data.industry_name).processing" style="margin-top:6px;">
                                    <el-input
                                      v-model="industryKeyword[step.data.industry_name]"
                                      size="mini"
                                      placeholder="输入企业名称关键词（如 药房 / 激光）"
                                      style="width:220px; margin-right:6px;"
                                    ></el-input>
                                    <el-button type="warning" size="mini" plain icon="el-icon-plus" @click="applyKeywordRule(step.data.industry_name, 'add')">补充</el-button>
                                    <el-button type="danger" size="mini" plain icon="el-icon-minus" @click="applyKeywordRule(step.data.industry_name, 'delete')">删除</el-button>
                                  </div>
'''
if 'keyword-rule-panel' in src:
    print('模板已存在, 跳过1')
else:
    assert anchor1 in src, 'anchor1 未找到'
    src = src.replace(anchor1, panel, 1)
    print('模板插入OK')

# ---- 2. data: 加 industryKeyword ----
anchor2 = '      mindmapPipelineStates: {},'
if 'industryKeyword: {}' in src:
    print('data已存在, 跳过2')
else:
    assert anchor2 in src, 'anchor2 未找到'
    src = src.replace(anchor2, anchor2 + '\n      industryKeyword: {},  // 关键词增删: {产业链名称: 关键词}', 1)
    print('data插入OK')

# ---- 3. 方法: 在 exportIndustryResult 前插入 applyKeywordRule ----
anchor3 = '    async exportIndustryResult(industryName) {'
method = '''    async applyKeywordRule(industryName, action) {
      const kw = (this.industryKeyword[industryName] || '').trim();
      if (!kw) {
        this.$message.warning('请输入企业名称关键词');
        return;
      }
      const token = localStorage.getItem('access_token');
      if (!token) {
        this.$message.error('请先登录');
        this.$router.push('/login');
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
          body: JSON.stringify({ industry_name: industryName, keyword: kw, action })
        });
        const result = await response.json();
        if (response.ok) {
          this.$message.success(result.message || '操作成功');
        } else {
          this.$message.error((result && result.detail) || '操作失败');
        }
      } catch (e) {
        this.$message.error('请求失败: ' + e.message);
      }
    },

    async exportIndustryResult(industryName) {'''
if 'applyKeywordRule(industryName' in src:
    print('方法已存在, 跳过3')
else:
    assert anchor3 in src, 'anchor3 未找到'
    src = src.replace(anchor3, method, 1)
    print('方法插入OK')

io.open(FN, 'w', encoding='utf-8').write(src)
print('前端补丁完成')