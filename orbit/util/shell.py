# Copyright 2026 LCode
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Windows 资源管理器集成。"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.wintypes.HWND),
        ("wFunc", ctypes.wintypes.UINT),
        ("pFrom", ctypes.wintypes.LPCWSTR),
        ("pTo", ctypes.wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", ctypes.wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.wintypes.LPCWSTR),
    ]


def recycle_path(path: Path) -> bool:
    """将文件移入回收站，避免永久删除。

    使用 SHFileOperationW + FOF_ALLOWUNDO。若系统策略禁止回收站操作则返回 False，
    调用方应保留原文件并向用户说明。
    """
    path = Path(path)
    if not path.exists():
        return True
    if sys.platform != "win32":
        return False
    try:
        operation = _SHFILEOPSTRUCTW()
        operation.hwnd = None
        operation.wFunc = FO_DELETE
        operation.pFrom = str(path.resolve()) + "\0"
        operation.pTo = None
        operation.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
        if result != 0:
            log.warning("SHFileOperationW 删除失败，代码 %s：%s", result, path)
            return False
        if operation.fAnyOperationsAborted:
            log.info("用户/系统取消了回收站操作：%s", path)
            return False
        return not path.exists()
    except Exception:
        log.exception("移入回收站失败：%s", path)
        return False
