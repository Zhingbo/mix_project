"""
CAS白名单数据库操作
"""
from datetime import datetime
from database.industrial_chain.connection import get_db_connection
from utils.logger import get_logger

logger = get_logger(__name__)


def init_sso_whitelist_table():
    """
    初始化CAS白名单表
    """
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS sso_whitelist (
        id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
        oa_user_id VARCHAR(100) NOT NULL UNIQUE COMMENT 'OA账号',
        user_name VARCHAR(100) DEFAULT NULL COMMENT '用户姓名',
        permission_level VARCHAR(50) DEFAULT 'basic' COMMENT '权限级别: basic, admin',
        is_active TINYINT(1) DEFAULT 1 COMMENT '是否启用: 1启用, 0禁用',
        current_token_jti VARCHAR(100) DEFAULT NULL COMMENT '当前登录Token的JTI',
        last_login_at DATETIME DEFAULT NULL COMMENT '最后登录时间',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        INDEX idx_oa_user_id (oa_user_id),
        INDEX idx_is_active (is_active)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='CAS单点登录白名单表';
    """

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(create_table_sql)
            conn.commit()
            logger.info("CAS白名单表初始化成功")
            return {"success": True, "message": "表初始化成功"}
    except Exception as e:
        logger.error(f"初始化CAS白名单表失败: {str(e)}")
        return {"success": False, "message": f"初始化失败: {str(e)}"}
    finally:
        if 'conn' in locals():
            conn.close()


def add_whitelist_user(oa_user_id: str, user_name: str = None, permission_level: str = "basic") -> dict:
    """
    添加白名单用户

    Args:
        oa_user_id: OA账号
        user_name: 用户姓名
        permission_level: 权限级别

    Returns:
        操作结果
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查用户是否已存在
            cursor.execute("SELECT id FROM sso_whitelist WHERE oa_user_id = %s", (oa_user_id,))
            if cursor.fetchone():
                return {"success": False, "message": f"用户 {oa_user_id} 已存在"}

            # 插入新用户
            cursor.execute(
                "INSERT INTO sso_whitelist (oa_user_id, user_name, permission_level) VALUES (%s, %s, %s)",
                (oa_user_id, user_name or oa_user_id, permission_level)
            )
            conn.commit()
            user_id = cursor.lastrowid

            logger.info(f"添加白名单用户成功: {oa_user_id}")
            return {
                "success": True,
                "message": "添加成功",
                "user_id": user_id,
                "oa_user_id": oa_user_id
            }
    except Exception as e:
        logger.error(f"添加白名单用户失败: {str(e)}")
        return {"success": False, "message": f"添加失败: {str(e)}"}
    finally:
        if 'conn' in locals():
            conn.close()


def get_whitelist_user(oa_user_id: str) -> dict:
    """
    获取白名单用户信息

    Args:
        oa_user_id: OA账号

    Returns:
        用户信息
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, oa_user_id, user_name, permission_level, is_active, current_token_jti, last_login_at FROM sso_whitelist WHERE oa_user_id = %s",
                (oa_user_id,)
            )
            user = cursor.fetchone()

            if user and user.get('is_active'):
                return {
                    "success": True,
                    "user": user
                }
            elif user and not user.get('is_active'):
                return {"success": False, "message": "用户已被禁用"}
            else:
                return {"success": False, "message": "用户不在白名单中"}
    except Exception as e:
        logger.error(f"获取白名单用户失败: {str(e)}")
        return {"success": False, "message": f"查询失败: {str(e)}"}
    finally:
        if 'conn' in locals():
            conn.close()


def update_user_login(oa_user_id: str, token_jti: str) -> dict:
    """
    更新用户登录信息

    Args:
        oa_user_id: OA账号
        token_jti: Token唯一标识

    Returns:
        操作结果
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE sso_whitelist SET current_token_jti = %s, last_login_at = %s WHERE oa_user_id = %s",
                (token_jti, datetime.now(), oa_user_id)
            )
            conn.commit()
            return {"success": True, "message": "更新成功"}
    except Exception as e:
        logger.error(f"更新用户登录信息失败: {str(e)}")
        return {"success": False, "message": f"更新失败: {str(e)}"}
    finally:
        if 'conn' in locals():
            conn.close()


def clear_user_token(oa_user_id: str) -> dict:
    """
    清除用户Token（退出登录）

    Args:
        oa_user_id: OA账号

    Returns:
        操作结果
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE sso_whitelist SET current_token_jti = NULL WHERE oa_user_id = %s",
                (oa_user_id,)
            )
            conn.commit()
            return {"success": True, "message": "清除成功"}
    except Exception as e:
        logger.error(f"清除用户Token失败: {str(e)}")
        return {"success": False, "message": f"清除失败: {str(e)}"}
    finally:
        if 'conn' in locals():
            conn.close()


def list_whitelist_users() -> dict:
    """
    列出所有白名单用户

    Returns:
        用户列表
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, oa_user_id, user_name, permission_level, is_active, last_login_at, created_at FROM sso_whitelist ORDER BY created_at DESC"
            )
            users = cursor.fetchall()
            return {
                "success": True,
                "users": users,
                "count": len(users)
            }
    except Exception as e:
        logger.error(f"获取白名单列表失败: {str(e)}")
        return {"success": False, "message": f"获取失败: {str(e)}"}
    finally:
        if 'conn' in locals():
            conn.close()


def delete_whitelist_user(oa_user_id: str) -> dict:
    """
    删除白名单用户

    Args:
        oa_user_id: OA账号

    Returns:
        操作结果
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM sso_whitelist WHERE oa_user_id = %s", (oa_user_id,))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"删除白名单用户成功: {oa_user_id}")
                return {"success": True, "message": "删除成功"}
            else:
                return {"success": False, "message": "用户不存在"}
    except Exception as e:
        logger.error(f"删除白名单用户失败: {str(e)}")
        return {"success": False, "message": f"删除失败: {str(e)}"}
    finally:
        if 'conn' in locals():
            conn.close()
