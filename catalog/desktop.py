"""Open catalog-authorized paths in the user's Windows desktop session."""
import os

RESTRICTED_MESSAGE = 'Memòria està iniciada en un entorn restringit que no pot obrir finestres de Windows. Tanca l’aplicació des de Configuració i obre Inicia-Memoria.cmd amb doble clic des de Windows. No cal executar com a administrador.'

def restricted_desktop():
    if os.name != 'nt': return False
    import ctypes as c
    from ctypes import wintypes as w
    kernel=c.WinDLL('kernel32',use_last_error=True)
    advapi=c.WinDLL('advapi32',use_last_error=True)
    kernel.GetCurrentProcess.restype=w.HANDLE
    advapi.OpenProcessToken.argtypes=[w.HANDLE,w.DWORD,c.POINTER(w.HANDLE)]
    advapi.IsTokenRestricted.argtypes=[w.HANDLE]
    kernel.CloseHandle.argtypes=[w.HANDLE]
    token=w.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(),8,c.byref(token)):
        return True
    try:return bool(advapi.IsTokenRestricted(token))
    finally:kernel.CloseHandle(token)

def open_desktop_path(path, select_file=False):
    if os.name != 'nt': raise ValueError('Aquesta acció està disponible a Windows')
    if restricted_desktop(): raise ValueError(RESTRICTED_MESSAGE)
    try:
        from .foreground import launch_and_focus
        return launch_and_focus(path, select_file=select_file)
    except OSError as error:
        raise ValueError('Windows no ha pogut obrir aquesta ubicació o aplicació. Comprova els permisos i el reproductor predeterminat. Ruta: '+str(path)) from error
