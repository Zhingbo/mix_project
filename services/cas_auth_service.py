"""
CAS单点登录认证服务
"""
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import uuid
import urllib.parse
import xml.etree.ElementTree as ET
import httpx

from config.auth_config import JWT_SECRET_KEY, JWT_ALGORITHM, JWT_ACCESS_TOKEN_EXPIRE_MINUTES
from database.industrial_chain.sso_whitelist_db import get_whitelist_user, update_user_login, clear_user_token
from utils.logger import get_logger

logger = get_logger(__name__)

# CAS服务器配置
CAS_SERVER_URL = "http://sso.liando.cn/cas"


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> tuple:
    """
    创建JWT Token

    Args:
        data: 要编码的数据
        expires_delta: 过期时间增量

    Returns:
        (token, jti) 元组
    """
    from datetime import datetime
    import jwt as PyJWT

    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES))
    jti = str(uuid.uuid4())
    to_encode.update({"exp": expire, "jti": jti})
    token = PyJWT.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token, jti


def decode_token(token: str) -> Dict[str, Any]:
    """
    解析JWT Token

    Args:
        token: JWT字符串

    Returns:
        解码后的数据

    Raises:
        HTTPException: Token无效时
    """
    import jwt as PyJWT
    from fastapi import HTTPException

    try:
        return PyJWT.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except PyJWT.PyJWTError:
        raise HTTPException(status_code=401, detail="无效的认证凭据")


async def validate_cas_ticket(ticket: str, service: str) -> Dict[str, Any]:
    """
    向CAS服务器验证ticket，获取用户信息

    Args:
        ticket: CAS返回的ticket
        service: 回调服务地址

    Returns:
        包含username的字典

    Raises:
        Exception: 验证失败时
    """
    validate_url = f"{CAS_SERVER_URL}/serviceValidate"
    params = {
        "ticket": ticket,
        "service": service
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(validate_url, params=params)
            if response.status_code != 200:
                logger.error(f"CAS验证失败，状态码: {response.status_code}")
                raise Exception(f"CAS验证失败，状态码: {response.status_code}")

            # 解析CAS响应（XML格式）
            root = ET.fromstring(response.text)

            # CAS响应可能带不同的命名空间，尝试多种方式
            # 方式1: 带命名空间
            ns = {'cas': 'http://www.yale.edu/tp/cas'}
            user_elem = root.find('.//cas:user', ns)

            # 方式2: 不带命名空间
            if user_elem is None:
                user_elem = root.find('.//{http://www.yale.edu/tp/cas}user')

            # 方式3: 直接查找user标签
            if user_elem is None:
                user_elem = root.find('.//user')

            if user_elem is None:
                logger.error(f"CAS响应中未找到用户信息: {response.text[:200]}")
                raise Exception("无效的ticket")

            username = user_elem.text
            logger.info(f"CAS验证成功，用户: {username}")
            return {"username": username}

    except httpx.TimeoutException:
        logger.error("CAS验证超时")
        raise Exception("CAS验证超时")
    except ET.ParseError as e:
        logger.error(f"解析CAS响应失败: {str(e)}")
        raise Exception("解析CAS响应失败")


async def cas_login(ticket: str, service: str) -> Dict[str, Any]:
    """
    CAS登录流程

    Args:
        ticket: CAS ticket
        service: 回调地址

    Returns:
        登录结果，包含token和用户信息
    """
    # 1. 验证ticket
    user_info = await validate_cas_ticket(ticket, service)
    username = user_info.get("username")

    # 2. 检查白名单
    whitelist_result = get_whitelist_user(username)
    if not whitelist_result["success"]:
        logger.warning(f"CAS用户不在白名单或已被禁用: {username}")
        return {
            "success": False,
            "message": whitelist_result.get("message", "无访问权限")
        }

    user = whitelist_result["user"]

    # 3. 生成JWT
    token, jti = create_access_token({
        "oa_user_id": username,
        "user_name": user.get("user_name", username),
        "permission_level": user.get("permission_level", "basic"),
    })

    # 4. 更新登录信息
    update_user_login(username, jti)

    logger.info(f"CAS用户登录成功: {username}")

    return {
        "success": True,
        "access_token": token,
        "token_type": "bearer",
        "oa_user_id": username,
        "user_name": user.get("user_name", username),
        "permission_level": user.get("permission_level", "basic")
    }


def get_cas_login_url(service: str) -> str:
    """
    获取CAS登录URL

    Args:
        service: 回调地址

    Returns:
        CAS登录URL
    """
    encoded_service = urllib.parse.quote(service, safe='')
    return f"{CAS_SERVER_URL}/login?service={encoded_service}"


def get_cas_logout_url(service: str = None) -> str:
    """
    获取CAS登出URL

    Args:
        service: 登出后跳转地址（可选）

    Returns:
        CAS登出URL
    """
    if service:
        encoded_service = urllib.parse.quote(service, safe='')
        return f"{CAS_SERVER_URL}/logout?service={encoded_service}"
    return f"{CAS_SERVER_URL}/logout"


def cas_logout(oa_user_id: str) -> Dict[str, Any]:
    """
    CAS登出

    Args:
        oa_user_id: OA账号

    Returns:
        登出结果
    """
    clear_user_token(oa_user_id)
    logger.info(f"CAS用户登出: {oa_user_id}")
    return {"success": True, "message": "登出成功"}
