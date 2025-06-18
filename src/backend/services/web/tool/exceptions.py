from django.utils.translation import gettext_lazy

from apps.exceptions import CoreException


class ToolException(CoreException):
    MODULE_CODE = "02"


class DataSearchSimpleModeNotSupportedError(ToolException):
    MESSAGE = gettext_lazy("当前暂不支持 '简易模式'(simple) 的数据查询工具")
    STATUS_CODE = 400
    ERROR_CODE = "001"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
