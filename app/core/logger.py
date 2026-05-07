"""
WisePick API v0 极简日志模块。使用 Python 标准库 logging，仅用于开发者本地调试。
"""
import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """
    获取 WisePick API 统一格式的 logger。
    
    Args:
        name: logger 名称，如 "decide", "feedback"
        
    Returns:
        配置好的 logger 实例
    """
    logger = logging.getLogger(f"wisepick.{name}")
    
    # 避免重复添加 handler
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # 创建控制台 handler
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        
        # 极简格式：[WISEPICK] [LEVEL] message
        formatter = logging.Formatter('[WISEPICK] [%(levelname)s] %(message)s')
        handler.setFormatter(formatter)
        
        logger.addHandler(handler)
    
    return logger