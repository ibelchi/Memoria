"""Reproducible synthetic checks; never scans personal disks."""
import ctypes
import json
import platform
import shutil
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path
from catalog.core import Catalog, executable, now


def report():
    with tempfile.TemporaryDirectory() as folder:
        c = Catalog(Path(folder) / 'data')
        c.seed_demo()
        with c.db() as db:
            for i in range(990):
                ident = str(uuid.uuid4())
                db.execute("INSERT INTO videos(id,root_id,relative_path,recorded_at,date_source,demo) VALUES(?,'demo',?,'2026-10-25','sample',1)", (ident, f'Rendiment/{i}.mp4'))
                db.execute('INSERT INTO annotations VALUES(?,?,0,?)', (ident, 'Una escena de prova per mesurar la cerca', now()))
        measurements = []
        for i in range(5):
            start = time.perf_counter()
            result = c.videos({'q': 'escena prova'})
            measurements.append(round((time.perf_counter()-start)*1000, 2))
        ram = None
        if platform.system() == 'Windows':
            from ctypes import wintypes
            class Memory(ctypes.Structure):
                _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [(n,ctypes.c_ulonglong) for n in ['total','available','page','availpage','virtual','availvirtual','ext']]
            m = Memory()
            m.length = ctypes.sizeof(m)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                ram = round(m.total/2**30, 1)
        return {'system': platform.platform(), 'python': platform.python_version(),
                'sqlite': sqlite3.sqlite_version, 'ram_gib': ram,
                'ffmpeg': bool(executable('ffmpeg')), 'ffprobe': bool(executable('ffprobe')),
                'synthetic_videos': 1000, 'matched': result['total'], 'search_ms': measurements,
                'real_media_validation': 'pending', 'originals_scanned': 0}


if __name__ == '__main__':
    print(json.dumps(report(), ensure_ascii=False, indent=2))
