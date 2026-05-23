"""异常层级 — 所有异常从 MiniCodeError 继承，便于上层统一捕获。"""


class MiniCodeError(Exception):
    """所有 mini-code 异常的基类"""
    pass


class ConfigError(MiniCodeError):
    """配置相关错误：模型未配置、认证缺失等"""
    pass


class ModelError(MiniCodeError):
    """模型 API 调用相关错误"""
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ModelRateLimitError(ModelError):
    """API 限流"""
    pass


class ModelEmptyResponseError(ModelError):
    """模型返回空响应"""
    pass


class ToolError(MiniCodeError):
    """工具执行错误"""
    def __init__(self, message: str, tool_name: str):
        super().__init__(message)
        self.tool_name = tool_name


class ToolNotFoundError(ToolError):
    """工具未注册"""
    pass


class PermissionError(MiniCodeError):
    """权限拒绝"""
    pass


class PermissionDeniedError(PermissionError):
    """用户拒绝权限请求"""
    pass


class SessionError(MiniCodeError):
    """会话持久化错误"""
    pass


class CompactionError(MiniCodeError):
    """压缩失败（非致命，Agent Loop 应继续）"""
    pass


class CompactionDisabledError(CompactionError):
    """压缩已因连续失败被禁用"""
    pass
