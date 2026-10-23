"""
用户管理路由
提供用户CRUD操作的API接口
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from database.industrial_chain.sso_whitelist_db import (
    list_whitelist_users,
    add_whitelist_user,
    get_whitelist_user,
    delete_whitelist_user
)
from auth_routes import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/users", tags=["用户管理"])


# ==================== 请求/响应模型 ====================

class UserListItem(BaseModel):
    """用户列表项"""
    id: int
    oa_user_id: str
    user_name: Optional[str] = None
    permission_level: str
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime


class UserListResponse(BaseModel):
    """用户列表响应"""
    success: bool
    users: List[UserListItem]
    count: int


class AddUserRequest(BaseModel):
    """添加用户请求"""
    oa_user_id: str
    user_name: Optional[str] = None
    permission_level: str = "basic"


class UpdateUserRequest(BaseModel):
    """更新用户请求"""
    oa_user_id: str
    user_name: Optional[str] = None
    permission_level: Optional[str] = None
    is_active: Optional[bool] = None


class OperationResponse(BaseModel):
    """操作响应"""
    success: bool
    message: str


# ==================== 权限验证 ====================

async def require_admin(current_user: dict = Depends(get_current_user)):
    """
    要求管理员权限的依赖
    """
    if current_user.get("permission_level") != "admin":
        raise HTTPException(
            status_code=403,
            detail="需要管理员权限"
        )
    return current_user


# ==================== 路由 ====================

@router.get("/list", response_model=UserListResponse)
async def get_users(current_user: dict = Depends(require_admin)):
    """
    获取用户列表

    需要管理员权限
    """
    try:
        result = list_whitelist_users()
        if not result["success"]:
            raise HTTPException(status_code=500, detail=result.get("message"))

        return UserListResponse(
            success=True,
            users=result["users"],
            count=result["count"]
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取用户列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取用户列表失败: {str(e)}")


@router.post("/add", response_model=OperationResponse)
async def add_user(
    user_data: AddUserRequest,
    current_user: dict = Depends(require_admin)
):
    """
    添加新用户

    需要管理员权限
    """
    try:
        result = add_whitelist_user(
            oa_user_id=user_data.oa_user_id,
            user_name=user_data.user_name,
            permission_level=user_data.permission_level
        )

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("message"))

        logger.info(f"用户 {current_user.get('oa_user_id')} 添加了用户 {user_data.oa_user_id}")

        return OperationResponse(
            success=True,
            message=f"用户 {user_data.oa_user_id} 添加成功"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加用户失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"添加用户失败: {str(e)}")


@router.put("/update", response_model=OperationResponse)
async def update_user(
    user_data: UpdateUserRequest,
    current_user: dict = Depends(require_admin)
):
    """
    更新用户信息

    需要管理员权限
    """
    try:
        import pymysql
        from database.industrial_chain.connection import get_db_connection

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 构建更新SQL
            update_fields = []
            params = []

            if user_data.user_name is not None:
                update_fields.append("user_name = %s")
                params.append(user_data.user_name)

            if user_data.permission_level is not None:
                update_fields.append("permission_level = %s")
                params.append(user_data.permission_level)

            if user_data.is_active is not None:
                update_fields.append("is_active = %s")
                params.append(1 if user_data.is_active else 0)

            if not update_fields:
                raise HTTPException(status_code=400, detail="没有要更新的字段")

            params.append(user_data.oa_user_id)
            sql = f"UPDATE sso_whitelist SET {', '.join(update_fields)} WHERE oa_user_id = %s"

            cursor.execute(sql, params)
            conn.commit()

            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="用户不存在")

        conn.close()

        logger.info(f"用户 {current_user.get('oa_user_id')} 更新了用户 {user_data.oa_user_id}")

        return OperationResponse(
            success=True,
            message="用户信息更新成功"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新用户失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新用户失败: {str(e)}")


@router.delete("/delete", response_model=OperationResponse)
async def delete_user(
    oa_user_id: str = Query(..., description="要删除的用户OA账号"),
    current_user: dict = Depends(require_admin)
):
    """
    删除用户

    需要管理员权限
    """
    try:
        # 防止删除自己
        if oa_user_id == current_user.get("oa_user_id"):
            raise HTTPException(status_code=400, detail="不能删除自己的账号")

        result = delete_whitelist_user(oa_user_id)

        if not result["success"]:
            raise HTTPException(status_code=404, detail=result.get("message"))

        logger.info(f"用户 {current_user.get('oa_user_id')} 删除了用户 {oa_user_id}")

        return OperationResponse(
            success=True,
            message=f"用户 {oa_user_id} 删除成功"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除用户失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除用户失败: {str(e)}")


@router.get("/current")
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """
    获取当前登录用户信息
    """
    return {
        "success": True,
        "user": current_user
    }
