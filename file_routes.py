from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Form, Body, Request
from typing import List, Optional
import os
import uuid
from datetime import datetime
import oss2

from services.oss_service import oss_service
from auth_routes import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

# 创建文件路由
file_router = APIRouter(prefix="/api/files", tags=["files"])

@file_router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    folder: Optional[str] = Form("general"),  # 可选参数，指定文件夹，默认为general
    current_user: dict = Depends(get_current_user)
):
    """
    上传单个文件到OSS
    
    Args:
        file: 上传的文件
        folder: 存储的文件夹名称（可选）
        current_user: 当前登录用户
        
    Returns:
        包含文件URL的响应
    """
    try:
        # 检查OSS服务是否配置
        if not oss_service.is_configured:
            raise HTTPException(status_code=500, detail="对象存储服务未正确配置")
        
        # 获取用户ID
        user_id = str(current_user["user_id"])
        
        # 读取文件内容
        await file.seek(0)  # 确保从文件开头读取
        file_content = await file.read()
        
        # 最大文件大小限制 (10MB)
        MAX_FILE_SIZE = 30 * 1024 * 1024
        if len(file_content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="文件大小超过限制(30MB)")
        
        # 获取文件名
        original_filename = file.filename
        
        # 构建OSS路径
        current_date = datetime.now().strftime('%Y%m%d')
        oss_path = f"{folder}/{current_date}/{user_id}/{original_filename}"
        
        # 使用阿里云OSS域名构建URL（预先构建，用于调试和备选）
        if oss_service.oss_domain:
            expected_url = f"https://{oss_service.oss_domain}/{oss_path}"
        else:
            expected_url = f"https://{oss_service.bucket_name}.{oss_service.endpoint}/{oss_path}"
            
        # 记录准备上传的信息
        logger.info(f"准备上传文件: {original_filename} 到 {oss_path}, 预期URL: {expected_url}")
        
        # 上传文件内容到OSS
        file_url = await oss_service.upload_content(
            file_content=file_content,
            oss_path=oss_path,
            user_id=user_id
        )
        
        if not file_url and oss_service.is_configured:
            # 如果未获取到URL但OSS配置正常，使用预构建的URL
            logger.warning(f"未获取到OSS返回的URL，使用预构建的URL: {expected_url}")
            file_url = expected_url
        
        if not file_url:
            raise HTTPException(status_code=500, detail="文件上传失败")
        
        # 记录最终URL
        logger.info(f"文件上传成功: {original_filename}, URL: {file_url}")
        
        return {
            "status": "success",
            "message": "文件上传成功",
            "file_url": file_url,
            "file_name": original_filename
        }
    except Exception as e:
        logger.error(f"文件上传时出错: {str(e)}")
        import traceback
        logger.error(f"详细错误信息: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}")

@file_router.post("/upload-multiple")
async def upload_multiple_files(
    files: List[UploadFile] = File(...),
    folder: str = Form("general"),
    max_concurrent: int = Form(30),  # 增加并发数
    chunk_size: int = Form(8 * 1024 * 1024),  # 增大块大小到8MB
    use_multipart: bool = Form(True),  # 启用分片上传
    current_user: dict = Depends(get_current_user)
):
    """
    上传多个文件到OSS（超高性能版）
    
    Args:
        files: 上传的文件列表
        folder: 存储的文件夹名称
        max_concurrent: 最大并发上传数量
        chunk_size: 分块上传的块大小
        use_multipart: 是否使用分片上传
        current_user: 当前登录用户
        
    Returns:
        包含所有文件URL的响应
    """
    try:
        import asyncio
        import aiohttp
        from aiohttp.client_exceptions import ClientOSError, ServerDisconnectedError
        import io
        from concurrent.futures import ThreadPoolExecutor
        import time
        
        # 检查OSS服务是否配置
        if not oss_service.is_configured:
            raise HTTPException(status_code=500, detail="对象存储服务未正确配置")
        
        # 基础信息
        user_id = str(current_user["user_id"])
        current_date = datetime.now().strftime('%Y%m%d')
        
        # 结果容器
        successful_uploads = []
        failed_uploads = []
        
        # 文件限制
        MAX_FILE_SIZE = 100 * 1024 * 1024  # 增加到100MB
        ALLOWED_EXTENSIONS = ['.doc', '.docx', '.pdf', '.png', '.jpg', '.jpeg', '.txt', '.xlsx', '.csv']
        
        # 提高性能的TCP连接池
        conn = aiohttp.TCPConnector(
            limit=max_concurrent,
            ssl=False,
            force_close=False,
            enable_cleanup_closed=True,
            keepalive_timeout=60,
            ttl_dns_cache=300,  # DNS缓存时间
            limit_per_host=10  # 每个主机的最大连接数
        )
        
        # 高效上传单个文件
        async def upload_single_file(file, semaphore, session, executor):
            start_time = time.time()
            file_size = 0
            
            async with semaphore:
                try:
                    # 检查文件类型
                    filename = file.filename
                    ext = os.path.splitext(filename.lower())[1]
                    content_type = file.content_type or "application/octet-stream"
                    
                    if ext not in ALLOWED_EXTENSIONS:
                        return {
                            "file_name": filename,
                            "status": "error",
                            "message": "不支持的文件类型"
                        }
                    
                    # 获取文件大小 - 修复seek参数错误
                    file_size = 0
                    try:
                        # 读取文件内容以获取大小（对于较大的文件可能不太高效）
                        await file.seek(0)
                        # 尝试从content_length获取大小
                        if hasattr(file, "size") and file.size:
                            file_size = file.size
                        elif getattr(file, "_file", None) and hasattr(file._file, "content_length") and file._file.content_length:
                            file_size = file._file.content_length
                        else:
                            # 如果无法获取size，读取文件内容计算大小（只读取少量内容进行检查）
                            sample_content = await file.read(1024 * 1024)  # 读取前1MB用于检查
                            file_size = len(sample_content)
                            if sample_content:  # 如果有内容，说明文件可能更大
                                logger.warning(f"无法直接获取文件大小，通过采样估计大小: {filename}")
                                # 重置文件指针
                                await file.seek(0)
                    except Exception as e:
                        logger.warning(f"获取文件大小时出错: {e}")
                    
                    # 重置文件指针到开头
                    await file.seek(0)
                    
                    if file_size > MAX_FILE_SIZE:
                        return {
                            "file_name": filename,
                            "status": "error",
                            "message": f"文件大小超过限制({MAX_FILE_SIZE/1024/1024}MB)"
                        }
                    
                    # 构建OSS路径和URL
                    oss_path = f"{folder}/{current_date}/{user_id}/{filename}"
                    if oss_service.oss_domain:
                        file_url = f"https://{oss_service.oss_domain}/{oss_path}"
                    else:
                        file_url = f"https://{oss_service.bucket_name}.{oss_service.endpoint}/{oss_path}"
                    
                    # 根据文件大小选择上传策略 - 增加阈值到50MB，减少分片上传使用频率
                    if file_size > 50 * 1024 * 1024 and use_multipart:  # 只有超过50MB的文件才使用分片上传
                        logger.info(f"使用分片上传大文件: {filename}, 大小: {file_size/1024/1024:.2f}MB")
                        
                        # 分片上传逻辑 - 使用线程池加速IO操作
                        try:
                            # 初始化分片上传
                            def init_multipart():
                                auth = oss_service.auth
                                bucket = oss_service.bucket
                                return bucket.init_multipart_upload(oss_path, headers={"Content-Type": content_type})
                            
                            # 在线程池中运行初始化
                            upload_info = await asyncio.get_event_loop().run_in_executor(
                                executor, init_multipart
                            )
                            
                            # 计算分片数量 (每片大小默认为5MB)
                            part_size = min(10 * 1024 * 1024, max(5 * 1024 * 1024, int(file_size / 20)))  # 根据文件大小动态调整分片大小
                            total_parts = (file_size + part_size - 1) // part_size
                            parts_info = []
                            
                            # 上传分片的函数
                            async def upload_part(part_number, start_pos, size):
                                await file.seek(start_pos)
                                data = await file.read(size)
                                
                                def do_upload_part():
                                    auth = oss_service.auth
                                    bucket = oss_service.bucket
                                    return bucket.upload_part(
                                        oss_path, 
                                        upload_info.upload_id, 
                                        part_number, 
                                        data
                                    )
                                
                                result = await asyncio.get_event_loop().run_in_executor(
                                    executor, do_upload_part
                                )
                                return {"part_number": part_number, "etag": result.etag}
                            
                            # 并发上传所有分片
                            upload_tasks = []
                            for i in range(1, total_parts + 1):
                                start_pos = (i - 1) * part_size
                                size = min(part_size, file_size - start_pos)
                                task = upload_part(i, start_pos, size)
                                upload_tasks.append(task)
                            
                            # 使用有限并发控制分片上传
                            part_semaphore = asyncio.Semaphore(6)  # 限制每个文件的分片并发数
                            
                            async def upload_with_semaphore(task_func):
                                async with part_semaphore:
                                    return await task_func
                            
                            # 包装任务以使用信号量
                            wrapped_tasks = [upload_with_semaphore(task) for task in upload_tasks]
                            part_results = await asyncio.gather(*wrapped_tasks)
                            
                            # 排序分片信息
                            parts_info = sorted(part_results, key=lambda x: x["part_number"])
                            
                            # 完成分片上传
                            def complete_multipart():
                                auth = oss_service.auth
                                bucket = oss_service.bucket
                                parts = [oss2.models.PartInfo(p["part_number"], p["etag"]) for p in parts_info]
                                return bucket.complete_multipart_upload(oss_path, upload_info.upload_id, parts)
                            
                            await asyncio.get_event_loop().run_in_executor(
                                executor, complete_multipart
                            )
                            
                            end_time = time.time()
                            logger.info(f"分片上传完成: {filename}, 耗时: {end_time-start_time:.2f}秒, 速度: {file_size/1024/1024/(end_time-start_time):.2f}MB/s")
                            
                            return {
                                "file_name": filename,
                                "file_url": file_url,
                                "status": "success",
                                "speed": f"{file_size/1024/1024/(end_time-start_time):.2f}MB/s"
                            }
                            
                        except Exception as e:
                            logger.error(f"分片上传失败: {e}, 尝试传统方式上传")
                    
                    # 直接使用传统方式上传，不再使用预签名URL
                    try:
                        await file.seek(0)
                        
                        # 以更大的块读取文件到内存
                        buffer = io.BytesIO()
                        
                        # 优化读取策略
                        chunk = await file.read(chunk_size)
                        while chunk:
                            buffer.write(chunk)
                            chunk = await file.read(chunk_size)
                        
                        buffer.seek(0)
                        
                        # 调用OSS服务上传
                        file_url = await oss_service.upload_content(
                            file_content=buffer.getvalue(),
                            oss_path=oss_path,
                            user_id=user_id
                        )
                        
                        if file_url:
                            end_time = time.time()
                            speed = file_size/1024/1024/(end_time-start_time) if (end_time-start_time) > 0 else 0
                            return {
                                "file_name": filename,
                                "file_url": file_url,
                                "status": "success",
                                "speed": f"{speed:.2f}MB/s"
                            }
                        
                        # 如果未获取到URL但服务配置正常
                        if oss_service.is_configured:
                            end_time = time.time()
                            return {
                                "file_name": filename,
                                "file_url": file_url,
                                "status": "success"
                            }
                        
                        return {
                            "file_name": filename,
                            "status": "error",
                            "message": "文件上传失败"
                        }
                    except Exception as e:
                        logger.error(f"传统方式上传失败: {e}")
                        raise e
                        
                except Exception as e:
                    return {
                        "file_name": getattr(file, "filename", "unknown"),
                        "status": "error",
                        "message": str(e)
                    }
        
        # 创建信号量控制并发（适度并行）
        semaphore = asyncio.Semaphore(min(3, len(files)))  # 最多3个文件同时上传
        
        # 创建线程池执行器，用于IO密集型阻塞操作
        executor = ThreadPoolExecutor(max_workers=3)  # 适度并行
        
        # 使用单一会话以减少建立连接的开销
        client_timeout = aiohttp.ClientTimeout(total=600, connect=30, sock_read=300)
        async with aiohttp.ClientSession(
            connector=conn, 
            timeout=client_timeout,
            raise_for_status=False,  # 手动处理错误
            trust_env=True,  # 信任环境变量中的代理设置
        ) as session:
            # 创建上传任务
            upload_tasks = []
            for file in files:
                task = upload_single_file(file, semaphore, session, executor)
                upload_tasks.append(task)
            
            # 并发执行所有上传任务
            results = await asyncio.gather(*upload_tasks, return_exceptions=True)
        
        # 处理结果
        for result in results:
            if isinstance(result, Exception):
                # 处理异常情况
                failed_uploads.append({
                    "file_name": "unknown",
                    "status": "error",
                    "message": str(result)
                })
            elif isinstance(result, dict) and result.get("status") == "success":
                successful_uploads.append(result)
            else:
                failed_uploads.append(result)
        
        # 关闭线程池
        executor.shutdown(wait=False)
        
        return {
            "status": "success",
            "message": f"成功上传 {len(successful_uploads)} 个文件，失败 {len(failed_uploads)} 个文件",
            "successful_files": successful_uploads,
            "failed_files": failed_uploads
        }
        
    except Exception as e:
        logger.error(f"文件上传处理时出错: {str(e)}")
        import traceback
        logger.error(f"详细错误信息: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}")