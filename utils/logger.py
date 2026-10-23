import os
import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
import time
from pathlib import Path
from datetime import datetime

# 日志级别映射
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL
}

# 默认日志级别
DEFAULT_LOG_LEVEL = "INFO"

# 日志目录
LOG_DIR = Path("/root/mix_project/logs")
WEBPAGE_REPORT_LOG_DIR = Path("/root/mix_project/logs/webpage_report_progress")

# 确保日志目录存在
LOG_DIR.mkdir(exist_ok=True)
WEBPAGE_REPORT_LOG_DIR.mkdir(parents=True, exist_ok=True)

# 获取当前日期和小时信息
def get_current_datetime_info():
    now = datetime.now()
    date_str = now.strftime('%Y%m%d')
    hour_str = now.strftime('%H')
    return date_str, hour_str

# 创建日期目录
def ensure_daily_log_dir():
    date_str, hour_str = get_current_datetime_info()
    daily_dir = LOG_DIR / date_str
    daily_dir.mkdir(exist_ok=True)
    return daily_dir, date_str, hour_str

# 日志格式 - 修改为与示例更接近的格式
LOG_FORMAT = logging.Formatter(
    "[%(asctime)s][%(levelname)s] %(message)s",
    datefmt='%Y-%m-%d %H:%M:%S'
)

# 网页处理和报告生成专用日志格式（带时间戳）
WEBPAGE_REPORT_LOG_FORMAT = logging.Formatter(
    "[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt='%Y-%m-%d %H:%M:%S'
)

class DailyHourlyFileHandler(logging.Handler):
    """
    自定义日志处理器，同时写入日期目录下的小时日志和当日完整日志
    """
    def __init__(self, encoding='utf-8'):
        super().__init__()
        self.encoding = encoding
        self.setFormatter(LOG_FORMAT)
    
    def emit(self, record):
        try:
            # 获取当前时间信息
            daily_dir, date_str, hour_str = ensure_daily_log_dir()
            
            # 格式化日志消息
            msg = self.format(record)
            
            # 写入日期目录下的小时日志文件
            hourly_log_file = daily_dir / f"{hour_str}.log"
            with open(hourly_log_file, "a", encoding=self.encoding) as f:
                f.write(msg + "\n")
            
            # 写入当日完整日志文件
            daily_log_file = LOG_DIR / f"{date_str}_all.log"
            with open(daily_log_file, "a", encoding=self.encoding) as f:
                f.write(msg + "\n")
                
        except Exception:
            self.handleError(record)

def get_logger(name: str, level: str = None) -> logging.Logger:
    """
    获取日志记录器
    
    参数:
        name: 日志记录器名称
        level: 日志级别，默认为None，将使用环境变量或默认级别
        
    返回:
        logging.Logger: 配置好的日志记录器
    """
    # 获取日志级别
    log_level_str = level or os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL)
    log_level = LOG_LEVELS.get(log_level_str.upper(), logging.INFO)
    
    # 创建日志记录器
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    
    # 避免重复添加处理器
    if not logger.handlers:
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(LOG_FORMAT)
        logger.addHandler(console_handler)
        
        # 自定义日期小时文件处理器
        daily_hourly_handler = DailyHourlyFileHandler()
        logger.addHandler(daily_hourly_handler)
    
    return logger

def get_webpage_report_logger(user_id: str = None) -> logging.Logger:
    """
    获取网页处理和报告生成专用日志记录器
    按小时轮转，只记录INFO级别及以上的日志
    
    参数:
        user_id: 用户ID，可选
        
    返回:
        logging.Logger: 配置好的专用日志记录器
    """
    logger_name = f"webpage_report_{user_id}" if user_id else "webpage_report"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    
    # 避免重复添加处理器
    if not logger.handlers:
        # 按小时轮转的文件处理器
        log_filename = WEBPAGE_REPORT_LOG_DIR / f"webpage_report_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = TimedRotatingFileHandler(
            log_filename,
            when='H',  # 按小时轮转
            interval=1,  # 每1小时轮转一次
            backupCount=24 * 7,  # 保留7天的日志
            encoding='utf-8'
        )
        file_handler.setFormatter(WEBPAGE_REPORT_LOG_FORMAT)
        file_handler.setLevel(logging.INFO)
        logger.addHandler(file_handler)
        
        # 控制台处理器（可选，用于调试）
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(WEBPAGE_REPORT_LOG_FORMAT)
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)
    
    return logger

def log_webpage_report_progress(user_id: str, message: str, log_type: str = "INFO"):
    """
    记录网页处理和报告生成进度的专用函数
    
    参数:
        user_id: 用户ID
        message: 日志消息
        log_type: 日志类型 (INFO, WARNING, ERROR, DEBUG)
    """
    logger = get_webpage_report_logger(user_id)
    log_level = LOG_LEVELS.get(log_type.upper(), logging.INFO)
    
    # 添加用户ID前缀
    formatted_message = f"[User:{user_id}] {message}"
    
    if log_level == logging.DEBUG:
        logger.debug(formatted_message)
    elif log_level == logging.INFO:
        logger.info(formatted_message)
    elif log_level == logging.WARNING:
        logger.warning(formatted_message)
    elif log_level == logging.ERROR:
        logger.error(formatted_message)
    elif log_level == logging.CRITICAL:
        logger.critical(formatted_message)

# 添加log_message函数以保持向后兼容
def log_message(user_id, message, log_type="INFO"):
    """
    日志记录函数，兼容现有代码
    现在使用新的日志存储方式
    
    参数:
        user_id: 用户ID
        message: 日志消息
        log_type: 日志类型 (INFO, WARNING, ERROR, DEBUG)
    """
    # 使用新的日志记录器
    logger = get_logger(f"user_{user_id}")
    log_level = LOG_LEVELS.get(log_type.upper(), logging.INFO)
    
    # 添加用户ID前缀到消息
    formatted_message = f"[User:{user_id}] {message}"
    
    if log_level == logging.DEBUG:
        logger.debug(formatted_message)
    elif log_level == logging.INFO:
        logger.info(formatted_message)
    elif log_level == logging.WARNING:
        logger.warning(formatted_message)
    elif log_level == logging.ERROR:
        logger.error(formatted_message)
    elif log_level == logging.CRITICAL:
        logger.critical(formatted_message)
    
    # 同时记录到网页报告进度日志
    if log_type.upper() in ['INFO', 'WARNING', 'ERROR']:
        log_webpage_report_progress(user_id, message, log_type)