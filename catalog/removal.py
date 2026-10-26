"""Explicit exclusion and confirmed content-checked recycling."""
from pathlib import Path
import secrets
import time
from .identity import full_hash
from .recycle import recycle_file

class RemovalMixin:
    def init_removal(self):
        self.removal_plans = {}
        with self.db() as db:
            if db.execute('SELECT version FROM schema_version').fetchone()[0] < 4: return
            columns = {r[1] for r in db.execute('PRAGMA table_info(annotations)')}
        if 'excluded' not in columns:
            self.backup()
            with self.db() as db:
                db.execute('ALTER TABLE annotations ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0 CHECK(excluded IN (0,1))')

    def preview_removal(self, ident, action):
        if action not in ('exclude','restore','recycle'): raise ValueError('Acció desconeguda')
        v = self.video(ident)
        plan = {'id':ident,'action':action,'expires':time.monotonic()+300}
        if action == 'recycle':
            path = self.path_for(ident)
            original = Path(v['root_path'])/v['relative_path']
            if original.is_symlink() or path.suffix.lower() not in ('.mp4','.mov','.m4v','.mkv','.avi','.webm','.mts','.m2ts','.3gp'):
                raise ValueError('No es pot enviar aquest fitxer a la paperera')
            if not v['sha256'] or full_hash(path) != v['sha256']:
                raise ValueError('El contingut ha canviat. Actualitza la carpeta abans de continuar.')
            st = path.stat()
            plan.update(path=str(path),sha=v['sha256'],stat=(st.st_size,st.st_mtime_ns,st.st_ino))
        token = secrets.token_urlsafe(24)
        self.removal_plans = {k:v for k,v in self.removal_plans.items() if v['expires']>time.monotonic()}
        self.removal_plans[token]=plan
        return {'token':token,'action':action,'name':v['relative_path'],'path':str(Path(v['root_path'])/v['relative_path'])}

    def apply_removal(self, ident, token):
        plan=self.removal_plans.pop(token,None)
        if not plan or plan['id']!=ident or plan['expires']<time.monotonic():
            raise ValueError('La confirmació ha caducat. Torna-ho a provar.')
        if not self.scan_lock.acquire(blocking=False):
            raise ValueError('Espera que acabi l’exploració abans de continuar.')
        try:
            v=self.video(ident)
            if plan['action']=='recycle':
                path=self.path_for(ident);st=path.stat()
                if str(path)!=plan['path'] or (st.st_size,st.st_mtime_ns,st.st_ino)!=plan['stat'] or full_hash(path)!=plan['sha']:
                    raise ValueError('El fitxer ha canviat després de la confirmació. No s’ha tocat.')
            self.backup()
            excluded=0 if plan['action']=='restore' else 1
            with self.db() as db: db.execute('UPDATE annotations SET excluded=? WHERE video_id=?',(excluded,ident))
            if plan['action']=='recycle':
                try: recycle_file(path)
                except Exception:
                    if path.exists():
                        with self.db() as db: db.execute('UPDATE annotations SET excluded=? WHERE video_id=?',(v['individually_excluded'],ident))
                    raise
                with self.db() as db: db.execute('UPDATE videos SET available=0 WHERE id=?',(ident,))
            with self.db() as db:
                db.execute("INSERT INTO activity(created_at,action,label) VALUES(strftime('%Y-%m-%dT%H:%M:%fZ','now'),?,?)",({'exclude':'Vídeo exclòs','restore':'Vídeo reincorporat','recycle':'Vídeo enviat a la paperera'}[plan['action']],v['relative_path']))
            return {'ok':True,'action':plan['action']}
        finally: self.scan_lock.release()
