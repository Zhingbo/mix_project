import hashlib
from datetime import datetime
from database.industrial_chain.connection import get_db_connection
from utils.logger import get_logger
from config.auth_config import PASSWORD_HASH_ALGORITHM

logger = get_logger(__name__)

def hash_password(password: str) -> str:
    """对密码进行哈希处理"""
    return hashlib.new(PASSWORD_HASH_ALGORITHM, password.encode()).hexdigest()

def create_user(username: str, password: str) -> dict:
    """创建新用户"""
    hashed_password = hash_password(password)
    
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查用户名是否已存在
            cursor.execute("SELECT id FROM users_info WHERE username = %s", (username,))
            if cursor.fetchone():
                return {"success": False, "message": "用户名已存在"}
            
            # 插入新用户
            created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                "INSERT INTO users_info (username, password, created_at) VALUES (%s, %s, %s)",
                (username, hashed_password, created_at)
            )
            conn.commit()
            
            # 获取新创建的用户ID
            user_id = cursor.lastrowid
            
            return {
                "success": True,
                "user_id": user_id,
                "username": username,
                "created_at": created_at
            }
    except Exception as e:
        logger.error(f"创建用户时出错: {str(e)}")
        return {"success": False, "message": f"创建用户时出错: {str(e)}"}
    finally:
        if 'conn' in locals():
            conn.close()

def authenticate_user(username: str, password: str) -> dict:
    """验证用户凭据"""
    hashed_password = hash_password(password)
    
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, username, created_at FROM users_info WHERE username = %s AND password = %s",
                (username, hashed_password)
            )
            user = cursor.fetchone()
            
            if user:
                return {
                    "success": True,
                    "user_id": user["id"],
                    "username": user["username"],
                    "created_at": user["created_at"]
                }
            else:
                return {"success": False, "message": "用户名或密码不正确"}
    except Exception as e:
        logger.error(f"用户认证时出错: {str(e)}")
        return {"success": False, "message": f"用户认证时出错: {str(e)}"}
    finally:
        if 'conn' in locals():
            conn.close()

def get_user_by_id(user_id: int) -> dict:
    """通过ID获取用户信息"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, username, created_at FROM users_info WHERE id = %s",
                (user_id,)
            )
            user = cursor.fetchone()
            
            if user:
                return {
                    "success": True,
                    "user_id": user["id"],
                    "username": user["username"],
                    "created_at": user["created_at"]
                }
            else:
                return {"success": False, "message": "用户不存在"}
    except Exception as e:
        logger.error(f"获取用户信息时出错: {str(e)}")
        return {"success": False, "message": f"获取用户信息时出错: {str(e)}"}
    finally:
        if 'conn' in locals():
            conn.close() 