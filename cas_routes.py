"""
CAS单点登录路由
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, Optional
from pydantic import BaseModel

from services.cas_auth_service import (
    get_cas_login_url,
    get_cas_logout_url,
    cas_login,
    cas_logout as cas_logout_service
)
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth/cas", tags=["CAS认证"])


# ==================== 请求/响应模型 ====================

class LoginRequest(BaseModel):
    """CAS登录请求"""
    ticket: str
    service: str


class LoginResponse(BaseModel):
    """CAS登录响应"""
    access_token: str
    token_type: str = "bearer"
    oa_user_id: str
    user_name: Optional[str] = None
    permission_level: Optional[str] = None


class LoginUrlResponse(BaseModel):
    """登录URL响应"""
    login_url: str


class LogoutResponse(BaseModel):
    """登出响应"""
    logout_url: Optional[str] = None
    message: str


# ==================== 路由 ====================

@router.get("/login-url", response_model=LoginUrlResponse)
async def get_login_url(service: str = Query(..., description="回调地址，CAS登录后会跳转到此地址")):
    """
    获取CAS登录URL

    前端获取此URL后，重定向用户到CAS登录页面
    """
    login_url = get_cas_login_url(service)
    logger.info(f"获取CAS登录URL，service: {service}")
    return {"login_url": login_url}


@router.post("/callback")
async def cas_callback(req: LoginRequest):
    """
    CAS登录回调验证

    流程：
    1. CAS登录成功后，会回调到前端页面，并带上ticket参数
    2. 前端将ticket和service发送给此接口
    3. 后端验证ticket，检查白名单，生成JWT token
    """
    logger.info(f"CAS回调验证，ticket: {req.ticket[:20]}..., service: {req.service}")

    result = await cas_login(req.ticket, req.service)

    if not result["success"]:
        raise HTTPException(status_code=403, detail=result.get("message", "登录失败"))

    return {
        "access_token": result["access_token"],
        "token_type": "bearer",
        "oa_user_id": result["oa_user_id"],
        "user_name": result.get("user_name"),
        "permission_level": result.get("permission_level")
    }


@router.post("/logout", response_model=LogoutResponse)
async def logout(oa_user_id: Optional[str] = Query(None, description="OA账号，如果提供则清除本地token")):
    """
    退出登录

    返回CAS登出URL，前端应重定向到此URL以清除CAS会话
    """
    if oa_user_id:
        cas_logout_service(oa_user_id)

    # 获取登出URL（登出后跳转到首页）
    service = "http://cyltai.liando.cn:3001/"
    logout_url = get_cas_logout_url(service)

    logger.info("用户退出登录")
    return {
        "logout_url": logout_url,
        "message": "登出成功"
    }


@router.get("/config")
async def get_cas_config():
    """
    获取CAS配置信息（前端使用）

    返回CAS登录相关的配置，方便前端调试
    """
    return {
        "cas_server": "http://sso.liando.cn/cas",
        "callback_path": "/login/callback",
        "description": "使用此配置进行CAS单点登录"
    }


# ==================== 使用说明 ====================
"""
登录流程：
=========

1. 前端发起登录
   GET /api/auth/cas/login-url?service=http://cyltai.liando.cn:3001/login/callback
   → 返回: {"login_url": "http://sso.liando.cn/cas/login?service=..."}

2. 前端重定向到CAS
   window.location.href = login_url

3. 用户在CAS页面登录，CAS回调
   → http://cyltai.liando.cn:3001/login/callback?ticket=ST-xxx

4. 前端获取ticket，调用回调接口
   POST /api/auth/cas/callback
   Body: {"ticket": "ST-xxx", "service": "http://cyltai.liando.cn:3001/login/callback"}

5. 后端验证ticket，返回JWT
   → {"access_token": "xxx", "oa_user_id": "gy_zhanghb", ...}

6. 前端存储token，跳转到首页

退出登录：
=========
1. 前端调用 POST /api/auth/cas/logout?oa_user_id=xxx
2. 获取logout_url
3. 清除本地token
4. 重定向到logout_url
"""
