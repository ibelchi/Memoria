"""Recycle exactly one file using Windows IFileOperation; no permanent-delete fallback."""
import os
from pathlib import Path


def recycle_file(path):
    if os.name != 'nt':
        raise ValueError('La paperera només està disponible a Windows')
    import ctypes as c
    from ctypes import wintypes as w
    import uuid
    class GUID(c.Structure):
        _fields_ = [('data', c.c_byte * 16)]
        def __init__(self, value):
            super().__init__()
            c.memmove(c.addressof(self), uuid.UUID(value).bytes_le, 16)
    ole = c.OleDLL('ole32')
    shell = c.OleDLL('shell32')
    ole.CoInitializeEx.argtypes = [c.c_void_p, w.DWORD]
    ole.CoCreateInstance.argtypes = [c.POINTER(GUID),c.c_void_p,w.DWORD,c.POINTER(GUID),c.POINTER(c.c_void_p)]
    shell.SHCreateItemFromParsingName.argtypes = [w.LPCWSTR,c.c_void_p,c.POINTER(GUID),c.POINTER(c.c_void_p)]
    def check(hr):
        if hr < 0:
            raise OSError('Windows no ha pogut enviar el fitxer a la paperera (HRESULT '+hex(hr & 0xffffffff)+')')
    def call(obj, index, types, *args):
        table = c.cast(obj,c.POINTER(c.POINTER(c.c_void_p))).contents
        return c.WINFUNCTYPE(c.c_long,c.c_void_p,*types)(table[index])(obj,*args)
    op,item=c.c_void_p(),c.c_void_p()
    initialized=False
    try:
        check(ole.CoInitializeEx(None,2)); initialized=True
        check(ole.CoCreateInstance(c.byref(GUID('3ad05575-8857-4850-9277-11b85bdb8e09')),None,1,c.byref(GUID('947aab5f-0a5c-4c13-b4d6-4bf7836fc9f8')),c.byref(op)))
        # RECYCLEONDELETE | EARLYFAILURE | NOERRORUI | NOCONFIRMATION | SILENT.
        check(call(op,5,[w.DWORD],0x00080000|0x00100000|0x400|0x10|0x4))
        check(shell.SHCreateItemFromParsingName(str(Path(path)),None,c.byref(GUID('43826d1e-e718-42ee-bc55-a1e261c37bfe')),c.byref(item)))
        check(call(op,18,[c.c_void_p,c.c_void_p],item,None))
        check(call(op,21,[]))
        aborted=w.BOOL()
        check(call(op,22,[c.POINTER(w.BOOL)],c.byref(aborted)))
        if aborted.value or Path(path).exists():
            raise OSError('No s’ha completat l’enviament a la paperera; el vídeo es conserva')
    finally:
        if item.value: call(item,2,[])
        if op.value: call(op,2,[])
        if initialized: ole.CoUninitialize()
