from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
from database.industrial_chain.jina_article_dao import JinaArticleDAO
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

@router.get("/jina-articles/{chain_name}")
async def get_articles_by_chain(
    chain_name: str,
    node_name: Optional[str] = Query(None, description="节点名称（可选）"),
    limit: int = Query(50, description="限制数量"),
    offset: int = Query(0, description="偏移量")
):
    """获取指定产业链的文章列表"""
    try:
        articles = await JinaArticleDAO.get_articles_by_chain(
            chain_name=chain_name,
            node_name=node_name,
            limit=limit,
            offset=offset
        )
        
        return {
            "success": True,
            "data": articles,
            "total": len(articles)
        }
        
    except Exception as e:
        logger.error(f"获取文章列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取文章列表失败: {str(e)}")

@router.get("/jina-articles/content/{article_id}")
async def get_article_content(article_id: int):
    """获取文章完整内容"""
    try:
        article = await JinaArticleDAO.get_article_content(article_id)
        
        if not article:
            raise HTTPException(status_code=404, detail="文章不存在")
        
        return {
            "success": True,
            "data": article
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文章内容失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取文章内容失败: {str(e)}")

@router.get("/jina-articles/statistics")
async def get_statistics(chain_name: Optional[str] = Query(None, description="产业链名称（可选）")):
    """获取文章统计信息"""
    try:
        stats = await JinaArticleDAO.get_statistics(chain_name)
        
        return {
            "success": True,
            "data": stats
        }
        
    except Exception as e:
        logger.error(f"获取统计信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")

@router.delete("/jina-articles/{chain_name}")
async def delete_articles_by_chain(chain_name: str):
    """删除指定产业链的所有文章"""
    try:
        success = await JinaArticleDAO.delete_articles_by_chain(chain_name)
        
        if success:
            return {
                "success": True,
                "message": f"成功删除产业链 {chain_name} 的所有文章"
            }
        else:
            raise HTTPException(status_code=500, detail="删除失败")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除文章失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除文章失败: {str(e)}")

@router.post("/jina-articles/save")
async def save_article_manually(
    url: str,
    title: str,
    content: str,
    chain_name: str,
    node_name: Optional[str] = None
):
    """手动保存文章内容"""
    try:
        success = await JinaArticleDAO.save_article_content(
            url=url,
            title=title,
            content=content,
            chain_name=chain_name,
            node_name=node_name,
            fetch_status=1
        )
        
        if success:
            return {
                "success": True,
                "message": "文章保存成功"
            }
        else:
            raise HTTPException(status_code=500, detail="保存失败")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存文章失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存文章失败: {str(e)}")