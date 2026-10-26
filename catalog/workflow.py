"""Owners and explicit annotation decisions; legacy review history is retained."""
import uuid

OWNERS = {'belchi': 'Belchi', 'nuria': 'Núria', 'altres': 'Altres'}


def catalog_status(description, tags, omitted):
    if description.strip() and tags:
        return 'complete'
    if omitted and not description.strip() and not tags:
        return 'empty_by_choice'
    return 'pending'


class WorkflowMixin:
    def migrate_workflow(self):
        with self.db() as db:
            version = db.execute('SELECT version FROM schema_version').fetchone()[0]
        if version == 4:
            with self.db() as db:
                db.executemany('INSERT OR IGNORE INTO owners VALUES(?,?)', OWNERS.items())
                columns = {r[1] for r in db.execute('PRAGMA table_info(annotations)')}
            if 'favorite' not in columns:
                self.backup()
                with self.db() as db:
                    db.execute('ALTER TABLE annotations ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0 CHECK(favorite IN (0,1))')
            return
        if version != 3:
            raise ValueError('Versió de catàleg desconeguda')
        self.backup()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE owners(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE)')
            db.executemany('INSERT INTO owners VALUES(?,?)', OWNERS.items())
            db.execute('ALTER TABLE roots ADD COLUMN owner_id TEXT REFERENCES owners(id)')
            db.execute('ALTER TABLE videos ADD COLUMN owner_id TEXT REFERENCES owners(id)')
            db.execute('ALTER TABLE annotations ADD COLUMN omit_annotations INTEGER NOT NULL DEFAULT 0')
            db.execute("UPDATE roots SET owner_id='belchi' WHERE id='demo'")
            db.execute("UPDATE videos SET owner_id='belchi' WHERE demo=1")
            db.execute('CREATE TABLE app_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute('INSERT INTO app_meta VALUES(?,?)', ('catalog_id', str(uuid.uuid4())))
            db.execute('ALTER TABLE annotations ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0 CHECK(favorite IN (0,1))')
            db.execute('UPDATE schema_version SET version=4')

    @property
    def catalog_id(self):
        with self.db() as db:
            return db.execute("SELECT value FROM app_meta WHERE key='catalog_id'").fetchone()[0]

    def validate_owner(self, owner):
        if not isinstance(owner, str) or owner not in OWNERS:
            raise ValueError('Cal escollir el propietari: Belchi, Núria o Altres')
        return owner

    def set_root_owner(self, root_id, owner, apply_existing=False):
        owner = self.validate_owner(owner)
        if type(apply_existing) is not bool:
            raise ValueError('Operació de propietari incorrecta')
        if not self.scan_lock.acquire(blocking=False):
            raise ValueError('Espera que acabi l’exploració')
        try:
            self.backup()
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if not db.execute('SELECT 1 FROM roots WHERE id=?', (root_id,)).fetchone():
                    raise ValueError('Carpeta desconeguda')
                db.execute('UPDATE roots SET owner_id=? WHERE id=?', (owner, root_id))
                if apply_existing:
                    db.execute('UPDATE videos SET owner_id=? WHERE root_id=?', (owner, root_id))
                else:
                    db.execute('UPDATE videos SET owner_id=? WHERE root_id=? AND owner_id IS NULL', (owner, root_id))
        finally:
            self.scan_lock.release()
        return {'ok': True}

    def annotation_decision(self, ids, omit):
        from .core import now
        if type(omit) is not bool or not isinstance(ids, list) or not 1 <= len(ids) <= 500 or not all(isinstance(v, str) for v in ids):
            raise ValueError('Selecció o decisió incorrecta')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for ident in ids:
                row = db.execute('SELECT description FROM annotations WHERE video_id=?', (ident,)).fetchone()
                if not row:
                    raise ValueError('Vídeo desconegut')
                if omit and (row['description'].strip() or db.execute('SELECT 1 FROM video_tags WHERE video_id=?', (ident,)).fetchone()):
                    raise ValueError('L’excepció és per a vídeos sense descripció ni etiquetes. No s’ha esborrat res.')
            db.executemany('UPDATE annotations SET omit_annotations=?,updated_at=? WHERE video_id=?', [(omit, now(), ident) for ident in ids])
        return {'ok': True}
