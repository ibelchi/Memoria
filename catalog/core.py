import contextlib
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import unicodedata
import uuid
from .curation import CurationMixin
from .removal import RemovalMixin
from .activity import ActivityMixin
from .identity import IdentityMixin
from .groups import CollectionsMixin
from .workflow import WorkflowMixin, OWNERS, catalog_status

EXTENSIONS = {'.mp4', '.mov', '.m4v', '.mkv', '.avi', '.webm', '.mts', '.m2ts', '.3gp'}


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.casefold())
                   if unicodedata.category(c) != 'Mn' and c != '·')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def executable(name):
    candidate = Path(__file__).resolve().parent.parent / 'tools' / (name + ('.exe' if os.name == 'nt' else ''))
    return str(candidate) if candidate.is_file() else shutil.which(name)


def run_media(args, timeout=30):
    return subprocess.run(args, capture_output=True, timeout=timeout, check=True,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


def within(path, root):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class Catalog(IdentityMixin, CollectionsMixin, WorkflowMixin, ActivityMixin, RemovalMixin, CurationMixin):
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / 'catalog.sqlite3'
        self.cache = self.data_dir / 'thumbnails'
        self.cache.mkdir(exist_ok=True)
        self.scan_lock = threading.Lock()
        self.picker_lock = threading.Lock()
        with self.db() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
            INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM schema_version);
            CREATE TABLE IF NOT EXISTS roots(id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL,
                label TEXT NOT NULL, available INTEGER NOT NULL DEFAULT 1, scanned_at TEXT);
            CREATE TABLE IF NOT EXISTS videos(id TEXT PRIMARY KEY, root_id TEXT REFERENCES roots(id),
                relative_path TEXT NOT NULL, size INTEGER DEFAULT 0, mtime_ns INTEGER DEFAULT 0,
                duration REAL, width INTEGER, height INTEGER, rotation INTEGER,
                container TEXT, codec TEXT, recorded_at TEXT, date_source TEXT,
                date_original TEXT, available INTEGER DEFAULT 1, extraction TEXT DEFAULT 'pending',
                error TEXT, demo INTEGER DEFAULT 0, UNIQUE(root_id,relative_path));
            CREATE TABLE IF NOT EXISTS annotations(video_id TEXT PRIMARY KEY REFERENCES videos(id),
                description TEXT NOT NULL DEFAULT '', reviewed INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tags(id TEXT PRIMARY KEY,name TEXT NOT NULL,key TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS video_tags(video_id TEXT REFERENCES videos(id),
                tag_id TEXT REFERENCES tags(id),PRIMARY KEY(video_id,tag_id));
            CREATE TABLE IF NOT EXISTS scans(id TEXT PRIMARY KEY,root_id TEXT REFERENCES roots(id),
                status TEXT, processed INTEGER DEFAULT 0, errors INTEGER DEFAULT 0,
                started_at TEXT, finished_at TEXT, message TEXT);
            CREATE INDEX IF NOT EXISTS videos_root ON videos(root_id);
            ''')
            if db.execute('SELECT version FROM schema_version').fetchone()[0] not in (1, 2, 3, 4):
                raise ValueError('Versió de catàleg desconeguda. No s’ha modificat.')
        self.migrate_identity()
        self.migrate_collections()
        self.migrate_workflow()
        self.init_removal()
        self.init_curation()
        self.init_activity()

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def roots(self):
        with self.db() as db:
            return [dict(r) for r in db.execute('''SELECT r.*,
                (SELECT COUNT(*) FROM videos v WHERE v.root_id=r.id AND v.retired=0 AND v.demo=0) video_count,
                (SELECT COUNT(*) FROM videos v WHERE v.root_id=r.id AND v.retired=0 AND v.demo=0 AND v.sha256 IS NOT NULL) verified_count
                FROM roots r ORDER BY label''')]

    def browse_directories(self, value=''):
        if not isinstance(value, str) or value.startswith(('\\\\', '//')):
            raise ValueError('Selecciona una carpeta en un disc local')
        if not value.strip():
            if os.name == 'nt':
                import ctypes
                mask = ctypes.windll.kernel32.GetLogicalDrives()
                paths = [Path(chr(65+i)+':/') for i in range(26) if mask & (1 << i)]
            else:
                paths = [Path.home()]
            return {'path': '', 'parent': None, 'folders': [{'name': str(p), 'path': str(p)} for p in paths]}
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError('Aquesta ruta no és una carpeta')
        folders = []
        try:
            for entry in path.iterdir():
                try:
                    if entry.is_dir() and not entry.is_symlink() and not (getattr(entry.lstat(), 'st_file_attributes', 0) & 1024):
                        folders.append({'name': entry.name, 'path': str(entry)})
                except OSError:
                    continue
        except PermissionError:
            raise ValueError('Windows no permet llegir aquesta carpeta. Tria una altra ubicació.')
        folders.sort(key=lambda item: item['name'].casefold())
        return {'path': str(path), 'parent': str(path.parent) if path.parent != path else '', 'folders': folders}

    def add_root(self, value, owner=None):
        owner = self.validate_owner(owner)
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_dir() or path == path.parent:
            raise ValueError('Selecciona una carpeta concreta, no tot el disc.')
        if within(self.data_dir, path) or within(path, self.data_dir):
            raise ValueError('La carpeta de dades ha d’estar separada dels vídeos.')
        for r in self.roots():
            old = Path(r['path'])
            if old == path:
                if r['owner_id'] != owner:
                    raise ValueError('La carpeta ja està incorporada amb un altre propietari. Canvia’l des de Configuració.')
                return r['id']
            if within(path, old) or within(old, path):
                raise ValueError('Aquesta carpeta se solapa amb una arrel existent.')
        ident = str(uuid.uuid4())
        with self.db() as db:
            db.execute('INSERT INTO roots(id,path,label,owner_id) VALUES(?,?,?,?)', (ident, str(path), path.name, owner))
        return ident

    def video(self, ident):
        with self.db() as db:
            row = db.execute('''SELECT v.*,a.description,a.reviewed,a.updated_at,a.omit_annotations,a.favorite,a.excluded,a.video_type,a.date_override,r.label root_label,
                r.path root_path,r.available root_available FROM videos v
                JOIN annotations a ON v.id=a.video_id JOIN roots r ON v.root_id=r.id WHERE v.id=?''', (ident,)).fetchone()
            if row is None:
                raise KeyError('Vídeo desconegut')
            result = dict(row)
            result['tags'] = [dict(t) for t in db.execute('''SELECT t.id,t.name FROM tags t
                JOIN video_tags vt ON t.id=vt.tag_id WHERE vt.video_id=? ORDER BY t.key''', (ident,))]
            result['collections'] = [dict(c) for c in db.execute('''SELECT c.id,c.name FROM collections c
                JOIN collection_videos cv ON cv.collection_id=c.id WHERE cv.video_id=? ORDER BY c.name_key''', (ident,))]
            result['catalog_status'] = catalog_status(result['description'], result['tags'], result['omit_annotations'])
            result['owner_name'] = OWNERS.get(result['owner_id'], 'Pendent d’assignar')
            return self.effective_video(result,self.folder_rules())

    def videos(self, query):
        root = query.get('root', '')
        folder = query.get('folder', '').strip('/')
        words = normalize(query.get('q', '')).split()
        tags = query.get('tags', '').split(',') if query.get('tags') else []
        state = query.get('state', '')
        start, end = query.get('start', ''), query.get('end', '')
        for value in (start, end):
            if value:
                dt.date.fromisoformat(value)
        page = max(1, int(query.get('page', '1')))
        all_items = query.get('limit') == 'all'
        limit = None if all_items else min(100, max(1, int(query.get('limit', '50'))))
        if all_items:
            page = 1
        # Small personal collections: normalized search across fields, with AND semantics.
        with self.db() as db:
            rows = [dict(r) for r in db.execute('''SELECT v.*,a.description,a.reviewed,a.updated_at,a.omit_annotations,a.favorite,a.excluded,a.video_type,a.date_override,
                r.label root_label,r.path root_path,r.available root_available FROM videos v
                JOIN annotations a ON v.id=a.video_id JOIN roots r ON v.root_id=r.id''')]
            by_id = {v['id']: v for v in rows}
            for v in rows:
                v['tags'] = []
            for t in db.execute('''SELECT vt.video_id,t.id,t.name FROM video_tags vt
                JOIN tags t ON t.id=vt.tag_id ORDER BY t.key'''):
                if t['video_id'] in by_id:
                    by_id[t['video_id']]['tags'].append({'id': t['id'], 'name': t['name']})
            members = {r[0] for r in db.execute('SELECT video_id FROM collection_videos WHERE collection_id=?', (query.get('collection', ''),))}
        rules=self.folder_rules()
        matches = []
        for v in rows:
            self.effective_video(v,rules)
            if query.get('video_type') in ('original','montage') and v['video_type']!=query['video_type']:
                continue
            if bool(v['excluded']) != (query.get('excluded') == '1'):
                continue
            v['catalog_status'] = catalog_status(v['description'], v['tags'], v['omit_annotations'])
            if query.get('favorite') == '1' and not v['favorite']:
                continue
            v['owner_name'] = OWNERS.get(v['owner_id'], 'Pendent d’assignar')
            if query.get('owner') == 'unassigned' and v['owner_id'] is not None:
                continue
            if query.get('owner') in OWNERS and v['owner_id'] != query['owner']:
                continue
            if state in ('pending', 'complete', 'empty_by_choice') and v['catalog_status'] != state:
                continue
            if query.get('collection') and v['id'] not in members:
                continue
            if root and v['root_id'] != root:
                continue
            if folder and not v['relative_path'].startswith(folder + '/'):
                continue
            if state == 'unreviewed' and v['reviewed']:
                continue
            if state == 'reviewed' and not v['reviewed']:
                continue
            date = (v['recorded_at'] or '')[:10]
            if query.get('unknown') == '1' and date:
                continue
            if (start or end) and (not date or start and date < start or end and date > end):
                continue
            if not set(tags).issubset({t['id'] for t in v['tags']}):
                continue
            hay = normalize(v['description'] + ' ' + ' '.join(t['name'] for t in v['tags']))
            if not all(word in hay for word in words):
                continue
            matches.append(v)
        known = [v for v in matches if v['recorded_at']]
        unknown = [v for v in matches if not v['recorded_at']]
        known.sort(key=lambda v: (v['recorded_at'], v['id']), reverse=query.get('sort') != 'asc')
        unknown.sort(key=lambda v: v['id'])
        ordered = known + unknown
        return {'items': ordered if all_items else ordered[(page-1)*limit:page*limit],
                'total': len(ordered), 'page': page, 'limit': 'all' if all_items else limit,
                'pages': 1 if all_items else max(1, (len(ordered)+limit-1)//limit)}

    def folders(self):
        with self.db() as db:
            rows = db.execute('SELECT root_id,relative_path FROM videos').fetchall()
        result = set()
        for r in rows:
            p = Path(r['relative_path']).parent
            while str(p) != '.':
                result.add((r['root_id'], p.as_posix()))
                p = p.parent
        return [{'root_id': r, 'path': p} for r, p in sorted(result)]

    def patch(self, ident, data):
        if not data or set(data) - {'description', 'reviewed', 'favorite', 'video_type', 'date_override'}:
            raise ValueError('Camps d’anotació incorrectes')
        if 'description' in data and (not isinstance(data['description'], str) or len(data['description']) > 10000):
            raise ValueError('Descripció massa llarga o incorrecta')
        if 'reviewed' in data and type(data['reviewed']) is not bool:
            raise ValueError('Estat de revisió incorrecte')
        if 'favorite' in data and type(data['favorite']) is not bool:
            raise ValueError('Favorite must be boolean')
        if 'video_type' in data and data['video_type'] not in ('original','montage'):
            raise ValueError('Tipus de vídeo incorrecte')
        if 'date_override' in data:
            data['date_override']=self.validate_date(data['date_override'])
        before=self.video(ident)
        with self.db() as db:
            for key, value in data.items():
                db.execute(f'UPDATE annotations SET {key}=?,updated_at=? WHERE video_id=?', (value, now(), ident))
            for key,label in (('date_override','Data i hora corregides'),('video_type','Tipus de vídeo modificat')):
                if key in data and data[key]!=before[key]:
                    db.execute("INSERT INTO activity(created_at,action,label) VALUES(?,?,?)",(now(),label,before['relative_path']))
            if data.get('description', '').strip():
                db.execute('UPDATE annotations SET omit_annotations=0 WHERE video_id=?', (ident,))
        return self.video(ident)

    def tags(self):
        with self.db() as db:
            return [dict(t) for t in db.execute('SELECT id,name FROM tags ORDER BY key')]

    def apply_tags(self, ids, names, remove=False):
        if not isinstance(ids, list) or not 1 <= len(ids) <= 500:
            raise ValueError('Selecció incorrecta')
        if not isinstance(names, list) or not 1 <= len(names) <= 50:
            raise ValueError('Etiquetes incorrectes')
        cleaned = []
        for name in names:
            if not isinstance(name, str) or not name.strip() or len(name) > 80:
                raise ValueError('Cada etiqueta ha de tenir entre 1 i 80 caràcters')
            cleaned.append(' '.join(name.split()))
        with self.db() as db:
            for ident in ids:
                if not db.execute('SELECT 1 FROM videos WHERE id=?', (ident,)).fetchone():
                    raise ValueError('Selecció de vídeos desconeguda')
            for name in cleaned:
                key = normalize(name)
                row = db.execute('SELECT id FROM tags WHERE key=?', (key,)).fetchone()
                if remove and row is None:
                    continue
                tag = row[0] if row else str(uuid.uuid4())
                if row is None:
                    db.execute('INSERT INTO tags VALUES(?,?,?)', (tag, name, key))
                for ident in ids:
                    if remove:
                        db.execute('DELETE FROM video_tags WHERE video_id=? AND tag_id=?', (ident, tag))
                    else:
                        db.execute('INSERT OR IGNORE INTO video_tags VALUES(?,?)', (ident, tag))
                        db.execute('UPDATE annotations SET omit_annotations=0 WHERE video_id=?', (ident,))

    def path_for(self, ident):
        v = self.video(ident)
        if v['demo']:
            raise FileNotFoundError('Mostra il·lustrativa: no conté una gravació real.')
        if v['retired'] or not v['available']:
            raise FileNotFoundError('La ubicació d’aquest vídeo ha canviat. Explora les carpetes i revisa «Vídeos moguts».')
        root = Path(v['root_path']).resolve(strict=True)
        path = (root / v['relative_path']).resolve(strict=True)
        if not within(path, root) or not path.is_file():
            raise PermissionError('Fitxer fora de les carpetes autoritzades')
        return path

    def start_scan(self, root_id):
        if not executable('ffprobe') or not executable('ffmpeg'):
            raise ValueError('Falten ffprobe i ffmpeg. Consulta README.md per activar els vídeos reals; la demostració funciona sense aquests programes.')
        if not self.scan_lock.acquire(blocking=False):
            raise ValueError('Ja hi ha una exploració en curs')
        ident = str(uuid.uuid4())
        try:
            with self.db() as db:
                root = db.execute('SELECT owner_id FROM roots WHERE id=?', (root_id,)).fetchone()
                if not root:
                    raise ValueError('Carpeta desconeguda')
                self.validate_owner(root['owner_id'])
                db.execute("INSERT INTO scans(id,root_id,status,started_at) VALUES(?,?,'running',?)", (ident, root_id, now()))
            self.begin_scan_activity(ident,root_id)
            threading.Thread(target=self._scan, args=(ident, root_id), daemon=True).start()
        except BaseException:
            self.scan_lock.release()
            raise
        return ident

    def scan_status(self, ident):
        with self.db() as db:
            r = db.execute('SELECT * FROM scans WHERE id=?', (ident,)).fetchone()
            if not r:
                raise KeyError('Exploració desconeguda')
            return dict(r)

    def _scan(self, scan_id, root_id):
        seen, processed, errors = set(), 0, 0
        with self.db() as db:
            before={r['id']:tuple(r)[1:] for r in db.execute('SELECT id,relative_path,size,mtime_ns,sha256 FROM videos WHERE root_id=? AND retired=0',(root_id,))}
        try:
            root = next(r for r in self.roots() if r['id'] == root_id)
            path = Path(root['path'])
            if not path.is_dir():
                with self.db() as db:
                    db.execute('UPDATE roots SET available=0 WHERE id=?', (root_id,))
                raise FileNotFoundError('Carpeta desconnectada; el catàleg es conserva.')
            def fail_walk(error):
                raise error
            for parent, dirs, files in os.walk(path, followlinks=False, onerror=fail_walk):
                def safe_dir(name):
                    p = Path(parent) / name
                    # On Windows skip junctions / reparse points as well as symlinks.
                    return not p.is_symlink() and not (getattr(p.lstat(), 'st_file_attributes', 0) & 1024) and within(p, path)
                dirs[:] = [d for d in dirs if safe_dir(d)]
                for name in files:
                    file = Path(parent) / name
                    if file.suffix.lower() not in EXTENSIONS or file.is_symlink() or not within(file, path):
                        continue
                    relative = file.relative_to(path).as_posix()
                    seen.add(relative)
                    try:
                        self.index_file(root_id, file, relative)
                    except Exception:
                        errors += 1
                    processed += 1
                    with self.db() as db:
                        db.execute('UPDATE scans SET processed=?,errors=? WHERE id=?', (processed, errors, scan_id))
            # Only mark absent after the entire tree was enumerated successfully.
            if not path.is_dir():
                raise FileNotFoundError('El disc s’ha desconnectat durant l’exploració.')
            with self.db() as db:
                for row in db.execute('SELECT id,relative_path FROM videos WHERE root_id=? AND retired=0', (root_id,)).fetchall():
                    db.execute('UPDATE videos SET available=? WHERE id=?', (int(row['relative_path'] in seen), row['id']))
                db.execute('UPDATE roots SET available=1,scanned_at=? WHERE id=?', (now(), root_id))
                db.execute("UPDATE scans SET status='done',finished_at=? WHERE id=?", (now(), scan_id))
        except Exception as e:
            with self.db() as db:
                db.execute("UPDATE scans SET status='error',message=?,finished_at=? WHERE id=?", (str(e), now(), scan_id))
        finally:
            try: self.finish_scan_activity(scan_id,root_id,before)
            finally: self.scan_lock.release()

    def index_file(self, root_id, path, relative):
        ident, needs_extract = self.identify(root_id, path, relative)
        if not needs_extract:
            return ident
        stat = path.stat()
        try:
            probe = json.loads(run_media([executable('ffprobe'), '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)]).stdout)
            stream = next(s for s in probe.get('streams', []) if s.get('codec_type') == 'video')
            fmt = probe.get('format', {})
            duration = max(0, float(fmt.get('duration') or stream.get('duration') or 0))
            original = (fmt.get('tags') or {}).get('creation_time') or (stream.get('tags') or {}).get('creation_time')
            recorded, source = None, None
            if original:
                try:
                    parsed = dt.datetime.fromisoformat(original.replace('Z', '+00:00'))
                    if 1900 < parsed.year <= dt.date.today().year + 1:
                        recorded, source = parsed.isoformat(), 'metadata'
                except ValueError:
                    pass
            if not recorded:
                match = re.search(r'(20\d{2})[-_]?(\d{2})[-_]?(\d{2})', path.stem)
                if match:
                    try:
                        recorded, source = dt.date(*map(int, match.groups())).isoformat(), 'filename'
                    except ValueError:
                        pass
            if not recorded:
                recorded, source = dt.datetime.fromtimestamp(stat.st_mtime).isoformat(), 'mtime'
            rotation = int((stream.get('tags') or {}).get('rotate', 0))
            for side in stream.get('side_data_list', []):
                rotation = int(side.get('rotation', rotation))
            thumb = self.cache / (ident + '.jpg')
            run_media([executable('ffmpeg'), '-nostdin', '-v', 'error', '-ss', str(duration/3), '-i', str(path),
                       '-frames:v', '1', '-vf', 'scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2',
                       '-y', str(thumb)])
            with self.db() as db:
                db.execute('''UPDATE videos SET duration=?,width=?,height=?,rotation=?,container=?,codec=?,recorded_at=?,
                    date_source=?,date_original=?,extraction='ok',error=NULL,available=1 WHERE id=?''',
                    (duration, stream.get('width'), stream.get('height'), rotation, fmt.get('format_name'), stream.get('codec_name'),
                     recorded, source, original, ident))
        except Exception as e:
            with self.db() as db:
                db.execute("UPDATE videos SET extraction='error',error=? WHERE id=?", ('No s’han pogut extreure les metadades o la miniatura (' + type(e).__name__ + ').', ident))
            raise
        return ident

    def export(self):
        with self.db() as db:
            db.execute('BEGIN')
            tables = {t: [dict(r) for r in db.execute('SELECT * FROM ' + t)] for t in
                      ('owners', 'app_meta', 'roots', 'videos', 'annotations', 'tags', 'video_tags', 'collections', 'collection_videos', 'folder_exclusions')}
        return {'format': 'cataleg-videos', 'version': 4, 'exported_at': now(), 'tables': tables}

    def backup(self):
        directory = self.data_dir / 'backups'
        directory.mkdir(exist_ok=True)
        target = directory / ('catalog-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6] + '.sqlite3')
        with self.db() as src, sqlite3.connect(target) as dst:
            src.backup(dst)
        for p in sorted(directory.glob('catalog-*.sqlite3'), reverse=True)[10:]:
            p.unlink()
        return target

    def import_empty(self, document):
        if document.get('format') != 'cataleg-videos' or document.get('version') not in (1, 2, 3, 4):
            raise ValueError('Exportació desconeguda')
        with self.db() as db:
            if db.execute('SELECT 1 FROM roots').fetchone() or db.execute('SELECT 1 FROM collections').fetchone():
                raise ValueError('La importació requereix un catàleg buit')
            if document['version'] == 4:
                if not any(r.get('key') == 'catalog_id' and r.get('value') for r in document['tables'].get('app_meta', [])):
                    raise ValueError('Falta la identitat del catàleg a l’exportació')
                db.execute('DELETE FROM app_meta')
            for table in ('owners', 'app_meta', 'roots', 'videos', 'annotations', 'tags', 'video_tags', 'collections', 'collection_videos', 'folder_exclusions'):
                allowed = {r[1] for r in db.execute('PRAGMA table_info(' + table + ')')}
                if table in ('owners', 'app_meta') and document['version'] < 4:
                    continue
                for row in document['tables'].get(table, []):
                    if not row or set(row) - allowed:
                        raise ValueError('Camps desconeguts a l’exportació')
                    columns = list(row)
                    verb = 'INSERT OR REPLACE' if table == 'owners' else 'INSERT'
                    db.execute(verb+' INTO ' + table + '(' + ','.join(columns) + ') VALUES(' + ','.join('?' for _ in columns) + ')', list(row.values()))

            # JSON restores a snapshot, not a sequence of new user actions.
            db.execute('DELETE FROM activity')

    def seed_demo(self):
        with self.db() as db:
            if db.execute('SELECT 1 FROM roots').fetchone():
                return
            db.execute('INSERT INTO roots(id,path,label) VALUES(?,?,?)', ('demo', str(self.data_dir / 'fictional-media'), 'Mostres fictícies'))
            has_owner = 'owner_id' in {r[1] for r in db.execute('PRAGMA table_info(roots)')}
            if has_owner:
                db.execute("UPDATE roots SET owner_id='belchi' WHERE id='demo'")
            samples = [
                ('Estiu/Platja', 'La petita construeix un castell de sorra a la platja.', ['platja', 'família'], '2026-08-14', 42, 1),
                ('Sortides/Parc', 'La Júlia va en bicicleta i la Núria l’ajuda.', ['Júlia', 'Núria', 'bicicleta'], '2026-09-12', 68, 0),
                ('A casa', 'Bufem les espelmes del pastís d’aniversari.', ['aniversari', 'família'], '2026-07-23', 24, 1),
                ('Sortides/Muntanya', 'Una caminada entre els arbres després de la pluja.', ['muntanya', 'excursió'], '2026-06-08', 96, 0),
                ('A casa', '', [], None, 18, 0),
                ('Estiu/Piscina', 'Salts a la piscina amb els cosins.', ['piscina', 'família'], '2026-08-20', 31, 0),
                ('A casa', 'Preparem galetes de xocolata una tarda de diumenge.', ['cuina', 'xocolata'], '2026-10-04', 75, 1),
                ('Sortides/Parc', 'Observem com les fulles cauen dels arbres.', ['tardor', 'parc'], '2026-10-18', 53, 0),
                ('Estiu/Platja', 'Passeig al costat del mar al capvespre.', ['mar', 'passeig'], '2026-08-15', 82, 0),
                ('A casa', 'Un experiment: mirem què li passa al plàtan.', ['experiment', 'Júlia'], '2026-10-10', 45, 1),
            ]
            for i, (folder, description, tags, date, duration, reviewed) in enumerate(samples):
                ident = str(uuid.uuid5(uuid.NAMESPACE_URL, 'cataleg-demo-' + str(i)))
                db.execute('''INSERT INTO videos(id,root_id,relative_path,duration,width,height,recorded_at,date_source,extraction,demo)
                    VALUES(?,'demo',?,?,1920,1080,?,'sample','sample',1)''', (ident, folder + '/mostra-' + str(i+1) + '.mp4', duration, date))
                db.execute('INSERT INTO annotations(video_id,description,reviewed,updated_at) VALUES(?,?,?,?)', (ident, description, reviewed, now()))
                if has_owner:
                    db.execute("UPDATE videos SET owner_id='belchi' WHERE id=?", (ident,))
        for i, (_, _, tags, _, _, _) in enumerate(samples):
            if tags:
                with self.db() as db:
                    for name in tags:
                        row = db.execute('SELECT id FROM tags WHERE key=?', (normalize(name),)).fetchone()
                        tag_id = row[0] if row else str(uuid.uuid4())
                        if not row:
                            db.execute('INSERT INTO tags VALUES(?,?,?)', (tag_id, name, normalize(name)))
                        db.execute('INSERT OR IGNORE INTO video_tags VALUES(?,?)', (str(uuid.uuid5(uuid.NAMESPACE_URL, 'cataleg-demo-' + str(i))), tag_id))
