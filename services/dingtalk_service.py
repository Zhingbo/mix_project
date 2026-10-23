"""
钉钉机器人服务
支持企业内部应用机器人发送单聊消息
"""
import os

import requests
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from database.industrial_chain.connection import get_db_connection
from utils.logger import get_logger

logger = get_logger(__name__)

BASE_URL = "https://api.dingtalk.com"


class DingTalkBotService:
    """钉钉机器人服务"""

    def __init__(self, app_key: str, app_secret: str, name: str = "DingTalkBot"):
        """
        初始化机器人

        Args:
            app_key: 钉钉应用 AppKey
            app_secret: 钉钉应用 AppSecret
            name: 机器人名称（用于日志）
        """
        self.app_key = app_key
        self.app_secret = app_secret
        self.name = name
        self._access_token = None
        self._token_expires_at = None

    def get_access_token(self) -> str:
        """
        获取企业内部应用的 accessToken（带缓存和过期检查）

        Returns:
            accessToken
        """
        # 检查缓存是否有效（提前 5 分钟过期）
        if self._access_token and self._token_expires_at and datetime.now() < self._token_expires_at:
            return self._access_token

        url = f"{BASE_URL}/v1.0/oauth2/accessToken"
        try:
            resp = requests.post(url, json={
                "appKey": self.app_key,
                "appSecret": self.app_secret
            }, timeout=10)
            data = resp.json()

            if "accessToken" not in data:
                logger.error(f"[{self.name}] 获取 accessToken 失败: {data}")
                raise Exception(f"获取 accessToken 失败: {data.get('message', '未知错误')}")

            self._access_token = data["accessToken"]
            # accessToken 有效期 2 小时，提前 5 分钟刷新
            self._token_expires_at = datetime.now() + timedelta(seconds=7200 - 300)
            logger.info(f"[{self.name}] accessToken 获取成功并缓存")
            return self._access_token

        except requests.RequestException as e:
            logger.error(f"[{self.name}] 请求 accessToken 网络错误: {str(e)}")
            raise Exception(f"网络请求失败: {str(e)}")

    def get_dinguserid_by_alias(self, alias: str) -> Optional[str]:
        """
        通过项目的 oa_user_id（即 idm.alias）获取钉钉 dinguserid

        Args:
            alias: OA账号，对应 idm_users.alias

        Returns:
            dinguserid 钉钉用户ID，未找到返回 None
        """
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT dinguserid, usercn, usernumber, belongdepartment FROM performance_db.idm_users WHERE alias = %s",
                    (alias,)
                )
                user = cursor.fetchone()
                conn.close()

                if not user:
                    logger.warning(f"未找到 alias={alias} 对应的 idm_users 记录")
                    return None

                dinguserid = user.get("dinguserid")
                if not dinguserid:
                    logger.warning(f"alias={alias} ({user.get('usercn')}) 未绑定 dinguserid")
                    return None

                logger.info(f"alias={alias} -> dinguserid={dinguserid} ({user.get('usercn')}, {user.get('belongdepartment')})")
                return dinguserid

        except Exception as e:
            logger.error(f"查询 dinguserid 失败: {str(e)}")
            return None

    def send_single_text(self, user_ids: List[str], content: str) -> Dict[str, Any]:
        """
        机器人批量发送单聊文本消息

        Args:
            user_ids: 钉钉 userId 列表
            content: 文本内容

        Returns:
            发送结果
        """
        if not user_ids:
            raise Exception("user_ids 不能为空")

        token = self.get_access_token()
        url = f"{BASE_URL}/v1.0/robot/oToMessages/batchSend"
        headers = {
            "x-acs-dingtalk-access-token": token,
            "Content-Type": "application/json"
        }
        body = {
            "robotCode": self.app_key,
            "userIds": user_ids,
            "msgKey": "sampleText",
            "msgParam": json.dumps({"content": content}, ensure_ascii=False)
        }

        try:
            resp = requests.post(url, headers=headers, json=body, timeout=10)
            data = resp.json()

            # 钉钉 API 响应格式判断：
            # 1. 有 code 字段：code=0 表示成功
            # 2. 无 code 字段但有 processQueryKey：表示消息已提交（异步处理），视为成功
            is_success = (data.get("code") == 0) or (data.get("code") is None and data.get("processQueryKey"))

            if is_success:
                logger.info(f"[{self.name}] 发送文本消息成功，接收人: {len(user_ids)} 人")
                return {"success": True, "data": data}
            else:
                logger.error(f"[{self.name}] 发送文本消息失败: {data}")
                return {"success": False, "data": data}

        except requests.RequestException as e:
            logger.error(f"[{self.name}] 发送文本消息网络错误: {str(e)}")
            return {"success": False, "error": str(e)}

    def send_single_markdown(self, user_ids: List[str], title: str, text: str) -> Dict[str, Any]:
        """
        机器人批量发送单聊 Markdown 消息

        Args:
            user_ids: 钉钉 userId 列表
            title: 消息标题
            text: Markdown 内容

        Returns:
            发送结果
        """
        if not user_ids:
            raise Exception("user_ids 不能为空")

        token = self.get_access_token()
        url = f"{BASE_URL}/v1.0/robot/oToMessages/batchSend"
        headers = {
            "x-acs-dingtalk-access-token": token,
            "Content-Type": "application/json"
        }
        body = {
            "robotCode": self.app_key,
            "userIds": user_ids,
            "msgKey": "sampleMarkdown",
            "msgParam": json.dumps({"title": title, "text": text}, ensure_ascii=False)
        }

        try:
            resp = requests.post(url, headers=headers, json=body, timeout=10)
            data = resp.json()

            # 钉钉 API 响应格式判断：
            # 1. 有 code 字段：code=0 表示成功
            # 2. 无 code 字段但有 processQueryKey：表示消息已提交（异步处理），视为成功
            is_success = (data.get("code") == 0) or (data.get("code") is None and data.get("processQueryKey"))

            if is_success:
                logger.info(f"[{self.name}] 发送 Markdown 消息成功，接收人: {len(user_ids)} 人")
                return {"success": True, "data": data}
            else:
                logger.error(f"[{self.name}] 发送 Markdown 消息失败: {data}")
                return {"success": False, "data": data}

        except requests.RequestException as e:
            logger.error(f"[{self.name}] 发送 Markdown 消息网络错误: {str(e)}")
            return {"success": False, "error": str(e)}

    def send_to_project_users(self, aliases: List[str], title: str, text: str, msg_type: str = "markdown") -> Dict[str, Any]:
        """
        通过项目的 OA 账号列表发送消息

        Args:
            aliases: oa_user_id 列表（对应 idm.alias）
            title: 消息标题（仅 Markdown 需要）
            text: 消息内容
            msg_type: 消息类型（text/markdown）

        Returns:
            发送结果统计
        """
        dinguserids = []
        not_found = []
        no_dingid = []

        for alias in aliases:
            dinguserid = self.get_dinguserid_by_alias(alias)
            if dinguserid is None:
                not_found.append(alias)
            else:
                dinguserids.append(dinguserid)

        # 去重
        dinguserids = list(set(dinguserids))

        result = {
            "success": True,
            "total": len(aliases),
            "sent": len(dinguserids),
            "not_found": len(not_found),
            "no_dingid": len(no_dingid),
            "details": {
                "sent_count": len(dinguserids),
                "not_found_aliases": not_found,
                "no_dingid_aliases": no_dingid
            }
        }

        if not dinguserids:
            logger.warning(f"[{self.name}] 没有有效的 dinguserid 可发送")
            result["success"] = False
            return result

        # 发送
        if msg_type == "markdown":
            send_result = self.send_single_markdown(dinguserids, title, text)
        else:
            send_result = self.send_single_text(dinguserids, text)

        result["send_result"] = send_result
        if not send_result.get("success"):
            result["success"] = False

        return result


# ==================== 机器人实例管理 ====================
# 在 config/ 或 settings.yaml 中配置，这里先写死示例
BOT_INSTANCES = {
    "industry_chain": DingTalkBotService(
        app_key=os.getenv("DINGTALK_CHAIN_APP_KEY"),
        app_secret=os.getenv("DINGTALK_CHAIN_APP_SECRET"),
        name="产业链智能通知机器人"
    ),
    "train_notice": DingTalkBotService(
        app_key=os.getenv("DINGTALK_TRAIN_APP_KEY"),
        app_secret=os.getenv("DINGTALK_TRAIN_APP_SECRET"),
        name="AI培训通知机器人"
    ),
}


def get_bot(bot_id: str = "industry_chain") -> DingTalkBotService:
    """
    获取机器人实例

    Args:
        bot_id: 机器人ID（对应 BOT_INSTANCES 的 key）

    Returns:
        DingTalkBotService 实例
    """
    if bot_id not in BOT_INSTANCES:
        raise Exception(f"未找到机器人: {bot_id}，可用: {list(BOT_INSTANCES.keys())}")
    return BOT_INSTANCES[bot_id]
