"""
图谱导入路由
"""
import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from typing import Optional
import pandas as pd
import pymysql
from datetime import datetime
from auth_routes import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)
graph_router = APIRouter(prefix="/api/graph", tags=["graph"])


def get_db_connection(db_name="business_data"):
    """获取数据库连接"""
    return pymysql.connect(
        host='8.141.5.67',
        port=3306,
        user='root',
        password=os.getenv('DB_PASSWORD'),
        database=db_name,
        charset='utf8mb4'
    )


@graph_router.post("/import")
async def import_graph_structure(
    file: UploadFile = File(...),
    industry_name: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """
    导入图谱结构
    
    Args:
        file: Excel文件，包含列：编码、产业环节、父级id、级别
        industry_name: 产业链名称
    """
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="只支持Excel文件格式")
    
    try:
        # 读取Excel文件
        contents = await file.read()
        import io
        df = pd.read_excel(io.BytesIO(contents))
        
        # 验证必需列
        required_columns = ['编码', '产业环节', '父级id', '级别']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise HTTPException(
                status_code=400, 
                detail=f"Excel文件缺少必需列: {', '.join(missing_columns)}"
            )
        
        # 清空旧数据
        conn_business = get_db_connection("business_data")
        conn_industrial = get_db_connection("industrial_chain")
        
        cursor_business = conn_business.cursor()
        cursor_industrial = conn_industrial.cursor()
        
        try:
            # 删除旧数据
            cursor_industrial.execute(
                "DELETE FROM industrial_chain_structure WHERE chain_name = %s",
                (industry_name,)
            )
            cursor_business.execute(
                "DELETE FROM chain_needcomp WHERE chain_name = %s",
                (industry_name,)
            )
            
            # 构建节点ID映射
            node_id_map = {}  # {excel_id: db_id}
            current_db_id = 1
            
            # 先获取当前最大ID
            cursor_industrial.execute(
                "SELECT MAX(id) FROM industrial_chain_structure"
            )
            max_id = cursor_industrial.fetchone()[0]
            if max_id:
                current_db_id = max_id + 1
            
            # 获取chain_id（从industrial_chain_meta表）
            cursor_industrial.execute(
                "SELECT id FROM industrial_chain_meta WHERE name = %s",
                (industry_name,)
            )
            result = cursor_industrial.fetchone()
            if result:
                chain_id = result[0]
            else:
                # 如果产业链不存在，创建新记录
                cursor_industrial.execute(
                    "INSERT INTO industrial_chain_meta (name, status) VALUES (%s, 0)",
                    (industry_name,)
                )
                chain_id = cursor_industrial.lastrowid
            
            now = datetime.now()
            
            # 第一遍：创建所有节点（父节点和子节点）
            for _, row in df.iterrows():
                excel_id = row['编码']
                node_name = str(row['产业环节']).strip()
                parent_id_excel = row['父级id'] if pd.notna(row['父级id']) else None
                level = int(row['级别']) if pd.notna(row['级别']) else 1
                
                # 分配数据库ID
                if excel_id not in node_id_map:
                    node_id_map[excel_id] = current_db_id
                    current_db_id += 1
            
            # 第二遍：插入数据
            for _, row in df.iterrows():
                excel_id = row['编码']
                node_name = str(row['产业环节']).strip()
                parent_id_excel = row['父级id'] if pd.notna(row['父级id']) else None
                level = int(row['级别']) if pd.notna(row['级别']) else 1
                
                db_id = node_id_map[excel_id]
                
                # 确定父节点
                parent_node = None
                parent_db_id = None
                if pd.notna(parent_id_excel) and parent_id_excel in node_id_map:
                    parent_db_id = node_id_map[parent_id_excel]
                    # 找到父节点名称
                    parent_row = df[df['编码'] == parent_id_excel]
                    if not parent_row.empty:
                        parent_node = str(parent_row.iloc[0]['产业环节']).strip()
                
                # 插入到 industrial_chain.industrial_chain_structure
                cursor_industrial.execute("""
                    INSERT INTO industrial_chain_structure 
                    (chain_name, nodes, parent_node, parent_id, node_level, create_time, update_time, chain_id, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (industry_name, node_name, parent_node, parent_db_id, level, now, now, chain_id, 2))
                
                # 插入到 business_data.chain_needcomp
                cursor_business.execute("""
                    INSERT INTO chain_needcomp 
                    (chain_name, nodes, parent_node, parent_id, node_level, create_time, update_time, chain_id, STATUS, nodes_definition)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (industry_name, node_name, parent_node, parent_db_id, level, now, now, chain_id, 1, f'{node_name}是{industry_name}产业链的重要环节。'))
            
            conn_industrial.commit()
            conn_business.commit()
            
            logger.info(f"成功导入图谱结构: {industry_name}, 共{len(df)}个节点")
            
            return {
                "status": "success",
                "message": f"成功导入{len(df)}个节点",
                "industry_name": industry_name,
                "node_count": len(df)
            }
            
        except Exception as e:
            conn_industrial.rollback()
            conn_business.rollback()
            raise e
            
        finally:
            cursor_business.close()
            conn_industrial.close()
            conn_business.close()
            conn_industrial.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导入图谱结构失败: {e}")
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")
