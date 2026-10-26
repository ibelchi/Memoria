"""Validated data-folder selection. Transfers copy data and keep the source intact."""
import json
from pathlib import Path
import secrets
import shutil
import sqlite3
import time
import uuid


def read_pointer(config_file, fallback):
    config_file = Path(config_file)
    if not config_file.exists():
        return Path(fallback).resolve()
    document = json.loads(config_file.read_text(encoding='utf8'))
    if document.get('version') != 1 or not isinstance(document.get('data_dir'), str):
        raise ValueError('La configuració d’ubicació no és vàlida')
    return Path(document['data_dir']).resolve()


def write_pointer(config_file, data_dir):
    if config_file is None:
        return
    path = Path(config_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps({'version': 1, 'data_dir': str(Path(data_dir).resolve())}, ensure_ascii=False, indent=2), encoding='utf8')
    temporary.replace(path)


def probe_catalog(directory):
    path = Path(directory)/'catalog.sqlite3'
    if not path.is_file():
        raise ValueError('Aquesta carpeta no conté cap catàleg')
    if path.is_symlink() or (getattr(path.lstat(), 'st_file_attributes', 0)&1024):
        raise ValueError('Selecciona el catàleg original, no un enllaç')
    try:
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('El catàleg no supera la comprovació d’integritat')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'schema_version', 'roots', 'videos', 'annotations', 'tags', 'video_tags', 'scans'}.issubset(tables):
                raise ValueError('La carpeta no conté un catàleg de vídeos vàlid')
            if db.execute('SELECT version FROM schema_version').fetchone()[0] not in (1, 2, 3, 4):
                raise ValueError('Versió de catàleg desconeguda')
            return db.execute('SELECT COUNT(*) FROM videos').fetchone()[0]
    except sqlite3.DatabaseError as error:
        raise ValueError('La carpeta no conté un catàleg SQLite vàlid') from error


class StorageController:
    def __init__(self, server, config_file=None):
        self.server = server
        self.config_file = Path(config_file) if config_file is not None else None
        self.plans = {}

    def validate_path(self, value):
        from .core import within
        if not isinstance(value, str) or not value.strip() or value.startswith(('\\\\', '//')):
            raise ValueError('Selecciona una carpeta en un disc local')
        target = Path(value).expanduser().resolve()
        c = self.server.catalog
        if target == target.parent or within(target, c.data_dir) or within(c.data_dir, target):
            raise ValueError('Selecciona una carpeta diferent, fora de la carpeta actual del catàleg')
        for root in c.roots():
            if root['id'] != 'demo' and (within(target, Path(root['path'])) or within(Path(root['path']), target)):
                raise ValueError('La carpeta del catàleg ha d’estar separada de les gravacions')
        return target

    def preview(self, value, mode):
        if mode not in ('move', 'open', 'create'):
            raise ValueError('Operació d’ubicació desconeguda')
        target = self.validate_path(value)
        c = self.server.catalog
        if mode == 'open':
            count = probe_catalog(target)
        else:
            if target.exists() and (not target.is_dir() or any(target.iterdir())):
                raise ValueError('Per traslladar o crear, selecciona una carpeta buida. No se sobreescriurà cap fitxer.')
            with c.db() as db:
                count = db.execute('SELECT COUNT(*) FROM videos').fetchone()[0] if mode == 'move' else 0
        token = secrets.token_urlsafe(24)
        self.plans = {k: p for k, p in self.plans.items() if p['expires'] > time.monotonic()}
        self.plans[token] = {'path': str(target), 'mode': mode, 'source': str(c.data_dir),
                             'catalog_id': c.catalog_id, 'expires': time.monotonic()+900}
        return {'token': token, 'path': str(target), 'mode': mode, 'videos': count}

    def apply(self, token):
        from .core import Catalog
        plan = self.plans.get(token)
        c = self.server.catalog
        if (not plan or plan['expires'] < time.monotonic() or plan['source'] != str(c.data_dir)
                or plan['catalog_id'] != c.catalog_id):
            raise ValueError('La comprovació ha caducat o el catàleg ha canviat')
        if not c.scan_lock.acquire(blocking=False):
            raise ValueError('Espera que acabi l’exploració o la recuperació de vídeos')
        try:
            target = self.validate_path(plan['path'])
            if plan['mode'] == 'open':
                probe_catalog(target)
                c.backup()
                next_catalog = Catalog(target)
            else:
                if target.exists() and (not target.is_dir() or any(target.iterdir())):
                    raise ValueError('La destinació ja no és buida. No s’ha modificat la configuració.')
                c.backup()
                target.mkdir(parents=True, exist_ok=True)
                if plan['mode'] == 'move':
                    with c.db() as source, sqlite3.connect(target/'catalog.sqlite3') as destination:
                        source.backup(destination)
                    for name in ('thumbnails', 'backups'):
                        folder = c.data_dir/name
                        if folder.exists():
                            if folder.is_symlink() or (getattr(folder.lstat(), 'st_file_attributes', 0)&1024) or any(p.is_symlink() or (getattr(p.lstat(), 'st_file_attributes', 0)&1024) for p in folder.rglob('*')):
                                raise ValueError('La carpeta de dades conté enllaços; no s’ha canviat la ubicació activa')
                            shutil.copytree(folder, target/name)
                    probe_catalog(target)
                next_catalog = Catalog(target)
                if plan['mode'] == 'move' and next_catalog.export()['tables'] != c.export()['tables']:
                    raise ValueError('La còpia no coincideix amb l’original; la ubicació activa no ha canviat')
            # Atomic pointer update is the last step before making the new catalog active.
            write_pointer(self.config_file, target)
            self.server.catalog = next_catalog
            self.server.token = secrets.token_urlsafe(32)
            try:
                import logging
                if any(isinstance(h, logging.FileHandler) and Path(h.baseFilename).name == 'app.log' for h in logging.getLogger().handlers):
                    logging.basicConfig(filename=target/'app.log', level=logging.INFO, encoding='utf8', force=True)
            except OSError:
                pass
            self.plans.clear()
            return {'ok': True, 'reload': True, 'data_dir': str(target), 'catalog_id': next_catalog.catalog_id}
        finally:
            c.scan_lock.release()
