"""Content identity and explicit, verified relocation. Never writes media files."""
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import time
import uuid


def fingerprint(path):
    size = path.stat().st_size
    digest = hashlib.sha256(str(size).encode())
    with path.open('rb') as file:
        for offset in sorted({0, max(0, size // 2 - 32768), max(0, size - 65536)}):
            file.seek(offset)
            digest.update(file.read(65536))
    return digest.hexdigest()


def full_hash(path):
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('El fitxer ha canviat mentre es llegia. Torna a explorar.')
    return digest.hexdigest()


def media_files(root):
    from .core import EXTENSIONS, within
    def fail(error):
        raise error
    for parent, dirs, files in os.walk(root, followlinks=False, onerror=fail):
        dirs[:] = [d for d in dirs if not (Path(parent)/d).is_symlink()
                   and not (getattr((Path(parent)/d).lstat(), 'st_file_attributes', 0) & 1024)
                   and within(Path(parent)/d, root)]
        for name in files:
            path = Path(parent)/name
            if path.suffix.lower() in EXTENSIONS and not path.is_symlink() and within(path, root):
                yield path


class IdentityMixin:
    def migrate_identity(self):
        with self.db() as db:
            version = db.execute('SELECT version FROM schema_version').fetchone()[0]
        if version in (2, 3, 4):
            return
        if version != 1:
            raise ValueError('Versió de catàleg desconeguda')
        self.backup()  # Complete consistent copy before the schema transaction.
        db = sqlite3.connect(self.db_path, timeout=15)
        try:
            db.execute('PRAGMA foreign_keys=OFF')
            db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE videos_new(
                id TEXT PRIMARY KEY,root_id TEXT REFERENCES roots(id),relative_path TEXT NOT NULL,
                size INTEGER DEFAULT 0,mtime_ns INTEGER DEFAULT 0,duration REAL,width INTEGER,height INTEGER,
                rotation INTEGER,container TEXT,codec TEXT,recorded_at TEXT,date_source TEXT,date_original TEXT,
                available INTEGER DEFAULT 1,extraction TEXT DEFAULT 'pending',error TEXT,demo INTEGER DEFAULT 0,
                fingerprint TEXT,sha256 TEXT,identity_state TEXT DEFAULT 'unverified',retired INTEGER NOT NULL DEFAULT 0)''')
            columns = [r[1] for r in db.execute('PRAGMA table_info(videos)')]
            fields = ','.join(columns)
            db.execute('INSERT INTO videos_new('+fields+') SELECT '+fields+' FROM videos')
            db.execute('DROP TABLE videos')
            db.execute('ALTER TABLE videos_new RENAME TO videos')
            db.execute('CREATE INDEX videos_root ON videos(root_id)')
            db.execute('CREATE UNIQUE INDEX video_current_location ON videos(root_id,relative_path) WHERE retired=0')
            db.execute('CREATE INDEX video_content ON videos(sha256)')
            db.execute('UPDATE schema_version SET version=2')
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('La migració no ha superat la comprovació de relacions')
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def identify(self, root_id, path, relative):
        from .core import now
        stat = path.stat()
        quick = fingerprint(path)
        with self.db() as db:
            row = db.execute('SELECT * FROM videos WHERE root_id=? AND relative_path=? AND retired=0', (root_id, relative)).fetchone()
            previous = dict(row) if row else None
        unchanged = (previous and previous['size'] == stat.st_size and previous['mtime_ns'] == stat.st_mtime_ns
                     and previous['fingerprint'] == quick and previous['sha256'])
        sha = previous['sha256'] if unchanged else full_hash(path)
        final = path.stat()
        if (stat.st_size, stat.st_mtime_ns) != (final.st_size, final.st_mtime_ns):
            raise ValueError('El fitxer ha canviat durant la identificació')
        # Legacy annotations get their first baseline only at the unchanged original location.
        same = previous and (previous['sha256'] == sha or
                             not previous['sha256'] and previous['size'] == stat.st_size
                             and previous['mtime_ns'] == stat.st_mtime_ns)
        with self.db() as db:
            if same:
                ident = previous['id']
                db.execute('''UPDATE videos SET size=?,mtime_ns=?,fingerprint=?,sha256=?,available=1,
                    identity_state=CASE WHEN identity_state='unverified' THEN 'tracked' ELSE identity_state END WHERE id=?''',
                           (stat.st_size, stat.st_mtime_ns, quick, sha, ident))
                needs_extract = previous['extraction'] != 'ok' or not (self.cache/(ident+'.jpg')).is_file()
                return ident, needs_extract
            if previous:
                # A different file at the same name must never inherit the original annotations.
                db.execute('UPDATE videos SET retired=1,available=0 WHERE id=?', (previous['id'],))
            ident = str(uuid.uuid4())
            owner = db.execute('SELECT owner_id FROM roots WHERE id=?', (root_id,)).fetchone()
            if not owner:
                raise ValueError('Carpeta desconeguda')
            self.validate_owner(owner['owner_id'])
            db.execute('''INSERT INTO videos(id,root_id,relative_path,size,mtime_ns,fingerprint,sha256,identity_state)
                VALUES(?,?,?,?,?,?,?,'new')''', (ident, root_id, relative, stat.st_size, stat.st_mtime_ns, quick, sha))
            db.execute('UPDATE videos SET owner_id=? WHERE id=?', (owner['owner_id'], ident))
            db.execute('INSERT INTO annotations(video_id,updated_at) VALUES(?,?)', (ident, now()))
        return ident, True

    def recovery(self):
        with self.db() as db:
            rows = [dict(r) for r in db.execute('''SELECT v.*,r.path root_path,r.available root_available,
                a.description,a.reviewed,(SELECT COUNT(*) FROM video_tags WHERE video_id=v.id) tag_count
                FROM videos v JOIN roots r ON v.root_id=r.id JOIN annotations a ON a.video_id=v.id WHERE v.demo=0''')]
        missing, targets = {}, {}
        for v in rows:
            path = Path(v['root_path'])/v['relative_path']
            absent = v['retired'] or not v['available'] or not v['root_available'] or not path.is_file()
            if absent:
                if v['sha256']:
                    missing.setdefault(v['sha256'], []).append(v)
            elif v['identity_state'] == 'new' and not v['description'] and not v['reviewed'] and not v['tag_count']:
                targets.setdefault(v['sha256'], []).append(v)
        groups = []
        for sha, sources in missing.items():
            options = targets.get(sha, [])
            for source in sources:
                groups.append({'source': self.video(source['id']),
                               'targets': [self.video(t['id']) for t in options],
                               'unique': len(sources) == 1 and len(options) == 1})
        # Keep legacy missing entries visible even if no fingerprint was recorded before moving.
        for v in rows:
            if not v['sha256'] and (v['retired'] or not v['available'] or not v['root_available']):
                groups.append({'source': self.video(v['id']), 'targets': [], 'unique': False})
        return groups

    def apply_recovery(self, pairs):
        if not isinstance(pairs, list) or not 1 <= len(pairs) <= 500:
            raise ValueError('Selecció incorrecta')
        ids = []
        for pair in pairs:
            if not isinstance(pair, dict) or set(pair) != {'source_id', 'target_id'}:
                raise ValueError('Parella de recuperació incorrecta')
            if not all(isinstance(v, str) for v in pair.values()):
                raise ValueError('Identificadors incorrectes')
            ids.extend(pair.values())
        if len(set(ids)) != len(ids):
            raise ValueError('No es pot assignar un vídeo dues vegades')
        if not self.scan_lock.acquire(blocking=False):
            raise ValueError('Espera que acabi l’exploració')
        try:
            # Hash again immediately before committing; previews are not authority.
            verified = []
            for pair in pairs:
                source, target = self.video(pair['source_id']), self.video(pair['target_id'])
                if not source['sha256'] or source['sha256'] != target['sha256'] or source['demo'] or target['demo']:
                    raise ValueError('Els continguts dels dos vídeos no coincideixen')
                if source['available'] and not source['retired'] and (Path(source['root_path'])/source['relative_path']).is_file():
                    raise ValueError('L’original encara és disponible; no es fusionen còpies')
                destination = self.path_for(target['id'])
                initial_stat = destination.stat()
                if (initial_stat.st_size, initial_stat.st_mtime_ns) != (target['size'], target['mtime_ns']):
                    raise ValueError('El fitxer de destinació ha canviat. Torna a explorar.')
                if full_hash(destination) != source['sha256']:
                    raise ValueError('El fitxer de destinació ha canviat. Torna a explorar.')
                st = destination.stat()
                if (st.st_size, st.st_mtime_ns) != (initial_stat.st_size, initial_stat.st_mtime_ns):
                    raise ValueError('El fitxer ha canviat durant la comprovació')
                verified.append((source, target, st))
            self.backup()
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                for source, target, st in verified:
                    current_source = db.execute('SELECT sha256,available,retired FROM videos WHERE id=?', (source['id'],)).fetchone()
                    if not current_source or current_source['sha256'] != source['sha256']:
                        raise ValueError('La identitat original ha canviat')
                    if not current_source['retired'] and (Path(source['root_path'])/source['relative_path']).is_file():
                        raise ValueError('L’original torna a estar disponible; no es fusionen còpies')
                    destination = Path(target['root_path'])/target['relative_path']
                    final_stat = destination.stat()
                    if (final_stat.st_size, final_stat.st_mtime_ns) != (st.st_size, st.st_mtime_ns):
                        raise ValueError('El fitxer ha canviat abans de desar')
                    current = db.execute('''SELECT v.*,a.description,a.reviewed,
                        (SELECT COUNT(*) FROM video_tags WHERE video_id=v.id) tag_count FROM videos v
                        JOIN annotations a ON a.video_id=v.id WHERE v.id=?''', (target['id'],)).fetchone()
                    if (not current or current['identity_state'] != 'new' or current['retired']
                            or current['description'] or current['reviewed'] or current['tag_count']
                            or current['sha256'] != source['sha256']):
                        raise ValueError('El vídeo nou ja té anotacions o ha canviat; no es fusionarà')
                    db.execute('''INSERT OR IGNORE INTO collection_videos(collection_id,video_id)
                        SELECT collection_id,? FROM collection_videos WHERE video_id=?''', (source['id'], target['id']))
                    db.execute('DELETE FROM collection_videos WHERE video_id=?', (target['id'],))
                    db.execute('DELETE FROM annotations WHERE video_id=?', (target['id'],))
                    db.execute('DELETE FROM videos WHERE id=?', (target['id'],))
                    db.execute('''UPDATE videos SET root_id=?,relative_path=?,size=?,mtime_ns=?,fingerprint=?,
                        available=1,retired=0,identity_state='tracked' WHERE id=?''',
                               (target['root_id'], target['relative_path'], st.st_size, st.st_mtime_ns,
                                target['fingerprint'], source['id']))
            for source, target, _ in verified:
                old, new = self.cache/(source['id']+'.jpg'), self.cache/(target['id']+'.jpg')
                if not old.is_file() and new.is_file():
                    shutil.copyfile(new, old)
            return {'recovered': len(verified)}
        finally:
            self.scan_lock.release()

    def validate_root_path(self, root_id, value):
        from .core import within
        if not isinstance(value, str):
            raise ValueError('Ruta incorrecta')
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_dir() or path == path.parent or within(self.data_dir, path) or within(path, self.data_dir):
            raise ValueError('Selecciona una carpeta de vídeos separada de les dades del catàleg')
        for r in self.roots():
            if r['id'] != root_id and (within(path, Path(r['path'])) or within(Path(r['path']), path)):
                raise ValueError('La nova carpeta se solapa amb una altra arrel')
        return path

    def preview_root(self, root_id, value):
        if not self.scan_lock.acquire(blocking=False):
            raise ValueError('Espera que acabi l’exploració')
        try:
            path = self.validate_root_path(root_id, value)
            root = next((r for r in self.roots() if r['id'] == root_id), None)
            if not root or root_id == 'demo':
                raise ValueError('Carpeta desconeguda o de demostració')
            with self.db() as db:
                originals = [dict(v) for v in db.execute('SELECT * FROM videos WHERE root_id=? AND retired=0', (root_id,))]
            known = {}
            for v in originals:
                if v['sha256']:
                    known.setdefault((v['size'], v['fingerprint']), []).append(v)
            found = {}
            for file in media_files(path):
                st = file.stat()
                if not any(key[0] == st.st_size for key in known):
                    continue
                quick = fingerprint(file)
                if (st.st_size, quick) not in known:
                    continue
                sha = full_hash(file)
                found.setdefault(sha, []).append({'relative_path': file.relative_to(path).as_posix(),
                                                 'size': st.st_size, 'mtime_ns': st.st_mtime_ns, 'fingerprint': quick})
            by_hash = {}
            for v in originals:
                if v['sha256']:
                    by_hash.setdefault(v['sha256'], []).append(v)
            matches = {}
            ambiguous = 0
            for sha, sources in by_hash.items():
                dests = found.get(sha, [])
                if len(sources) == 1 and len(dests) == 1:
                    matches[sources[0]['id']] = dict(dests[0], sha256=sha)
                elif dests:
                    ambiguous += len(sources)
            if not matches and not ambiguous:
                raise ValueError('No s’ha pogut verificar cap vídeo. Explora la ubicació original abans de moure-la, o afegeix aquesta carpeta com a nova.')
            token = secrets.token_urlsafe(24)
            if not hasattr(self, 'root_plans'):
                self.root_plans = {}
            self.root_plans = {k: v for k, v in self.root_plans.items() if v['expires'] > time.monotonic()}
            self.root_plans[token] = {'root_id': root_id, 'old_path': root['path'], 'path': str(path),
                                      'matches': matches, 'expires': time.monotonic()+900}
            return {'token': token, 'path': str(path), 'matched': len(matches), 'ambiguous': ambiguous,
                    'unmatched': len(originals)-len(matches)-ambiguous, 'total': len(originals)}
        finally:
            self.scan_lock.release()

    def apply_root(self, root_id, token):
        plan = getattr(self, 'root_plans', {}).get(token)
        if not plan or plan['root_id'] != root_id or plan['expires'] < time.monotonic():
            raise ValueError('La comprovació ha caducat. Torna a seleccionar la carpeta.')
        if not self.scan_lock.acquire(blocking=False):
            raise ValueError('Espera que acabi l’exploració')
        try:
            path = self.validate_root_path(root_id, plan['path'])
            for match in plan['matches'].values():
                file = path/match['relative_path']
                from .core import within
                if not within(file, path) or full_hash(file) != match['sha256']:
                    raise ValueError('La carpeta ha canviat després de comprovar-la')
                st = file.stat()
                match.update(size=st.st_size, mtime_ns=st.st_mtime_ns)
            self.backup()
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT path FROM roots WHERE id=?', (root_id,)).fetchone()
                if not row or row['path'] != plan['old_path']:
                    raise ValueError('La carpeta del catàleg ha canviat')
                # Free active locations before reassigning; unmapped entries stay archived with annotations.
                db.execute('UPDATE videos SET retired=1,available=0 WHERE root_id=?', (root_id,))
                for ident, match in plan['matches'].items():
                    row = db.execute('SELECT sha256 FROM videos WHERE id=? AND root_id=?', (ident, root_id)).fetchone()
                    if not row or row['sha256'] != match['sha256']:
                        raise ValueError('La identitat del catàleg ha canviat')
                    db.execute('''UPDATE videos SET relative_path=?,size=?,mtime_ns=?,fingerprint=?,
                        retired=0,available=1,identity_state='tracked' WHERE id=?''',
                               (match['relative_path'], match['size'], match['mtime_ns'], match['fingerprint'], ident))
                db.execute('UPDATE roots SET path=?,available=1 WHERE id=?', (str(path), root_id))
            self.root_plans.pop(token, None)
            return {'matched': len(plan['matches']), 'path': str(path)}
        finally:
            self.scan_lock.release()
