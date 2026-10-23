"""
钉钉机器人路由
提供发送消息的 API 接口
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from services.dingtalk_service import get_bot
from auth_routes import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/dingtalk", tags=["钉钉机器人"])


# ==================== 请求/响应模型 ====================

class SendToAliasesRequest(BaseModel):
    """通过项目 OA 账号发送消息请求"""
    aliases: List[str] = Field(..., description="OA账号列表（oa_user_id/alias）")
    title: str = Field(..., description="消息标题（Markdown 消息需要）")
    content: str = Field(..., description="消息内容（Markdown 或纯文本）")
    msg_type: str = Field("markdown", description="消息类型：text 或 markdown")
    bot_id: str = Field("industry_chain", description="机器人ID")


class SendToUserIdsRequest(BaseModel):
    """直接通过钉钉 userId 发送消息请求"""
    user_ids: List[str] = Field(..., description="钉钉 userId 列表")
    title: str = Field(..., description="消息标题（Markdown 消息需要）")
    content: str = Field(..., description="消息内容（Markdown 或纯文本）")
    msg_type: str = Field("markdown", description="消息类型：text 或 markdown")
    bot_id: str = Field("industry_chain", description="机器人ID")


class TestMessageRequest(BaseModel):
    """测试消息请求"""
    test_alias: str = Field(..., description="测试接收人的 OA 账号")


# ==================== 路由 ====================

@router.post("/send-to-aliases")
async def send_to_aliases(req: SendToAliasesRequest, current_user: dict = Depends(get_current_user)):
    """
    通过项目的 OA 账号列表发送消息

    流程：
    1. 接收 oa_user_id 列表（对应 idm.alias）
    2. 查询 idm_users 获取 dinguserid
    3. 通过钉钉机器人发送单聊消息

    权限：需要登录
    """
    if not req.aliases:
        raise HTTPException(status_code=400, detail="aliases 不能为空")

    try:
        bot = get_bot(req.bot_id)
        result = bot.send_to_project_users(
            aliases=req.aliases,
            title=req.title,
            text=req.content,
            msg_type=req.msg_type
        )

        logger.info(f"用户 {current_user.get('oa_user_id', current_user.get('username'))} 发送钉钉消息: "
                    f"机器人={req.bot_id}, 接收人数={len(req.aliases)}, 成功发送={result.get('sent')}")

        return {
            "success": result.get("success", True),
            "message": f"发送完成，成功: {result.get('sent')}/{result.get('total')}",
            "result": result
        }

    except Exception as e:
        logger.error(f"发送钉钉消息失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"发送失败: {str(e)}")


@router.post("/send-to-user-ids")
async def send_to_user_ids(req: SendToUserIdsRequest, current_user: dict = Depends(get_current_user)):
    """
    直接通过钉钉 userId 发送消息

    权限：需要登录
    """
    if not req.user_ids:
        raise HTTPException(status_code=400, detail="user_ids 不能为空")

    try:
        bot = get_bot(req.bot_id)

        if req.msg_type == "markdown":
            result = bot.send_single_markdown(req.user_ids, req.title, req.content)
        else:
            result = bot.send_single_text(req.user_ids, req.content)

        logger.info(f"用户 {current_user.get('oa_user_id', current_user.get('username'))} 发送钉钉消息（直接userId）: "
                    f"机器人={req.bot_id}, 接收人数={len(req.user_ids)}, 成功={result.get('success')}")

        return {
            "success": result.get("success"),
            "message": "发送完成" if result.get("success") else "发送失败",
            "result": result
        }

    except Exception as e:
        logger.error(f"发送钉钉消息失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"发送失败: {str(e)}")


@router.post("/test")
async def test_send_message(req: TestMessageRequest, current_user: dict = Depends(get_current_user)):
    """
    测试发送消息（给指定 OA 账号发一条测试消息）

    权限：需要登录
    """
    try:
        bot = get_bot("industry_chain")

        # 查询 dinguserid
        dinguserid = bot.get_dinguserid_by_alias(req.test_alias)
        if not dinguserid:
            raise HTTPException(status_code=404, detail=f"未找到 alias={req.test_alias} 对应的钉钉用户")

        # 发送测试消息
        test_title = "📬 钉钉机器人测试消息"
        test_content = f"""## 钉钉机器人集成测试

---

**测试时间：** {logger.logger.handlers[0].formatter.datefmt if hasattr(logger.logger.handlers[0], 'formatter') else 'N/A'}

**接收人 OA 账号：** `{req.test_alias}`

**钉钉 userId：** `{dinguserid}`

**触发用户：** {current_user.get('oa_user_id', current_user.get('username'))}

---

### ✅ 测试成功

如果你看到这条消息，说明：

1. 钉钉机器人配置正确
2. idm_users 中的 dinguserid 有效
3. 消息发送链路畅通

---

📌 **产业链智能体** 钉钉通知功能已就绪
        """

        result = bot.send_single_markdown([dinguserid], test_title, test_content)

        logger.info(f"用户 {current_user.get('oa_user_id', current_user.get('username'))} 发送测试消息到 {req.test_alias}")

        return {
            "success": result.get("success"),
            "message": f"测试消息已发送到 {req.test_alias}",
            "dinguserid": dinguserid,
            "result": result
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"发送测试消息失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"发送测试消息失败: {str(e)}")


@router.get("/bots")
async def list_bots(current_user: dict = Depends(get_current_user)):
    """
    获取可用的机器人列表

    权限：需要登录
    """
    from services.dingtalk_service import BOT_INSTANCES

    bots = []
    for bot_id, bot in BOT_INSTANCES.items():
        bots.append({
            "bot_id": bot_id,
            "name": bot.name,
            "app_key": bot.app_key
        })

    return {
        "success": True,
        "bots": bots
    }


@router.get("/check-dinguserid/{alias}")
async def check_dinguserid(alias: str, current_user: dict = Depends(get_current_user)):
    """
    检查指定 OA 账号的 dinguserid 绑定情况

    权限：需要登录
    """
    try:
        bot = get_bot("industry_chain")
        dinguserid = bot.get_dinguserid_by_alias(alias)

        if dinguserid:
            return {
                "success": True,
                "alias": alias,
                "dinguserid": dinguserid,
                "bound": True
            }
        else:
            return {
                "success": False,
                "alias": alias,
                "dinguserid": None,
                "bound": False,
                "message": "未找到绑定或用户不存在"
            }

    except Exception as e:
        logger.error(f"检查 dinguserid 失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"检查失败: {str(e)}")
