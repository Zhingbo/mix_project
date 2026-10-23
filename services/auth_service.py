from datetime import datetime, timedelta
import jwt as PyJWT
from typing import Dict, Any, Optional

from database.industrial_chain.user_db import create_user, authenticate_user, get_user_by_id
from utils.logger import get_logger
from config.auth_config import (
    JWT_SECRET_KEY, 
    JWT_ALGORITHM, 
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES
)

logger = get_logger(__name__)

class AuthService:
    @staticmethod
    def register_user(username: str, password: str) -> Dict[str, Any]:
        """
        注册新用户
        """
        logger.info(f"尝试注册新用户: {username}")
        result = create_user(username, password)
        
        if not result["success"]:
            logger.warning(f"用户注册失败: {result['message']}")
            return result
        
        logger.info(f"用户注册成功: {username}")
        return {
            "success": True,
            "message": "用户注册成功",
            "user_id": result["user_id"],
            "username": result["username"]
        }
    
    @staticmethod
    def login_user(username: str, password: str) -> Dict[str, Any]:
        """
        用户登录
        """
        logger.info(f"尝试登录: {username}")
        result = authenticate_user(username, password)
        
        if not result["success"]:
            logger.warning(f"用户登录失败: {result['message']}")
            return result
        
        # 创建访问令牌
        access_token_expires = timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = AuthService.create_access_token(
            data={"sub": username, "user_id": result["user_id"]},
            expires_delta=access_token_expires
        )
        
        logger.info(f"用户登录成功: {username}")
        return {
            "success": True,
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": result["user_id"],
            "username": result["username"]
        }
    
    @staticmethod
    def get_user_info(user_id: int) -> Dict[str, Any]:
        """
        获取用户信息
        """
        return get_user_by_id(user_id)
    
    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """
        创建JWT访问令牌
        """

        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode.update({"exp": expire})
        encoded_jwt = PyJWT.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        return encoded_jwt
    
    @staticmethod
    def decode_token(token: str) -> Dict[str, Any]:
        """
        解码JWT令牌
        """
        try:
            payload = PyJWT.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return {"success": True, "payload": payload}
        except PyJWT.PyJWTError as e:
            logger.error(f"令牌解码失败: {str(e)}")
            return {"success": False, "message": "无效的认证令牌"}
    
    @staticmethod
    def verify_token(token: str) -> Dict[str, Any]:
        """
        验证令牌并获取用户信息
        支持两种类型的 token:
        1. 用户名密码登录: 包含 user_id
        2. CAS SSO登录: 包含 oa_user_id
        """
        decode_result = AuthService.decode_token(token)
        if not decode_result["success"]:
            return decode_result

        payload = decode_result["payload"]

        # CAS SSO 登录的 token
        if "oa_user_id" in payload:
            return {
                "success": True,
                "user": {
                    "user_id": payload.get("oa_user_id"),
                    "oa_user_id": payload.get("oa_user_id"),
                    "username": payload.get("oa_user_id"),
                    "user_name": payload.get("user_name"),
                    "permission_level": payload.get("permission_level", "basic")
                }
            }

        # 用户名密码登录的 token
        user_id = payload.get("user_id")
        if not user_id:
            return {"success": False, "message": "令牌中缺少用户ID"}

        user_result = AuthService.get_user_info(user_id)
        if not user_result["success"]:
            return {"success": False, "message": "无法获取用户信息"}

        return {
            "success": True,
            "user": {
                "user_id": user_result["user_id"],
                "username": user_result["username"],
                "created_at": user_result["created_at"]
            }
        } 