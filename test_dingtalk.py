"""
钉钉机器人功能测试脚本
"""

import sys
sys.path.insert(0, "/root/mix_project")

from services.dingtalk_service import get_bot


def test_get_access_token():
    """测试获取 accessToken"""
    print("=== 测试 1: 获取 accessToken ===")
    try:
        bot = get_bot("industry_chain")
        token = bot.get_access_token()
        print(f"✅ accessToken 获取成功: {token[:20]}...")
        return True
    except Exception as e:
        print(f"❌ 失败: {str(e)}")
        return False


def test_get_dinguserid_by_alias():
    """测试通过 alias 获取 dinguserid"""
    print("\n=== 测试 2: 通过 alias 获取 dinguserid ===")

    test_aliases = [
        "gy_zhanghb",
        "210216",
        "207950",
        "lig",
        "123"
    ]

    for alias in test_aliases:
        try:
            bot = get_bot("industry_chain")
            dinguserid = bot.get_dinguserid_by_alias(alias)
            if dinguserid:
                print(f"✅ {alias} -> {dinguserid}")
            else:
                print(f"⚠️  {alias} -> 未找到 dinguserid")
        except Exception as e:
            print(f"❌ {alias} 查询失败: {str(e)}")


def test_send_single_text():
    """测试发送单聊文本消息（需要有效 dinguserid）"""
    print("\n=== 测试 3: 发送单聊文本消息 ===")

    # 先找一个有 dinguserid 的用户
    bot = get_bot("industry_chain")
    dinguserid = bot.get_dinguserid_by_alias("gy_zhanghb")

    if not dinguserid:
        print("⚠️  跳过：gy_zhanghb 没有 dinguserid")
        return

    try:
        result = bot.send_single_text(
            user_ids=[dinguserid],
            content="这是一条来自产业链智能体的测试消息（文本）"
        )
        if result.get("success"):
            print(f"✅ 文本消息发送成功")
        else:
            print(f"❌ 发送失败: {result}")
    except Exception as e:
        print(f"❌ 发送异常: {str(e)}")


def test_send_single_markdown():
    """测试发送单聊 Markdown 消息"""
    print("\n=== 测试 4: 发送单聊 Markdown 消息 ===")

    bot = get_bot("industry_chain")
    dinguserid = bot.get_dinguserid_by_alias("gy_zhanghb")

    if not dinguserid:
        print("⚠️  跳过：gy_zhanghb 没有 dinguserid")
        return

    markdown_content = """## 📊 产业链分析完成通知

---

**分析时间：** 2026-07-10 14:30

**产业链名称：** 新能源汽车

**分析结果：** 共生成 23 个节点、87 家企业

---

### ✅ 分析已完成

产业链知识图谱已生成完毕，请登录系统查看详细报告。

---

📌 **产业链智能体** 自动通知
    """

    try:
        result = bot.send_single_markdown(
            user_ids=[dinguserid],
            title="📊 产业链分析完成",
            text=markdown_content
        )
        if result.get("success"):
            print(f"✅ Markdown 消息发送成功")
        else:
            print(f"❌ 发送失败: {result}")
    except Exception as e:
        print(f"❌ 发送异常: {str(e)}")


def test_send_to_project_users():
    """测试通过项目 OA 账号列表发送消息"""
    print("\n=== 测试 5: 通过 OA 账号列表发送消息 ===")

    test_aliases = ["gy_zhanghb", "lig", "123"]

    markdown_content = """## 📢 批量通知测试

---

这是一条批量发送测试消息。

**接收人列表：** gy_zhanghb, lig, 123

**发送方式：** 通过 OA 账号（alias）自动匹配 dinguserid

---

📌 **产业链智能体** 通知功能
    """

    try:
        bot = get_bot("industry_chain")
        result = bot.send_to_project_users(
            aliases=test_aliases,
            title="📢 批量通知测试",
            text=markdown_content,
            msg_type="markdown"
        )

        print(f"发送统计：")
        print(f"  总接收人: {result.get('total')}")
        print(f"  成功发送: {result.get('sent')}")
        print(f"  未找到: {result.get('not_found')}")
        print(f"  无 dinguserid: {result.get('no_dingid')}")
        print(f"  未找到的账号: {result.get('details', {}).get('not_found_aliases')}")

        if result.get("success"):
            print(f"✅ 批量发送完成")
        else:
            print(f"⚠️  部分失败")

    except Exception as e:
        print(f"❌ 批量发送异常: {str(e)}")


def main():
    """运行所有测试"""
    print("=" * 60)
    print("钉钉机器人功能测试")
    print("=" * 60)

    test_get_access_token()
    test_get_dinguserid_by_alias()
    test_send_single_text()
    test_send_single_markdown()
    test_send_to_project_users()

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
