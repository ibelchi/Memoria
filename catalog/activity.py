"""Folder-first activity, with expandable scan results."""
import json

class ActivityMixin:
    def init_activity(self):
        with self.db() as db:
            if db.execute('SELECT version FROM schema_version').fetchone()[0] < 4:
                return
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='activity'").fetchone()
        with self.db() as db:
            columns={r[1] for r in db.execute('PRAGMA table_info(activity)')}
        if not exists or 'scan_id' not in columns:
            self.backup()
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,action TEXT NOT NULL,label TEXT NOT NULL)")
            columns={r[1] for r in db.execute('PRAGMA table_info(activity)')}
            for name,kind in (('root_id','TEXT'),('scan_id','TEXT'),('items_json',"TEXT NOT NULL DEFAULT '[]'")):
                if name not in columns: db.execute('ALTER TABLE activity ADD COLUMN '+name+' '+kind)
            db.execute('DROP TRIGGER IF EXISTS activity_video_added')
            db.execute('DROP TRIGGER IF EXISTS activity_root_added')
            db.execute("CREATE TRIGGER activity_root_added AFTER INSERT ON roots BEGIN INSERT INTO activity(created_at,action,label,root_id) VALUES(strftime('%Y-%m-%dT%H:%M:%fZ','now'),'Carpeta incorporada',NEW.label,NEW.id); END")
            specs = [
                ('collection_added', 'AFTER INSERT ON collections', None, "Col·lecció creada", 'NEW.name'),
                ('collection_renamed', 'AFTER UPDATE OF name ON collections', 'OLD.name != NEW.name', "Col·lecció reanomenada", 'NEW.name'),
                ('description_changed', 'AFTER UPDATE OF description ON annotations', 'OLD.description != NEW.description', "Descripció modificada", '(SELECT relative_path FROM videos WHERE id=NEW.video_id)'),
                ('tag_added', 'AFTER INSERT ON video_tags', None, "Etiqueta afegida", "(SELECT relative_path FROM videos WHERE id=NEW.video_id) || ' · ' || (SELECT name FROM tags WHERE id=NEW.tag_id)"),
                ('tag_removed', 'AFTER DELETE ON video_tags', None, "Etiqueta retirada", "(SELECT relative_path FROM videos WHERE id=OLD.video_id) || ' · ' || (SELECT name FROM tags WHERE id=OLD.tag_id)"),
                ('collection_member', 'AFTER INSERT ON collection_videos', None, "Vídeo afegit a col·lecció", "(SELECT name FROM collections WHERE id=NEW.collection_id) || ' · ' || (SELECT relative_path FROM videos WHERE id=NEW.video_id)"),
                ('favorite_changed', 'AFTER UPDATE OF favorite ON annotations', 'OLD.favorite != NEW.favorite', "Favorit modificat", '(SELECT relative_path FROM videos WHERE id=NEW.video_id)'),
            ]
            for name, event, condition, action, label in specs:
                action = action.replace("'", "''")
                when = ' WHEN '+condition if condition else ''
                db.execute("CREATE TRIGGER IF NOT EXISTS activity_"+name+' '+event+when+" BEGIN INSERT INTO activity(created_at,action,label) VALUES(strftime('%Y-%m-%dT%H:%M:%fZ','now'),'"+action+"',COALESCE("+label+",'')); END")

    def begin_scan_activity(self, scan_id, root_id):
        with self.db() as db:
            root=db.execute('SELECT label,scanned_at FROM roots WHERE id=?',(root_id,)).fetchone()
            previous=db.execute('SELECT id FROM activity WHERE root_id=? AND scan_id IS NULL AND action=? ORDER BY id DESC LIMIT 1',(root_id,'Carpeta incorporada')).fetchone()
            if not root['scanned_at'] and previous:
                db.execute('UPDATE activity SET scan_id=? WHERE id=?',(scan_id,previous['id']))
            else:
                db.execute("INSERT INTO activity(created_at,action,label,root_id,scan_id) VALUES(strftime('%Y-%m-%dT%H:%M:%fZ','now'),'Carpeta actualitzada',?,?,?)",(root['label'],root_id,scan_id))

    def finish_scan_activity(self,scan_id,root_id,before):
        with self.db() as db:
            rows=db.execute('SELECT id,relative_path,size,mtime_ns,sha256 FROM videos WHERE root_id=? AND retired=0 ORDER BY relative_path',(root_id,)).fetchall()
            items=[]
            by_path={value[0]:value for value in before.values()}
            for row in rows:
                old=before.get(row['id']) or by_path.get(row['relative_path'])
                if old is None or tuple(row)[1:]!=old:
                    items.append({'id':row['id'],'name':row['relative_path'],'change':'Afegit' if old is None else 'Actualitzat'})
            db.execute('UPDATE activity SET items_json=? WHERE scan_id=?',(json.dumps(items,ensure_ascii=False),scan_id))

    def recent_activity(self):
        with self.db() as db:
            rows=db.execute("SELECT a.*,s.status,s.errors,s.message,r.path root_path FROM activity a LEFT JOIN scans s ON s.id=a.scan_id LEFT JOIN roots r ON r.id=COALESCE(a.root_id,s.root_id) WHERE a.action != ? ORDER BY a.id DESC LIMIT 100",('Vídeo incorporat',)).fetchall()
        roots=self.roots()
        result=[]
        for row in rows:
            item=dict(row)
            if not item['root_path'] and item['action'] in ('Carpeta incorporada','Carpeta actualitzada'):
                matches=[r for r in roots if r['label']==item['label']]
                if len(matches)==1: item['root_path']=matches[0]['path']
            item['items']=json.loads(item.pop('items_json') or '[]');result.append(item)
        return result
