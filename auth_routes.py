from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from typing import Dict, Any
from pydantic import BaseModel

from services.auth_service import AuthService
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# 定义请求和响应模型
class UserCreate(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

# OAuth2密码流
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# 获取当前用户依赖
async def get_current_user(token: str = Depends(oauth2_scheme)):
    """
    从令牌中获取当前用户
    """
    result = AuthService.verify_token(token)
    if not result["success"]:
        raise HTTPException(
            status_code=401,
            detail="无效的认证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return result["user"]

# 注册新用户
@router.post("/register", response_model=Dict[str, Any])
async def register(user_data: UserCreate):
    """
    注册新用户
    """
    result = AuthService.register_user(user_data.username, user_data.password)
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    
    return {
        "message": "用户注册成功"
    }


@router.post("/login", response_model=Token)
async def login(user_data: UserLogin):
    """
    用户登录
    """
    result = AuthService.login_user(user_data.username, user_data.password)
    
    if not result["success"]:
        raise HTTPException(
            status_code=401,
            detail="用户名或密码不正确",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return {"access_token": result["access_token"], "token_type": "bearer"}


# 获取当前用户信息
@router.post("/me", response_model=Dict[str, Any])
async def read_users_me(current_user: dict = Depends(get_current_user)):
    """
    获取当前登录用户的信息
    """
    return current_user