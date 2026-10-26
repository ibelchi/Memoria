import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from .core import executable, run_media
from .storage import StorageController
from .workflow import OWNERS
from .desktop import open_desktop_path, restricted_desktop

STATIC = Path(__file__).resolve().parent.parent / 'web'


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, catalog, port=8765, config_file=None):
        self.catalog = catalog
        self.token = secrets.token_urlsafe(32)
        self.request_lock = threading.RLock()
        self.picker_lock = threading.Lock()
        self.storage = StorageController(self, config_file)
        super().__init__(('127.0.0.1', port), Handler)
        self.origin = 'http://127.0.0.1:' + str(self.server_port)


class Handler(BaseHTTPRequestHandler):
    server_version = 'MemoriaLocal/1.0.1'

    def log_message(self, *args):
        pass

    def send_bytes(self, value, kind='application/json; charset=utf-8', status=200, headers=None):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(value)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self'; media-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, val in (headers or {}).items():
            self.send_header(key, val)
        self.end_headers()
        self.wfile.write(value)

    def respond(self, value, status=200):
        self.send_bytes(json.dumps(value, ensure_ascii=False).encode('utf-8'), status=status)

    def guard(self, write=False):
        expected = '127.0.0.1:' + str(self.server.server_port)
        if self.headers.get('Host') != expected:
            raise PermissionError('Host no autoritzat')
        if self.headers.get('Origin') not in (None, self.server.origin):
            raise PermissionError('Origen no autoritzat')
        if self.headers.get('Sec-Fetch-Site') not in (None, 'none', 'same-origin'):
            raise PermissionError('Petició externa rebutjada')
        if (write or self.headers.get('X-Catalog-Token')) and not secrets.compare_digest(self.headers.get('X-Catalog-Token', ''), self.server.token):
            raise PermissionError('El catàleg o la sessió han canviat. Recarrega la pàgina abans de continuar.')

    def body(self):
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            raise ValueError('Cal un cos JSON')
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 100000:
            raise ValueError('Petició massa gran o buida')
        result = json.loads(self.rfile.read(length))
        if not isinstance(result, dict):
            raise ValueError('S’esperava un objecte JSON')
        return result

    def do_GET(self):
        self.handle_request('GET')

    def do_POST(self):
        self.handle_request('POST')

    def do_PATCH(self):
        self.handle_request('PATCH')

    def handle_request(self, method):
        if method != 'GET' and not urlsplit(self.path).path.endswith('/pick'):
            with self.server.request_lock:
                return self.handle_locked(method)
        return self.handle_locked(method)

    def handle_locked(self, method):
        try:
            self.guard(method != 'GET')
            c = self.server.catalog
            parsed = urlsplit(self.path)
            path = parsed.path
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            if method == 'GET':
                if path == '/api/config':
                    self.respond({'app': 'cataleg-videos', 'version': '1.0.1', 'token': self.server.token,
                                  'catalog_id': c.catalog_id, 'data_dir': str(c.data_dir), 'shell_restricted': restricted_desktop(),
                                  'owners': [{'id': ident, 'name': name} for ident, name in OWNERS.items()],
                                  'ffmpeg': bool(executable('ffmpeg')), 'ffprobe': bool(executable('ffprobe'))})
                elif path == '/api/directories':
                    self.guard(True)
                    self.respond(c.browse_directories(query.get('path', '')))
                elif path == '/api/folder-exclusions':
                    self.respond(c.folder_rules())
                elif path == '/api/activity':
                    self.respond(c.recent_activity())
                elif path == '/api/roots':
                    self.respond(c.roots())
                elif path == '/api/folders':
                    self.respond(c.folders())
                elif path == '/api/videos':
                    self.respond(c.videos(query))
                elif path == '/api/tags':
                    self.respond(c.tags())
                elif path == '/api/collections':
                    self.respond(c.collections())
                elif path == '/api/recovery':
                    self.respond(c.recovery())
                elif path == '/api/export':
                    self.send_bytes(json.dumps(c.export(), ensure_ascii=False, indent=2).encode('utf8'),
                                    headers={'Content-Disposition': 'attachment; filename="cataleg-anotacions.json"'})
                elif path.startswith('/api/scans/'):
                    self.respond(c.scan_status(path.rsplit('/', 1)[1]))
                elif re.fullmatch(r'/api/videos/[a-f0-9-]+(?:/(?:stream|thumbnail))?', path):
                    parts = path.split('/')
                    ident = parts[3]
                    v = c.video(ident)
                    if len(parts) == 4:
                        self.respond(v)
                    elif parts[4] == 'stream':
                        self.stream(c.path_for(ident))
                    elif v['demo']:
                        self.sample_thumbnail(v)
                    else:
                        thumb = c.cache / (ident + '.jpg')
                        if not thumb.is_file():
                            self.sample_thumbnail(v, placeholder=True)
                        else:
                            self.send_bytes(thumb.read_bytes(), 'image/jpeg')
                elif path in ('/', '/index.html', '/app.js', '/style.css', '/memoria.svg', '/favicon.svg', '/van.png', '/van.svg'):
                    file = STATIC / ('index.html' if path == '/' else path[1:])
                    if path == '/van.png' and not file.is_file():
                        file = STATIC / 'van.svg'
                    kind = {'.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript', '.svg': 'image/svg+xml', '.png': 'image/png'}[file.suffix]
                    self.send_bytes(file.read_bytes(), kind + '; charset=utf-8')
                else:
                    self.respond({'error': 'No s’ha trobat'}, 404)
            else:
                data = self.body()
                if method == 'PATCH' and re.fullmatch('/api/videos/[a-f0-9-]+', path):
                    self.respond(c.patch(path.rsplit('/', 1)[1], data))
                elif method == 'POST' and re.fullmatch('/api/videos/[a-f0-9-]+/removal-preview', path):
                    self.respond(c.preview_removal(path.split('/')[3], data.get('action')))
                elif method == 'POST' and re.fullmatch('/api/videos/[a-f0-9-]+/removal-confirm', path):
                    self.respond(c.apply_removal(path.split('/')[3], data.get('token')))
                elif method == 'POST' and path == '/api/folder-exclusions/preview':
                    self.respond(c.preview_folder_rule(data.get('root_id'),data.get('folder',''),data.get('remove',False)))
                elif method == 'POST' and path == '/api/folder-exclusions/confirm':
                    self.respond(c.apply_folder_rule(data.get('token')))
                elif method == 'POST' and path == '/api/bulk/shift-dates':
                    self.respond(c.shift_dates(data.get('ids'),data.get('minutes')))
                elif method == 'POST' and path == '/api/collections':
                    self.respond(c.create_collection(data.get('name')), 201)
                elif method == 'PATCH' and re.fullmatch('/api/collections/[a-f0-9-]+', path):
                    self.respond(c.rename_collection(path.rsplit('/', 1)[1], data.get('name')))
                elif method == 'POST' and re.fullmatch('/api/collections/[a-f0-9-]+/members', path):
                    if type(data.get('remove', False)) is not bool:
                        raise ValueError('Operació incorrecta')
                    self.respond(c.collection_members(path.split('/')[3], data.get('ids'), data.get('remove', False)))
                elif method == 'POST' and re.fullmatch('/api/collections/[a-f0-9-]+/delete', path):
                    self.respond(c.delete_collection(path.split('/')[3]))
                elif method == 'POST' and re.fullmatch('/api/videos/[a-f0-9-]+/reveal', path):
                    if os.name != 'nt':
                        raise ValueError('L’obertura de carpetes està disponible a Windows')
                    file=c.path_for(path.split('/')[3])
                    result=open_desktop_path(file, select_file=True)
                    self.respond({'ok': True, **result})
                elif method == 'POST' and path == '/api/recovery/apply':
                    self.respond(c.apply_recovery(data.get('pairs')))
                elif method == 'POST' and path == '/api/bulk/annotation-decision':
                    self.respond(c.annotation_decision(data.get('ids'), data.get('omit')))
                elif method == 'POST' and re.fullmatch('/api/roots/[a-f0-9-]+/owner', path):
                    self.respond(c.set_root_owner(path.split('/')[3], data.get('owner_id'), data.get('apply_existing', False)))
                elif method == 'POST' and path == '/api/storage/preview':
                    self.respond(self.server.storage.preview(data.get('path'), data.get('mode')))
                elif method == 'POST' and path == '/api/storage/apply':
                    self.respond(self.server.storage.apply(data.get('token')))
                elif method == 'POST' and re.fullmatch('/api/roots/[a-f0-9-]+/preview', path):
                    self.respond(c.preview_root(path.split('/')[3], data.get('path')))
                elif method == 'POST' and re.fullmatch('/api/roots/[a-f0-9-]+/relink', path):
                    if not isinstance(data.get('token'), str):
                        raise ValueError('Cal comprovar la carpeta abans de confirmar')
                    self.respond(c.apply_root(path.split('/')[3], data['token']))
                elif method == 'POST' and path == '/api/bulk/tags':
                    if set(data) - {'ids', 'names', 'remove'} or type(data.get('remove', False)) is not bool:
                        raise ValueError('Operació incorrecta')
                    c.apply_tags(data.get('ids'), data.get('names'), data.get('remove', False))
                    self.respond({'ok': True})
                elif method == 'POST' and path in ('/api/roots/pick', '/api/storage/pick'):
                    if not self.server.picker_lock.acquire(blocking=False):
                        raise ValueError('Ja hi ha una selecció de carpeta oberta')
                    try:
                        import sys
                        code = "import tkinter as t,json; from tkinter import filedialog; r=t.Tk(); r.withdraw(); r.attributes('-topmost',True); p=filedialog.askdirectory(title='Selecciona una carpeta'); print(json.dumps(p)); r.destroy()"
                        interpreter = str(Path(sys.executable).with_name('python.exe')) if sys.executable.lower().endswith('pythonw.exe') else sys.executable
                        command = [interpreter, '-c', code]
                        if os.name == 'nt':
                            script = """
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$owner = New-Object System.Windows.Forms.Form
$owner.Text = 'Memoria - Selecciona una carpeta'
$owner.TopMost = $true
$owner.ShowInTaskbar = $true
$owner.StartPosition = 'CenterScreen'
$owner.Size = New-Object System.Drawing.Size(420,100)
$owner.Show()
$owner.Activate()
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = 'Selecciona una carpeta per a Memoria'
$d.ShowNewFolderButton = $false
$p = ''
try {
    if ($d.ShowDialog($owner) -eq 'OK') { $p = $d.SelectedPath }
    ConvertTo-Json -InputObject $p -Compress
} finally { $d.Dispose(); $owner.Close(); $owner.Dispose() }
"""
                            import base64
                            command = ['powershell.exe', '-NoProfile', '-STA', '-EncodedCommand', base64.b64encode(script.encode('utf-16le')).decode('ascii')]
                        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                                timeout=180, check=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                        value = json.loads(result.stdout.strip())
                        self.respond({'path': value} if value else {'cancelled': True})
                    except subprocess.TimeoutExpired:
                        raise ValueError('La selecció de carpeta ha caducat. Torna-ho a provar o escriu la ruta directament.')
                    except subprocess.CalledProcessError:
                        raise ValueError('No s’ha pogut obrir el selector de Windows. Pots escriure la ruta de la carpeta directament.')
                    finally:
                        self.server.picker_lock.release()
                elif method == 'POST' and path == '/api/roots':
                    if not isinstance(data.get('path'), str):
                        raise ValueError('Ruta incorrecta')
                    self.respond({'id': c.add_root(data['path'], data.get('owner_id'))})
                elif method == 'POST' and path == '/api/scans':
                    self.respond({'id': c.start_scan(data.get('root_id'))}, 202)
                elif method == 'POST' and path == '/api/backup':
                    self.respond({'path': str(c.backup())})
                elif method == 'POST' and path == '/api/shutdown':
                    if c.scan_lock.locked():
                        raise ValueError('Espera que acabi l’exploració abans de tancar')
                    c.backup()
                    self.respond({'ok': True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                elif method == 'POST' and re.fullmatch('/api/videos/[a-f0-9-]+/open', path):
                    file = c.path_for(path.split('/')[3])
                    if os.name != 'nt':
                        raise ValueError('L’obertura amb el reproductor del sistema està disponible a Windows')
                    # Only video extensions and catalog IDs may reach the local shell.
                    from .core import EXTENSIONS
                    if file.suffix.lower() not in EXTENSIONS:
                        raise PermissionError('Tipus de fitxer no autoritzat')
                    result=open_desktop_path(file)
                    self.respond({'ok': True, **result})
                else:
                    self.respond({'error': 'Operació no disponible'}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except PermissionError as e:
            self.respond({'error': str(e)}, 403)
        except (FileNotFoundError, KeyError) as e:
            self.respond({'error': str(e)}, 404)
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            self.respond({'error': str(e)}, 400)
        except Exception:
            import logging
            logging.exception('Error del servei local')
            self.respond({'error': 'No s’ha pogut completar. Les anotacions pendents es conserven a la pantalla; torna-ho a provar.'}, 500)

    def stream(self, path):
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        value = self.headers.get('Range')
        if value:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
            if not match or not any(match.groups()):
                self.send_bytes(b'', status=416, headers={'Content-Range': 'bytes */' + str(size)})
                return
            first, last = match.groups()
            if first:
                start = int(first)
                end = min(int(last), end) if last else end
            else:
                start = max(0, size - int(last))
            if start > end or start >= size:
                self.send_bytes(b'', status=416, headers={'Content-Range': 'bytes */' + str(size)})
                return
            status = 206
        with path.open('rb') as file:
            self.send_response(status)
            self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(max(0, end-start+1)))
            self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if status == 206:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            file.seek(start)
            remaining = end-start+1
            while remaining > 0:
                chunk = file.read(min(256*1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def sample_thumbnail(self, v, placeholder=False):
        palette = [('#e9d7b3','#84aeb6','#42717c'), ('#cbd9b8','#75916c','#3b6153'),
                   ('#e8c2a8','#c58565','#765243'), ('#b7c5b3','#63847a','#344d48')]
        a,b,c = palette[int(v['id'].replace('-', '')[:4], 16) % 4]
        label = 'Miniatura pendent' if placeholder else 'MOSTRA FICTÍCIA'
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
        <rect width="640" height="360" fill="{a}"/><circle cx="506" cy="82" r="38" fill="#fff" opacity=".55"/>
        <path d="M0 255L175 104 315 256 427 163 640 300V360H0Z" fill="{b}"/>
        <path d="M0 300Q160 220 340 300T640 272V360H0Z" fill="{c}"/>
        <circle cx="320" cy="165" r="30" fill="#fff" opacity=".75"/><path d="M313 151L334 165 313 179Z" fill="{c}"/>
        <text x="22" y="333" font-family="sans-serif" font-size="15" letter-spacing="2" fill="#fff">{label}</text></svg>'''
        self.send_bytes(svg.encode(), 'image/svg+xml')
