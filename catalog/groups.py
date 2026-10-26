"""Named video selections. Membership never changes a media file."""
import uuid


class CollectionsMixin:
    def migrate_collections(self):
        with self.db() as db:
            version = db.execute('SELECT version FROM schema_version').fetchone()[0]
        if version in (3, 4):
            return
        if version != 2:
            raise ValueError('Versió de catàleg desconeguda')
        self.backup()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE collections(id TEXT PRIMARY KEY,name TEXT NOT NULL,
                name_key TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL)''')
            db.execute('''CREATE TABLE collection_videos(collection_id TEXT REFERENCES collections(id),
                video_id TEXT REFERENCES videos(id),PRIMARY KEY(collection_id,video_id))''')
            db.execute('CREATE INDEX collection_video_membership ON collection_videos(video_id)')
            db.execute('UPDATE schema_version SET version=3')

    def collections(self):
        with self.db() as db:
            return [dict(r) for r in db.execute('''SELECT c.id,c.name,c.created_at,COUNT(cv.video_id) video_count
                FROM collections c LEFT JOIN collection_videos cv ON cv.collection_id=c.id
                GROUP BY c.id ORDER BY c.name_key''')]

    def collection_name(self, value):
        from .core import normalize
        if not isinstance(value, str) or not value.strip() or len(value) > 100:
            raise ValueError('El nom de la col·lecció ha de tenir entre 1 i 100 caràcters')
        name = ' '.join(value.split())
        return name, normalize(name)

    def create_collection(self, value):
        from .core import now
        name, key = self.collection_name(value)
        ident = str(uuid.uuid4())
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM collections WHERE name_key=?', (key,)).fetchone():
                raise ValueError('Ja hi ha una col·lecció amb aquest nom')
            db.execute('INSERT INTO collections VALUES(?,?,?,?)', (ident, name, key, now()))
        return {'id': ident, 'name': name}

    def rename_collection(self, ident, value):
        name, key = self.collection_name(value)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM collections WHERE id=?', (ident,)).fetchone():
                raise ValueError('Col·lecció desconeguda')
            if db.execute('SELECT 1 FROM collections WHERE name_key=? AND id<>?', (key, ident)).fetchone():
                raise ValueError('Ja hi ha una col·lecció amb aquest nom')
            db.execute('UPDATE collections SET name=?,name_key=? WHERE id=?', (name, key, ident))
        return {'id': ident, 'name': name}

    def collection_members(self, ident, ids, remove=False):
        if not isinstance(ids, list) or not 1 <= len(ids) <= 500 or not all(isinstance(v, str) for v in ids):
            raise ValueError('Selecciona entre 1 i 500 vídeos')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM collections WHERE id=?', (ident,)).fetchone():
                raise ValueError('Col·lecció desconeguda')
            for video_id in ids:
                if not db.execute('SELECT 1 FROM videos WHERE id=?', (video_id,)).fetchone():
                    raise ValueError('Vídeo desconegut')
                if remove:
                    db.execute('DELETE FROM collection_videos WHERE collection_id=? AND video_id=?', (ident, video_id))
                else:
                    db.execute('INSERT OR IGNORE INTO collection_videos VALUES(?,?)', (ident, video_id))
        return {'ok': True}

    def delete_collection(self, ident):
        self.backup()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM collections WHERE id=?', (ident,)).fetchone():
                raise ValueError('Col·lecció desconeguda')
            db.execute('DELETE FROM collection_videos WHERE collection_id=?', (ident,))
            db.execute('DELETE FROM collections WHERE id=?', (ident,))
        return {'ok': True}
