# 用户管理功能设计方案

## 一、功能概述

在现有系统中添加用户管理功能，允许管理员（你）添加和管理其他用户的登录权限。

## 二、功能范围（完整功能）

### 1. 基础功能
- 查看用户列表（OA账号、用户姓名、权限级别、状态、最后登录时间）
- 添加新用户
- 编辑用户信息
- 删除用户
- 启用/禁用用户账户

### 2. 权限控制
- 只有 `permission_level = 'admin'` 的用户可以访问用户管理页面
- 其他用户访问时显示权限不足提示

## 三、UI设计方案

### 3.1 整体风格
与现有页面保持一致的 **玻璃拟态** 风格：
- 半透明背景 + backdrop-filter: blur()
- 渐变色边框和按钮
- 大圆角设计（border-radius: 16px~24px）
- 颜色方案：
  - --nav-ink: #102033
  - --nav-strong: #0f766e
  - --nav-blue: #2563eb

### 3.2 页面布局

```
┌─────────────────────────────────────────────────────────┐
│  导航栏（已有）                                          │
│  [产业链列表] [用户管理] [个人中心 ▼]                    │
└──���──────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│  用户管理                                               │
│  ┌────────────────────────────────────────────────┐    │
│  │  [+ 添加用户]    [🔄 刷新]                      │    │
│  └────────────────────────────────────────────────┘    │
│                                                         │
│  ┌────────────────────────────────────────────────┐    │
│  │  OA账号      │ 姓名  │ 权限  │ 状态 │ 操作     │    │
│  ├────────────────────────────────────────────────┤    │
│  │  zhingbo    │ 邹兴波 │ admin │ ●启用│ ✏️ 🗑️  │    │
│  │  user001    │ 张三   │ basic │ ●启用│ ✏️ 🗑️  │    │
│  │  user002    │ 李四   │ basic │ ○禁用│ ✏️ 🗑️  │    │
│  └────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### 3.3 组件设计

#### 用户列表卡片
```css
.user-list-card {
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(20px);
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.3);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
}
```

#### 按钮
```css
.btn-primary {
  background: linear-gradient(135deg, #0f766e 0%, #0d9488 100%);
  border-radius: 999px;
  color: white;
}

.btn-danger {
  background: linear-gradient(135deg, #dc2626 0%, #ef4444 100%);
  border-radius: 999px;
}
```

#### 状态标签
```css
.status-badge {
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12px;
}

.status-active {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.status-inactive {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}
```

### 3.4 对话框设计

#### 添加/编辑用户对话框
```css
.dialog-wrapper {
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(20px);
  border-radius: 24px;
}
```

表单字段：
- OA账号（必填，唯一）
- 用户姓名（必填）
- 权限级别（下拉选择：admin / basic）
- 状态（开关）

## 四、技术实现方案

### 4.1 后端API

需要创建新的API路由文件：`user_management_routes.py`

```python
# API端点设计
GET    /api/users/list          # 获取用户列表
POST   /api/users/add           # 添加用户
PUT    /api/users/update        # 更新用户信息
DELETE /api/users/delete        # 删除用户
PUT    /api/users/toggle-status # 切换用户状态
GET    /api/users/current       # 获取当前用户信息（验证权限）
```

### 4.2 前端文件结构

```
src/
├── views/
│   └── UserManageView.vue          # 用户管理主页面
├── components/
│   └── UserManage/
│       ├── UserList.vue            # 用户列表组件
│       ├── UserDialog.vue          # 添加/编辑用户对话框
│       └── UserStatusToggle.vue    # 状态切换组件
├── api/
│   └── modules/
│       └── userManage.js           # 用户管理API模块
└── router/
    └── index.js                    # 添加路由配置
```

### 4.3 路由配置

```javascript
{
  path: '/users',
  name: 'user-manage',
  component: () => import('../views/UserManageView.vue'),
  meta: {
    requiresAuth: true,
    requiresAdmin: true  // 新增：需要管理员权限
  }
}
```

### 4.4 权限验证

在路由守卫中添加管理员权限检查：
```javascript
if (to.meta.requiresAdmin) {
  const userInfo = getCurrentUserInfo(); // 从localStorage或API获取
  if (userInfo.permission_level !== 'admin') {
    next({ path: '/app' }); // 重定向到首页并提示权限不足
    return;
  }
}
```

## 五、开发步骤

1. **后端开发**
   - 创建 `user_management_routes.py`
   - 实现用户CRUD API
   - 添加权限验证中间件

2. **前端开发**
   - 创建 `UserManageView.vue`
   - 创建用户列表组件
   - 创建添加/编辑对话框
   - 创建API模块 `userManage.js`

3. **集成**
   - 添加路由配置
   - 在导航栏添加入口
   - 更新路由守卫

## 六、数据库表结构

使用现有的 `sso_whitelist` 表，无需修改：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键 |
| oa_user_id | VARCHAR(100) | OA账号（唯一） |
| user_name | VARCHAR(100) | 用户姓名 |
| permission_level | VARCHAR(50) | 权限：basic/admin |
| is_active | TINYINT(1) | 是否启用 |
| last_login_at | DATETIME | 最后登录时间 |
| created_at | DATETIME | 创建时间 |

## 七、安全考虑

1. 所有API需要验证JWT token
2. 管理员权限验证在后端也要做二次校验
3. 敏感操作（删除、修改权限）需要确认
4. 记录操作日志（可选）
