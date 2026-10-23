import os
import yaml
import oss2
from datetime import datetime
from utils.logger import get_logger

logger = get_logger(__name__)

class OssService:
    """阿里云对象存储服务，负责处理文件上传到阿里云OSS"""
    
    def __init__(self):
        """初始化OSS服务，读取配置信息"""
        try:
            # 读取项目配置文件
            with open("config/settings_show.yaml", "r") as file:
                settings = yaml.load(file, Loader=yaml.FullLoader)
            
            # 获取OSS配置
            oss_settings = settings.get('oss_settings', {})
            self.access_key_id = oss_settings.get('access_key_id', '')
            self.access_key_secret = oss_settings.get('access_key_secret', '')
            self.endpoint = oss_settings.get('endpoint', '')
            self.bucket_name = oss_settings.get('bucket_name', '')
            self.oss_domain = oss_settings.get('oss_domain', '')
            
            # 验证配置是否完整
            if not all([self.access_key_id, self.access_key_secret, self.endpoint, self.bucket_name]):
                logger.error("OSS配置不完整，请检查配置文件")
                self.is_configured = False
            else:
                self.is_configured = True
                # 初始化OSS客户端
                self.auth = oss2.Auth(self.access_key_id, self.access_key_secret)
                self.bucket = oss2.Bucket(self.auth, self.endpoint, self.bucket_name)
                logger.info("OSS服务初始化成功")
        except Exception as e:
            logger.error(f"初始化OSS服务失败: {e}")
            self.is_configured = False
    
    async def upload_file(self, local_file_path, oss_path=None, user_id=None):
        """
        上传文件到OSS（优化版）
        
        Args:
            local_file_path: 本地文件路径
            oss_path: OSS上的存储路径，如果为None，则使用文件名作为路径
            user_id: 用户ID，用于日志记录
            
        Returns:
            成功返回文件的访问URL，失败返回None
        """
        if not self.is_configured:
            logger.error("OSS服务未正确配置，无法上传文件")
            return None
        
        try:
            import aiofiles
            import os
            from asyncio import to_thread
            
            # 检查文件是否存在
            if not os.path.exists(local_file_path):
                logger.error(f"要上传的文件不存在: {local_file_path}")
                return None
            
            # 如果未指定OSS路径，则使用文件名
            if oss_path is None:
                file_name = os.path.basename(local_file_path)
                current_date = datetime.now().strftime('%Y%m%d')
                oss_path = f"industry_chain/{current_date}/{user_id}/{file_name}"
            
            # 获取文件大小
            file_size = os.path.getsize(local_file_path)
            
            # 小文件（<5MB）直接上传，大文件使用分块上传
            if file_size < 5 * 1024 * 1024:  # 5MB
                # 使用异步方式上传文件
                async def put_object():
                    try:
                        # 异步读取文件内容
                        async with aiofiles.open(local_file_path, 'rb') as f:
                            file_content = await f.read()
                        
                        # 在线程池中执行阻塞的OSS上传操作
                        def do_upload():
                            return self.bucket.put_object(oss_path, file_content)
                        
                        result = await to_thread(do_upload)
                        return result
                    except Exception as e:
                        logger.error(f"上传文件时出错: {e}")
                        return None
                
                result = await put_object()
            else:
                # 大文件使用分块上传
                # 定义分块大小：1MB
                part_size = 1024 * 1024
                
                async def upload_large_file():
                    try:
                        # 初始化分块上传
                        def init_multipart():
                            return self.bucket.init_multipart_upload(oss_path)
                        
                        upload_id = (await to_thread(init_multipart)).upload_id
                        parts = []
                        
                        # 读取并上传文件分块
                        async with aiofiles.open(local_file_path, 'rb') as f:
                            part_number = 1
                            while True:
                                chunk = await f.read(part_size)
                                if not chunk:
                                    break
                                
                                # 上传分块
                                def upload_part(part_num, data):
                                    return self.bucket.upload_part(
                                        oss_path, upload_id, part_num, data)
                                
                                result = await to_thread(upload_part, part_number, chunk)
                                parts.append(oss2.models.PartInfo(part_number, result.etag))
                                part_number += 1
                        
                        # 完成分块上传
                        def complete_multipart():
                            return self.bucket.complete_multipart_upload(oss_path, upload_id, parts)
                        
                        result = await to_thread(complete_multipart)
                        return result
                    except Exception as e:
                        logger.error(f"分块上传文件时出错: {e}")
                        return None
                
                result = await upload_large_file()
            
            # 检查上传结果
            if result and (hasattr(result, 'status') and result.status == 200):
                logger.info(f"文件上传成功: {local_file_path} -> {oss_path}")
                
                # 构建文件访问URL
                if self.oss_domain:
                    file_url = f"https://{self.oss_domain}/{oss_path}"
                else:
                    file_url = f"https://{self.bucket_name}.{self.endpoint}/{oss_path}"
                
                return file_url
            else:
                status = getattr(result, 'status', 'unknown') if result else 'no result'
                logger.error(f"文件上传失败: {status}")
                return None
        except Exception as e:
            logger.error(f"上传文件时出错: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            return None
    
    async def upload_industry_chain_files(self, industry_name, user_id, pid):
        """
        上传产业链分析相关文件到OSS
        
        Args:
            industry_name: 产业链名称
            user_id: 用户ID
            pid: 进程ID
            
        Returns:
            包含所有上传文件URL的字典
        """
        if not self.is_configured:
            logger.error("OSS服务未正确配置，无法上传文件")
            return {}
        
        try:
            # 构建文件夹路径
            user_folder = f"user_{user_id}_pid_{pid}"
            base_dir = f"resultTxt/{user_folder}"
            
            # 需要上传的文件列表
            files_to_upload = [
                f"{industry_name}_total_info.txt",
                f"nodes_{industry_name}.txt",
                f"relations_{industry_name}.txt"
            ]
            
            # 上传结果
            upload_results = {}
            
            # 上传每个文件
            for file_name in files_to_upload:
                local_file_path = f"{base_dir}/{file_name}"
                
                # 检查文件是否存在
                if not os.path.exists(local_file_path):
                    logger.warning(f"文件不存在，跳过上传: {local_file_path}")
                    continue
                
                # 构建OSS路径
                current_date = datetime.now().strftime('%Y%m%d')
                oss_path = f"industry_chain/{current_date}/{user_id}/{file_name}"
                
                # 上传文件
                file_url = await self.upload_file(local_file_path, oss_path, user_id)
                
                if file_url:
                    upload_results[file_name] = file_url
            
            return upload_results
        except Exception as e:
            logger.error(f"上传产业链文件时出错: {e}")
            return {}

    async def upload_content(self, file_content, oss_path, user_id=None):
        """
        直接上传内存中的文件内容到OSS
        
        Args:
            file_content: 文件内容(bytes)
            oss_path: OSS上的存储路径
            user_id: 用户ID，用于日志记录
            
        Returns:
            成功返回文件的访问URL，失败返回None
        """
        if not self.is_configured:
            logger.error("OSS服务未正确配置，无法上传文件")
            return None
        
        try:
            from asyncio import to_thread
            
            # 构建预期的URL（无论上传是否成功，都需要）
            if self.oss_domain:
                expected_url = f"https://{self.oss_domain}/{oss_path}"
            else:
                expected_url = f"https://{self.bucket_name}.{self.endpoint}/{oss_path}"
            
            # 获取文件大小
            file_size = len(file_content)
            
            # 上传是否成功的标志
            upload_success = False
            
            # 小文件（<5MB）直接上传，大文件使用分块上传
            if file_size < 5 * 1024 * 1024:  # 5MB
                # 使用异步方式上传文件
                async def put_object():
                    try:
                        # 在线程池中执行阻塞的OSS上传操作
                        def do_upload():
                            return self.bucket.put_object(oss_path, file_content)
                        
                        result = await to_thread(do_upload)
                        return result
                    except Exception as e:
                        logger.error(f"上传文件内容时出错: {e}")
                        return None
                
                result = await put_object()
            else:
                # 大文件使用分块上传
                # 定义分块大小：1MB
                part_size = 1024 * 1024
                
                async def upload_large_file():
                    try:
                        # 初始化分块上传
                        def init_multipart():
                            return self.bucket.init_multipart_upload(oss_path)
                        
                        upload_id = (await to_thread(init_multipart)).upload_id
                        parts = []
                        
                        # 处理文件分块
                        total_parts = (file_size + part_size - 1) // part_size
                        
                        for part_number in range(1, total_parts + 1):
                            start = (part_number - 1) * part_size
                            end = min(part_number * part_size, file_size)
                            chunk = file_content[start:end]
                            
                            # 上传分块
                            def upload_part(part_num, data):
                                return self.bucket.upload_part(
                                    oss_path, upload_id, part_num, data)
                            
                            result = await to_thread(upload_part, part_number, chunk)
                            parts.append(oss2.models.PartInfo(part_number, result.etag))
                        
                        # 完成分块上传
                        def complete_multipart():
                            return self.bucket.complete_multipart_upload(oss_path, upload_id, parts)
                        
                        result = await to_thread(complete_multipart)
                        return result
                    except Exception as e:
                        logger.error(f"分块上传文件内容时出错: {e}")
                        import traceback
                        logger.error(f"详细错误信息: {traceback.format_exc()}")
                        return None
                
                result = await upload_large_file()
            
            # 检查上传结果
            if result and (hasattr(result, 'status') and result.status == 200):
                upload_success = True
                logger.info(f"文件内容上传成功: -> {oss_path}")
                logger.info(f"文件访问URL: {expected_url}")
                return expected_url
            else:
                status = getattr(result, 'status', 'unknown') if result else 'no result'
                logger.error(f"文件内容上传失败: {status}")
                return None
                
        except Exception as e:
            logger.error(f"上传文件内容时出错: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            return None

    async def generate_presigned_url(self, oss_path, content_type=None, expires=3600):
        """
        生成OSS预签名URL，用于前端直接上传文件到OSS
        
        Args:
            oss_path: OSS上的存储路径
            content_type: 文件的MIME类型
            expires: URL有效期（秒）
            
        Returns:
            预签名URL字符串
        """
        if not self.is_configured:
            logger.error("OSS服务未正确配置，无法生成预签名URL")
            return None
        
        try:
            from asyncio import to_thread
            
            # 在线程池中执行阻塞的OSS签名操作
            def generate_url():
                # 构建上传请求头
                headers = {}
                if content_type:
                    headers['Content-Type'] = content_type
                
                # 生成签名URL
                url = self.bucket.sign_url('PUT', oss_path, expires, headers=headers)
                return url
            
            presigned_url = await to_thread(generate_url)
            logger.info(f"成功生成预签名URL: {oss_path}, 有效期: {expires}秒")
            
            return presigned_url
        except Exception as e:
            logger.error(f"生成预签名URL时出错: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            return None

# 创建OSS服务实例
oss_service = OssService() 