from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import multiprocessing
import asyncio
from datetime import datetime  # 添加这行导入

from auth_routes import router as auth_router
from cas_routes import router as cas_router
from industry_routes import industrial_router
from file_routes import file_router  # 导入新的文件路由
from pipeline_routes import pipeline_router  # 导入产业链自动化处理路由
from services.hotspot_service import HotspotService
from jina_article_routes import router as jina_article_router
from whitelist_routes import router as whitelist_router  # 导入白名单路由
from graph_routes import graph_router  # 导入图谱路由
from user_management_routes import router as user_management_router  # 导入用户管理路由
from dingtalk_routes import router as dingtalk_router  # 导入钉钉机器人路由

from utils.logger import get_logger

# 获取日志记录器
logger = get_logger(__name__)

app = FastAPI()

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有源
    allow_credentials=True,  # 允许携带凭证（如 cookies）
    allow_methods=["*"],  # 允许所有方法（GET、POST 等）
    allow_headers=["*"],  # 允许所有头部
)

# 创建临时上传目录
os.makedirs("temp_uploads", exist_ok=True)

# 注册路由
app.include_router(auth_router)
app.include_router(cas_router)  # 注册CAS单点登录路由
app.include_router(industrial_router)  # 只注册industrial_router
app.include_router(file_router)  # 注册文件路由
app.include_router(pipeline_router)  # 注册产业链自动化处理路由
app.include_router(whitelist_router)  # 注册白名单路由
app.include_router(graph_router)  # 注册图谱路由
app.include_router(user_management_router)  # 注册用户管理路由
app.include_router(dingtalk_router)  # 注册钉钉机器人路由

# 应用启动事件处理
@app.on_event("startup")
async def startup_event():
    """
    应用启动事件处理
    执行各种初始化和预热操作
    """
    # 设置进程名称 - 添加 cyl 标���避免误杀
    try:
        from setproctitle import setproctitle
        setproctitle("cyl_mix_project")
    except ImportError:
        pass

    logger.info("缓存预热服务启动中，正在初始化系统...")

    # 初始化热点监控服务并预热缓存
    await HotspotService.initialize()

    # 启动后台清理任务
    from pipeline_routes import cleanup_old_records_task
    asyncio.create_task(cleanup_old_records_task())
    logger.info("后台清理旧记录任务已启动")

    logger.info("服务初始化完成，系统正常运行")

# 在现有路由注册后添加
@app.get("/")
async def root():
    return {"message": "产业链分析服务正在运行", "docs": "/docs"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

# 注册路由
app.include_router(jina_article_router, prefix="/api", tags=["jina-articles"])
if __name__ == "__main__":
    import uvicorn
    
    workers = 1  
    
    logger.info(f"启动服务器，使用 {workers} 个工作进程")
    
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=8001, 
        reload=True,
        workers=workers,  # 使用基于CPU核心数的工作进程数量
        loop="asyncio"  # 使用asyncio事件循环
    )