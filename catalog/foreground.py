"""Best-effort foreground activation without changing Windows focus policy."""
from pathlib import Path
import os
import time


def explorer_window(path):
    import subprocess,base64
    # Exact folder match, including reused Explorer windows. No path interpolation in code.
    script="""
$target=$env:MEMORIA_OPEN_FOLDER
$shell=New-Object -ComObject Shell.Application
for($i=0;$i -lt 20;$i++) {
 foreach($window in $shell.Windows()) {
  try {
   $folder=$window.Document.Folder.Self.Path
   if([string]::Equals($folder,$target,[StringComparison]::OrdinalIgnoreCase)) {
    [Console]::WriteLine([long]$window.HWND); exit
   }
  } catch {}
 }
 Start-Sleep -Milliseconds 100
}
"""
    env=os.environ.copy();env['MEMORIA_OPEN_FOLDER']=str(path)
    try:
        result=subprocess.run(['powershell.exe','-NoProfile','-EncodedCommand',base64.b64encode(script.encode('utf-16le')).decode('ascii')],env=env,capture_output=True,text=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
        return int(result.stdout.strip()) if result.stdout.strip().isdigit() else None
    except (OSError,subprocess.SubprocessError):return None


def select_in_explorer(shell, ole, path):
    """Use Shell PIDLs so Unicode, commas and quotes never become command syntax."""
    import ctypes as c
    from ctypes import wintypes as w
    shell.ILCreateFromPathW.argtypes=[w.LPCWSTR]
    shell.ILCreateFromPathW.restype=c.c_void_p
    shell.ILFindLastID.argtypes=[c.c_void_p]
    shell.ILFindLastID.restype=c.c_void_p
    shell.SHOpenFolderAndSelectItems.argtypes=[c.c_void_p,w.UINT,c.POINTER(c.c_void_p),w.DWORD]
    shell.SHOpenFolderAndSelectItems.restype=c.c_long
    ole.CoTaskMemFree.argtypes=[c.c_void_p]
    folder=item=None
    try:
        folder=shell.ILCreateFromPathW(str(Path(path).parent))
        item=shell.ILCreateFromPathW(str(path))
        if not folder or not item:
            raise OSError('Windows no ha pogut identificar el vídeo')
        child=shell.ILFindLastID(item)
        children=(c.c_void_p*1)(child)
        result=shell.SHOpenFolderAndSelectItems(folder,1,children,0)
        if result < 0:
            raise OSError('Windows no ha pogut seleccionar el vídeo: '+hex(result & 0xffffffff))
    finally:
        if item:ole.CoTaskMemFree(item)
        if folder:ole.CoTaskMemFree(folder)


def launch_and_focus(path, select_file=False):
    import ctypes as c
    from ctypes import wintypes as w
    user=c.WinDLL('user32',use_last_error=True)
    kernel=c.WinDLL('kernel32',use_last_error=True)
    shell=c.WinDLL('shell32',use_last_error=True)
    ole=c.OleDLL('ole32')
    class EXEC(c.Structure):
        _fields_=[('cbSize',w.DWORD),('fMask',w.ULONG),('hwnd',w.HWND),('lpVerb',w.LPCWSTR),('lpFile',w.LPCWSTR),('lpParameters',w.LPCWSTR),('lpDirectory',w.LPCWSTR),('nShow',c.c_int),('hInstApp',w.HINSTANCE),('lpIDList',c.c_void_p),('lpClass',w.LPCWSTR),('hkeyClass',w.HKEY),('dwHotKey',w.DWORD),('hIcon',w.HANDLE),('hProcess',w.HANDLE)]
    shell.ShellExecuteExW.argtypes=[c.POINTER(EXEC)];shell.ShellExecuteExW.restype=w.BOOL
    kernel.GetProcessId.argtypes=[w.HANDLE];kernel.GetProcessId.restype=w.DWORD
    kernel.CloseHandle.argtypes=[w.HANDLE]
    user.IsWindowVisible.argtypes=[w.HWND];user.IsIconic.argtypes=[w.HWND]
    user.ShowWindowAsync.argtypes=[w.HWND,c.c_int]
    user.SetForegroundWindow.argtypes=[w.HWND];user.SetForegroundWindow.restype=w.BOOL
    user.GetForegroundWindow.restype=w.HWND
    user.GetWindowThreadProcessId.argtypes=[w.HWND,c.POINTER(w.DWORD)]
    user.GetWindowTextW.argtypes=[w.HWND,w.LPWSTR,c.c_int]
    user.SetWindowPos.argtypes=[w.HWND,w.HWND,c.c_int,c.c_int,c.c_int,c.c_int,w.UINT]
    callback=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
    user.EnumWindows.argtypes=[callback,w.LPARAM]
    info=EXEC();info.cbSize=c.sizeof(info);info.fMask=0x40|0x100|0x400
    info.lpVerb='open';info.lpFile=str(path);info.nShow=1
    initialized=ole.CoInitializeEx(None,2)>=0
    try:
        if select_file:
            select_in_explorer(shell,ole,path)
        elif not shell.ShellExecuteExW(c.byref(info)):
            raise c.WinError(c.get_last_error())
        pid=kernel.GetProcessId(info.hProcess) if info.hProcess else 0
    finally:
        if info.hProcess:kernel.CloseHandle(info.hProcess)
        if initialized:ole.CoUninitialize()
    folder=Path(path).parent if select_file else (Path(path) if Path(path).is_dir() else None)
    hwnd=explorer_window(folder) if folder else None
    if not hwnd and not folder:
        name=Path(path).name.casefold()
        for _ in range(20):
            by_pid=[];by_title=[]
            @callback
            def visit(window,param):
                if user.IsWindowVisible(window):
                    current=w.DWORD();user.GetWindowThreadProcessId(window,c.byref(current))
                    if pid and current.value==pid:by_pid.append(window)
                    title=c.create_unicode_buffer(1024);user.GetWindowTextW(window,title,1024)
                    if name in title.value.casefold():by_title.append(window)
                return True
            user.EnumWindows(visit,0)
            if by_pid or by_title:hwnd=(by_pid or by_title)[0];break
            time.sleep(.1)
    if not hwnd:
        import logging
        logging.info('Desktop open: window not identified (folder=%s)',Path(path).is_dir())
        return {'foreground':False,'window_found':False}
    if user.IsIconic(hwnd):user.ShowWindowAsync(hwnd,9)
    raised=raise_temporarily(user,hwnd)
    focused=user.GetForegroundWindow()==hwnd
    import logging
    logging.info('Desktop open: window found, raised=%s, focused=%s (folder=%s)',raised,focused,Path(path).is_dir())
    if not focused:
        class FLASH(c.Structure):
            _fields_=[('cbSize',w.UINT),('hwnd',w.HWND),('flags',w.DWORD),('count',w.UINT),('timeout',w.DWORD)]
        flash=FLASH(c.sizeof(FLASH),hwnd,2,3,0)
        user.FlashWindowEx.argtypes=[c.POINTER(FLASH)]
        user.FlashWindowEx(c.byref(flash))
    return {'foreground':focused,'window_found':True,'raised':raised}


def raise_temporarily(user,hwnd):
    # HWND_TOPMOST briefly changes z-order even when activation is denied.
    # Always undo it: the application must never stay permanently topmost.
    flags=0x1|0x2|0x40|0x10  # NOMOVE, NOSIZE, SHOWWINDOW, NOACTIVATE
    raised=False
    try:
        raised=bool(user.SetWindowPos(hwnd,-1,0,0,0,0,flags))
        user.SetForegroundWindow(hwnd)
        time.sleep(.15)
    finally:
        user.SetWindowPos(hwnd,-2,0,0,0,0,flags)
    return raised
