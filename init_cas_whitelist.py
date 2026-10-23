"""
CAS白名单初始化脚本
运行此脚本来初始化数据库并添加初始白名单用户
"""
from database.industrial_chain.sso_whitelist_db import (
    init_sso_whitelist_table,
    add_whitelist_user,
    list_whitelist_users
)
from utils.logger import get_logger

logger = get_logger(__name__)


def init_cas_system():
    """
    初始化CAS系统
    """
    print("=" * 50)
    print("CAS单点登录系统初始化")
    print("=" * 50)

    # 1. 初始化表
    print("\n[1/2] 初始化白名单表...")
    result = init_sso_whitelist_table()
    if result["success"]:
        print("✓ 白名单表初始化成功")
    else:
        print(f"✗ 白名单表初始化失败: {result['message']}")
        return

    # 2. 添加初始用户
    print("\n[2/2] 添加初始白名单用户...")
    initial_users = [
        {"oa_user_id": "gy_zhanghb", "user_name": "张洪波", "permission_level": "admin"},
    ]

    for user_info in initial_users:
        result = add_whitelist_user(**user_info)
        if result["success"]:
            print(f"✓ 添加用户成功: {user_info['oa_user_id']}")
        else:
            if "已存在" in result["message"]:
                print(f"○ 用户已存在: {user_info['oa_user_id']}")
            else:
                print(f"✗ 添加用户失败 {user_info['oa_user_id']}: {result['message']}")

    # 3. 显示当前白名单
    print("\n当前白名单用户:")
    print("-" * 50)
    list_result = list_whitelist_users()
    if list_result["success"]:
        for user in list_result["users"]:
            status = "启用" if user["is_active"] else "禁用"
            print(f"  - {user['oa_user_id']} ({user['user_name']}) - 权限: {user['permission_level']}, 状态: {status}")
        print(f"\n总计: {list_result['count']} 位用户")
    else:
        print(f"获取白名单失败: {list_result['message']}")

    print("\n" + "=" * 50)
    print("CAS系统初始化完成!")
    print("=" * 50)


if __name__ == "__main__":
    init_cas_system()
