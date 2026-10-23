"""
跨线程取消令牌模块

用于在pipeline_routes（主线程/事件循环）和step函数（线程池）之间传递取消信号
"""

import threading


class CancelToken:
    """线程安全的取消令牌"""

    def __init__(self):
        self._cancelled = False
        self._lock = threading.Lock()

    def cancel(self):
        """标记为已取消"""
        with self._lock:
            self._cancelled = True

    def is_cancelled(self) -> bool:
        """检查是否已取消"""
        with self._lock:
            return self._cancelled

    def reset(self):
        """重置令牌"""
        with self._lock:
            self._cancelled = False


# 全局取消令牌字典 {industry_name: CancelToken}
_cancel_tokens: dict[str, CancelToken] = {}
_lock = threading.Lock()


def get_cancel_token(industry_name: str) -> CancelToken:
    """获取或创建指定产业链的取消令牌"""
    with _lock:
        if industry_name not in _cancel_tokens:
            _cancel_tokens[industry_name] = CancelToken()
        return _cancel_tokens[industry_name]


def cancel_task(industry_name: str):
    """取消指定产业链的任务"""
    with _lock:
        if industry_name not in _cancel_tokens:
            _cancel_tokens[industry_name] = CancelToken()
        _cancel_tokens[industry_name].cancel()
        print(f"[CancelToken] 已标记产业链 {industry_name} 为取消状态")


def is_cancelled(industry_name: str) -> bool:
    """检查指定产业链的任务是否已取消"""
    with _lock:
        token = _cancel_tokens.get(industry_name)
        return token.is_cancelled() if token else False


def reset_token(industry_name: str):
    """重置指定产业链的取消令牌（用于开始新任务前）"""
    with _lock:
        if industry_name in _cancel_tokens:
            _cancel_tokens[industry_name].reset()
        else:
            _cancel_tokens[industry_name] = CancelToken()


def clear_cancel_task(industry_name: str):
    """清除指定产业链的取消标记。"""
    reset_token(industry_name)


def remove_token(industry_name: str):
    """移除指定产业链的取消令牌（用于任务完全结束后）"""
    with _lock:
        if industry_name in _cancel_tokens:
            del _cancel_tokens[industry_name]
