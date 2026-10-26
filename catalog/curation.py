"""Catalog-only type/date corrections and persistent folder exclusion rules."""
import datetime as dt
from pathlib import PurePosixPath
import secrets
import time

class CurationMixin:
    def init_curation(self):
        with self.db() as db:
            if db.execute('SELECT version FROM schema_version').fetchone()[0] < 4: return
            columns={r[1] for r in db.execute('PRAGMA table_info(annotations)')}
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='folder_exclusions'").fetchone()
        if 'video_type' not in columns or not exists: self.backup()
        with self.db() as db:
            if 'video_type' not in columns:
                db.execute("ALTER TABLE annotations ADD COLUMN video_type TEXT NOT NULL DEFAULT 'original' CHECK(video_type IN ('original','montage'))")
                db.execute('ALTER TABLE annotations ADD COLUMN date_override TEXT')
            db.execute("CREATE TABLE IF NOT EXISTS folder_exclusions(root_id TEXT NOT NULL REFERENCES roots(id),folder TEXT NOT NULL,PRIMARY KEY(root_id,folder))")

    def effective_video(self,v,rules):
        v['detected_at']=v['recorded_at']
        v['detected_source']=v['date_source']
        if v['date_override']:
            v['recorded_at']=v['date_override']; v['date_source']='manual'
        path=v['relative_path'].replace('\\','/')
        v['folder_excluded']=any(r['root_id']==v['root_id'] and (not r['folder'] or path.startswith(r['folder']+'/')) for r in rules)
        v['individually_excluded']=bool(v['excluded'])
        v['excluded']=bool(v['excluded'] or v['folder_excluded'])
        return v

    def folder_rules(self):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT e.*,r.label FROM folder_exclusions e JOIN roots r ON r.id=e.root_id ORDER BY r.label,e.folder')]

    @staticmethod
    def validate_date(value):
        if value is None: return None
        if not isinstance(value,str) or not 10<=len(value)<=32: raise ValueError('Data i hora incorrectes')
        try:
            result=dt.datetime.fromisoformat(value)
            if result.tzinfo is not None: raise ValueError()
            return result.isoformat(timespec='seconds')
        except ValueError: raise ValueError('Introdueix una data i hora locals vàlides')

    def preview_folder_rule(self,root_id,folder,remove=False):
        if type(remove) is not bool or not isinstance(folder,str): raise ValueError('Carpeta incorrecta')
        folder=folder.replace('\\','/').strip('/')
        if ':' in folder or any(p in ('.','..') for p in folder.split('/') if p): raise ValueError('Carpeta incorrecta')
        folder='/'.join(PurePosixPath(folder).parts) if folder else ''
        with self.db() as db:
            root=db.execute('SELECT label FROM roots WHERE id=?',(root_id,)).fetchone()
            if not root: raise ValueError('Carpeta desconeguda')
            rows=db.execute('SELECT relative_path FROM videos WHERE root_id=? AND retired=0',(root_id,)).fetchall()
        count=sum(not folder or r[0].replace('\\','/').startswith(folder+'/') for r in rows)
        token=secrets.token_urlsafe(24)
        self.removal_plans[token]={'kind':'folder','root_id':root_id,'folder':folder,'remove':remove,'expires':time.monotonic()+300}
        return {'token':token,'count':count,'label':root['label']+('/'+folder if folder else ''),'remove':remove}

    def apply_folder_rule(self,token):
        p=self.removal_plans.pop(token,None)
        if not p or p.get('kind')!='folder' or p['expires']<time.monotonic(): raise ValueError('Confirmació caducada')
        self.backup()
        with self.db() as db:
            if p['remove']: db.execute('DELETE FROM folder_exclusions WHERE root_id=? AND folder=?',(p['root_id'],p['folder']))
            else: db.execute('INSERT OR IGNORE INTO folder_exclusions VALUES(?,?)',(p['root_id'],p['folder']))
            db.execute("INSERT INTO activity(created_at,action,label) VALUES(strftime('%Y-%m-%dT%H:%M:%fZ','now'),?,?)",('Regla de carpeta retirada' if p['remove'] else 'Carpeta exclosa',p['folder'] or 'Tota la carpeta'))
        return {'ok':True}

    def shift_dates(self,ids,minutes):
        if not isinstance(ids,list) or not 1<=len(ids)<=500 or not all(isinstance(x,str) for x in ids) or type(minutes) is not int or not -52560000<=minutes<=52560000: raise ValueError('Selecció o desplaçament incorrectes')
        values=[]
        for ident in set(ids):
            v=self.video(ident)
            if not v['recorded_at']: raise ValueError('Hi ha vídeos sense data; corregeix-los individualment')
            parsed=dt.datetime.fromisoformat(v['recorded_at'].replace('Z','+00:00')).replace(tzinfo=None)
            try: value=parsed+dt.timedelta(minutes=minutes)
            except OverflowError: raise ValueError('El desplaçament excedeix les dates vàlides')
            values.append((value.isoformat(timespec='seconds'),ident))
        self.backup()
        with self.db() as db:
            db.executemany('UPDATE annotations SET date_override=? WHERE video_id=?',values)
            db.execute("INSERT INTO activity(created_at,action,label) VALUES(strftime('%Y-%m-%dT%H:%M:%fZ','now'),'Dates corregides',?)",(str(len(values))+' vídeos · '+str(minutes)+' minuts',))
        return {'ok':True,'count':len(values)}
