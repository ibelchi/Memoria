import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from catalog.core import Catalog
from catalog.server import LocalServer
from catalog.storage import read_pointer, write_pointer


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.c = Catalog(self.base/'data')
        self.root = self.base/'videos'
        self.root.mkdir()
        self.rid = self.c.add_root(str(self.root), 'belchi')
        self.file = self.root/'clip.mp4'
        self.file.write_bytes(b'identity-fixture')
        self.ident, _ = self.c.identify(self.rid, self.file, self.file.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_other_owner_is_added_to_existing_catalog_and_survives_reopen_and_export(self):
        with self.c.db() as db:
            db.execute("DELETE FROM owners WHERE id='altres'")
        self.c=Catalog(self.base/'data')
        self.c.set_root_owner(self.rid,'altres',True)
        self.assertEqual(self.c.video(self.ident)['owner_id'],'altres')
        self.assertEqual(self.c.videos({'owner':'altres'})['total'],1)
        self.assertEqual(self.c.videos({'owner':'belchi'})['total'],0)
        new=self.root/'new.mp4';new.write_bytes(b'new-fixture')
        ident,_=self.c.identify(self.rid,new,new.name)
        self.assertEqual(self.c.video(ident)['owner_id'],'altres')
        restored=Catalog(self.base/'restored-other')
        restored.import_empty(self.c.export())
        self.assertEqual(restored.videos({'owner':'altres'})['total'],2)
        self.assertEqual(Catalog(self.base/'data').video(ident)['owner_name'],'Altres')

    def test_folder_rules_cover_future_subfolders_and_preserve_individual_exclusions(self):
        sub=self.root/'child';sub.mkdir()
        p=sub/'one.mp4';p.write_bytes(b'one')
        ident,_=self.c.identify(self.rid,p,'child/one.mp4')
        plan=self.c.preview_folder_rule(self.rid,'child')
        self.assertEqual(plan['count'],1)
        self.c.apply_folder_rule(plan['token'])
        self.assertEqual(self.c.videos({})['total'],1)
        p2=sub/'two.mp4';p2.write_bytes(b'two')
        second,_=self.c.identify(self.rid,p2,'child/two.mp4')
        self.assertTrue(self.c.video(second)['folder_excluded'])
        self.assertEqual(self.c.videos({'excluded':'1'})['total'],2)
        plan=self.c.preview_removal(ident,'exclude');self.c.apply_removal(ident,plan['token'])
        restored=Catalog(self.base/'folder-rules-restore');restored.import_empty(self.c.export())
        self.assertTrue(restored.video(second)['folder_excluded'])
        plan=self.c.preview_folder_rule(self.rid,'child',True);self.c.apply_folder_rule(plan['token'])
        self.assertFalse(self.c.video(second)['excluded'])
        self.assertTrue(self.c.video(ident)['excluded'])
        for value in ('../outside','child/../outside','C:/outside'):
            with self.assertRaises(ValueError):self.c.preview_folder_rule(self.rid,value)

    def test_manual_date_type_persist_and_drive_filters_without_changing_detected_date(self):
        with self.c.db() as db:db.execute("UPDATE videos SET recorded_at='2020-01-01T10:00:00',date_source='metadata' WHERE id=?",(self.ident,))
        self.c.patch(self.ident,{'date_override':'2021-02-03T12:34','video_type':'montage'})
        v=self.c.video(self.ident)
        self.assertEqual(v['recorded_at'],'2021-02-03T12:34:00')
        self.assertEqual(v['detected_at'],'2020-01-01T10:00:00')
        self.assertEqual(v['date_source'],'manual')
        self.assertEqual(self.c.videos({'start':'2021-02-03','video_type':'montage'})['total'],1)
        self.assertEqual(self.c.videos({'video_type':'original'})['total'],0)
        restored=Catalog(self.base/'curation-restore');restored.import_empty(self.c.export())
        self.assertEqual(restored.video(self.ident)['date_override'],v['date_override'])
        self.c.patch(self.ident,{'date_override':None})
        self.assertEqual(self.c.video(self.ident)['recorded_at'],v['detected_at'])
        for data in ({'video_type':'invalid'},{'date_override':'2026-99-01'},{'date_override':'2026-01-01T12:00Z'}):
            with self.assertRaises(ValueError):self.c.patch(self.ident,data)

    def test_date_shift_is_atomic_and_keeps_detected_values(self):
        with self.c.db() as db:db.execute("UPDATE videos SET recorded_at='2020-01-01T10:00:00' WHERE id=?",(self.ident,))
        self.c.shift_dates([self.ident],-120)
        self.assertEqual(self.c.video(self.ident)['recorded_at'],'2020-01-01T08:00:00')
        self.assertEqual(self.c.video(self.ident)['detected_at'],'2020-01-01T10:00:00')
        with self.assertRaises(KeyError):self.c.shift_dates([self.ident,'unknown'],120)
        self.assertEqual(self.c.video(self.ident)['recorded_at'],'2020-01-01T08:00:00')

    def test_exclusion_is_persistent_reversible_and_exported(self):
        self.c.patch(self.ident, {'description': 'Preservar'})
        plan=self.c.preview_removal(self.ident, 'exclude')
        self.assertEqual(self.c.videos({})['total'], 1)
        self.c.apply_removal(self.ident,plan['token'])
        self.assertTrue(self.file.exists())
        self.assertEqual(Catalog(self.c.data_dir).videos({})['total'], 0)
        self.assertEqual(self.c.videos({'excluded':'1'})['total'], 1)
        ident,_=self.c.identify(self.rid,self.file,self.file.name)
        self.assertEqual(ident,self.ident)
        self.assertEqual(self.c.videos({})['total'],0)
        restored=Catalog(self.base/'excluded-restore')
        restored.import_empty(self.c.export())
        self.assertTrue(restored.video(self.ident)['excluded'])
        plan=self.c.preview_removal(self.ident,'restore')
        self.c.apply_removal(self.ident,plan['token'])
        self.assertEqual(self.c.videos({})['total'],1)
        self.assertEqual(self.c.video(self.ident)['description'],'Preservar')

    def test_recycle_confirmation_and_failure(self):
        with patch('catalog.removal.recycle_file',side_effect=OSError('failure')) as recycle:
            with self.assertRaises(ValueError):self.c.apply_removal(self.ident,'invalid')
            recycle.assert_not_called()
            plan=self.c.preview_removal(self.ident,'recycle')
            with self.assertRaises(OSError):self.c.apply_removal(self.ident,plan['token'])
            self.assertTrue(self.file.exists())
            self.assertFalse(self.c.video(self.ident)['excluded'])
            with self.assertRaises(ValueError):self.c.apply_removal(self.ident,plan['token'])
        plan=self.c.preview_removal(self.ident,'recycle')
        self.file.write_bytes(b'replaced-content')
        with patch('catalog.removal.recycle_file') as recycle:
            with self.assertRaises(ValueError):self.c.apply_removal(self.ident,plan['token'])
            recycle.assert_not_called()

    def test_recycle_success_and_busy_refusal(self):
        plan=self.c.preview_removal(self.ident,'recycle')
        self.c.scan_lock.acquire()
        try:
            with self.assertRaises(ValueError):self.c.apply_removal(self.ident,plan['token'])
        finally:self.c.scan_lock.release()
        plan=self.c.preview_removal(self.ident,'recycle')
        with patch('catalog.removal.recycle_file') as recycle:
            self.c.apply_removal(self.ident,plan['token'])
            recycle.assert_called_once_with(self.file)
        self.assertTrue(self.c.video(self.ident)['excluded'])
        self.assertFalse(self.c.video(self.ident)['available'])

    def test_directory_browser_lists_folders_without_importing(self):
        child = self.root/'subcarpeta'
        child.mkdir()
        before = self.c.export()['tables']
        result = self.c.browse_directories(str(self.root))
        self.assertEqual(result['path'], str(self.root.resolve()))
        self.assertEqual(result['folders'], [{'name': 'subcarpeta', 'path': str(child)}])
        self.assertEqual(self.c.browse_directories(str(child))['parent'], str(self.root))
        self.assertEqual(self.c.browse_directories(str(child))['folders'], [])
        with self.assertRaises(ValueError):
            self.c.browse_directories(str(self.file))
        with self.assertRaises(ValueError):
            self.c.browse_directories('//server/share')
        self.assertEqual(before, self.c.export()['tables'])

    def test_scan_activity_groups_added_and_updated_videos_by_folder(self):
        import uuid
        folder=self.base/'activity-folder';folder.mkdir()
        rid=self.c.add_root(str(folder),'nuria')
        (folder/'one.mp4').write_bytes(b'one')
        (folder/'two.mp4').write_bytes(b'two')
        def scan():
            sid=str(uuid.uuid4())
            with self.c.db() as db:db.execute("INSERT INTO scans(id,root_id,status,started_at) VALUES(?,?,'running','2026-01-01')",(sid,rid))
            self.c.begin_scan_activity(sid,rid)
            self.c.scan_lock.acquire()
            with patch.object(self.c,'index_file',side_effect=lambda r,p,n:self.c.identify(r,p,n)):
                self.c._scan(sid,rid)
            return next(e for e in self.c.recent_activity() if e['scan_id']==sid)
        first=scan()
        self.assertEqual(first['action'],'Carpeta incorporada')
        self.assertEqual(len(first['items']),2)
        self.assertEqual(first['status'],'done')
        self.assertEqual(first['root_path'],str(folder.resolve()))
        (folder/'three.mp4').write_bytes(b'three')
        (folder/'two.mp4').write_bytes(b'changed-two')
        second=scan()
        self.assertEqual(second['action'],'Carpeta actualitzada')
        self.assertEqual({x['name']:x['change'] for x in second['items']},{'three.mp4':'Afegit','two.mp4':'Actualitzat'})
        third=scan()
        self.assertEqual(third['items'],[])
        grouped=[e for e in self.c.recent_activity() if e['root_id']==rid]
        self.assertEqual(len(grouped),3)
        self.assertFalse(any(e['action']=='Vídeo incorporat' for e in self.c.recent_activity()))
        self.assertEqual(Catalog(self.c.data_dir).recent_activity(),self.c.recent_activity())

    def test_activity_logs_real_changes_without_backfill(self):
        events = self.c.recent_activity()
        self.assertEqual(len(events), 1)
        self.c.patch(self.ident, {'description': 'Una descripció'})
        self.c.patch(self.ident, {'description': 'Una descripció'})
        self.assertEqual(len(self.c.recent_activity()), 2)
        self.c.apply_tags([self.ident], ['prova'])
        group = self.c.create_collection('Muntatge')
        self.c.collection_members(group['id'], [self.ident])
        self.assertEqual(len(self.c.recent_activity()), 5)
        self.assertEqual(Catalog(self.c.data_dir).recent_activity(), self.c.recent_activity())
        restored = Catalog(self.base/'activity-restored')
        restored.import_empty(self.c.export())
        self.assertEqual(restored.recent_activity(), [])

    def test_favorite_persists_filters_and_exports(self):
        self.assertFalse(self.c.video(self.ident)['favorite'])
        self.c.patch(self.ident, {'favorite': True})
        self.assertEqual(Catalog(self.c.data_dir).videos({'favorite': '1'})['total'], 1)
        restored = Catalog(self.base/'favorite-restored')
        restored.import_empty(self.c.export())
        self.assertTrue(restored.video(self.ident)['favorite'])
        self.c.patch(self.ident, {'favorite': False})
        self.assertEqual(self.c.videos({'favorite': '1'})['total'], 0)
        with self.assertRaises(ValueError):
            self.c.patch(self.ident, {'favorite': 'yes'})

    def test_progressive_status_and_conscious_exception_never_erase(self):
        self.c.patch(self.ident, {'reviewed': True})
        self.assertEqual(self.c.video(self.ident)['catalog_status'], 'pending')
        self.c.annotation_decision([self.ident], True)
        self.assertEqual(self.c.video(self.ident)['catalog_status'], 'empty_by_choice')
        self.assertEqual(self.c.videos({'state': 'pending'})['total'], 0)
        self.c.patch(self.ident, {'description': 'Una escena'})
        self.assertFalse(self.c.video(self.ident)['omit_annotations'])
        self.assertEqual(self.c.video(self.ident)['catalog_status'], 'pending')
        with self.assertRaises(ValueError):
            self.c.annotation_decision([self.ident], True)
        self.assertEqual(self.c.video(self.ident)['description'], 'Una escena')
        self.c.apply_tags([self.ident], ['família'])
        self.assertEqual(self.c.video(self.ident)['catalog_status'], 'complete')
        self.assertEqual(self.c.videos({'state': 'complete'})['total'], 1)
        self.c.apply_tags([self.ident], ['família'], remove=True)
        self.assertEqual(self.c.video(self.ident)['catalog_status'], 'pending')

    def test_tag_add_clears_exception_and_bulk_decision_is_atomic(self):
        second = self.root/'second.mp4'
        second.write_bytes(b'second-identity')
        other, _ = self.c.identify(self.rid, second, second.name)
        self.c.patch(other, {'description': 'Preservar'})
        with self.assertRaises(ValueError):
            self.c.annotation_decision([self.ident, other], True)
        self.assertFalse(self.c.video(self.ident)['omit_annotations'])
        self.c.annotation_decision([self.ident], True)
        self.c.apply_tags([self.ident], ['nova'])
        self.assertFalse(self.c.video(self.ident)['omit_annotations'])
        self.assertEqual(self.c.video(self.ident)['catalog_status'], 'pending')

    def test_owner_required_and_existing_ownership_does_not_change_silently(self):
        other = self.base/'other'
        other.mkdir()
        for owner in (None, '', 'unknown'):
            with self.assertRaises(ValueError):
                self.c.add_root(str(other), owner)
        with self.assertRaises(ValueError):
            self.c.add_root(str(self.root), 'nuria')
        self.c.set_root_owner(self.rid, 'nuria', False)
        self.assertEqual(self.c.video(self.ident)['owner_id'], 'belchi')
        new = self.root/'new.mp4'
        new.write_bytes(b'new-content')
        ident, _ = self.c.identify(self.rid, new, new.name)
        self.assertEqual(self.c.video(ident)['owner_id'], 'nuria')
        self.assertEqual(self.c.videos({'owner': 'belchi'})['total'], 1)
        self.assertEqual(self.c.videos({'owner': 'nuria'})['total'], 1)
        self.c.set_root_owner(self.rid, 'nuria', True)
        self.assertEqual(self.c.videos({'owner': 'nuria'})['total'], 2)

    def test_move_recovery_retains_owner_exception_and_collection(self):
        self.c.annotation_decision([self.ident], True)
        group = self.c.create_collection('Muntatge')
        self.c.collection_members(group['id'], [self.ident])
        other = self.base/'other'
        other.mkdir()
        rid = self.c.add_root(str(other), 'nuria')
        destination = other/'moved.mp4'
        self.file.rename(destination)
        target, _ = self.c.identify(rid, destination, destination.name)
        self.c.apply_recovery([{'source_id': self.ident, 'target_id': target}])
        result = self.c.video(self.ident)
        self.assertEqual(result['owner_id'], 'belchi')
        self.assertEqual(result['catalog_status'], 'empty_by_choice')
        self.assertEqual(result['collections'][0]['id'], group['id'])

    def test_export4_restore_and_legacy3_migration_keep_history_without_inventing_exceptions(self):
        self.c.annotation_decision([self.ident], True)
        document = self.c.export()
        restored = Catalog(self.base/'restored')
        restored.import_empty(document)
        self.assertEqual(restored.export()['tables'], document['tables'])
        self.assertEqual(restored.catalog_id, self.c.catalog_id)
        legacy_dir = self.base/'legacy'
        with patch.object(Catalog, 'migrate_workflow', lambda self: None):
            old = Catalog(legacy_dir)
            old.seed_demo()
            with old.db() as db:
                ident = db.execute("SELECT video_id FROM annotations WHERE description='' LIMIT 1").fetchone()[0]
                db.execute('UPDATE annotations SET reviewed=1 WHERE video_id=?', (ident,))
        migrated = Catalog(legacy_dir)
        self.assertTrue(migrated.video(ident)['reviewed'])
        self.assertFalse(migrated.video(ident)['omit_annotations'])
        self.assertEqual(migrated.video(ident)['catalog_status'], 'pending')


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.c = Catalog(self.base/'data')
        self.c.seed_demo()
        self.ident = self.c.videos({'state': 'pending'})['items'][-1]['id']
        # Use an actually empty video for the explicit exception.
        self.ident = next(v['id'] for v in self.c.videos({})['items'] if not v['description'] and not v['tags'])
        self.c.annotation_decision([self.ident], True)
        group = self.c.create_collection('Preservar')
        self.c.collection_members(group['id'], [self.ident])
        (self.c.cache/'fixture.jpg').write_bytes(b'thumbnail-fixture')
        self.config = self.base/'settings.json'
        write_pointer(self.config, self.c.data_dir)
        self.server = LocalServer(self.c, 0, config_file=self.config)

    def tearDown(self):
        self.server.server_close()
        self.temp.cleanup()

    def test_transfer_preserves_data_assets_identity_and_source(self):
        before = self.c.export()['tables']
        old_token = self.server.token
        target = self.base/'new-data'
        plan = self.server.storage.preview(str(target), 'move')
        self.assertFalse(target.exists())
        self.server.storage.apply(plan['token'])
        self.assertEqual(self.server.catalog.export()['tables'], before)
        self.assertEqual(self.server.catalog.catalog_id, self.c.catalog_id)
        self.assertNotEqual(self.server.token, old_token)
        self.assertEqual(read_pointer(self.config, 'unused'), target.resolve())
        self.assertEqual((target/'thumbnails'/'fixture.jpg').read_bytes(), b'thumbnail-fixture')
        self.assertEqual(self.c.export()['tables'], before)
        self.assertTrue(self.c.db_path.exists())
        self.assertTrue(list((target/'backups').glob('*.sqlite3')))
        with self.assertRaises(ValueError):
            self.server.storage.apply(plan['token'])

    def test_open_existing_and_create_empty_are_distinct(self):
        other = Catalog(self.base/'other')
        other.seed_demo()
        other.patch(other.videos({})['items'][0]['id'], {'description': 'Another catalog'})
        plan = self.server.storage.preview(str(other.data_dir), 'open')
        self.server.storage.apply(plan['token'])
        self.assertEqual(self.server.catalog.videos({'q': 'another'})['total'], 1)
        target = self.base/'empty'
        plan = self.server.storage.preview(str(target), 'create')
        self.assertEqual(plan['videos'], 0)
        self.server.storage.apply(plan['token'])
        self.assertEqual(self.server.catalog.videos({})['total'], 0)
        self.assertNotEqual(self.server.catalog.catalog_id, other.catalog_id)
        self.assertEqual(self.c.videos({})['total'], 10)

    def test_nonempty_overlap_network_stale_and_busy_are_rejected(self):
        occupied = self.base/'occupied'
        occupied.mkdir()
        (occupied/'keep.txt').write_text('keep')
        for path in (str(occupied), str(self.c.cache), str(self.base), r'\\server\share\catalog'):
            with self.assertRaises(ValueError):
                self.server.storage.preview(path, 'move')
        target = self.base/'target'
        plan = self.server.storage.preview(str(target), 'move')
        target.mkdir()
        (target/'new.txt').write_text('do not overwrite')
        with self.assertRaises(ValueError):
            self.server.storage.apply(plan['token'])
        self.assertIs(self.server.catalog, self.c)
        plan = self.server.storage.preview(str(self.base/'busy'), 'move')
        self.c.scan_lock.acquire()
        try:
            with self.assertRaises(ValueError):
                self.server.storage.apply(plan['token'])
        finally:
            self.c.scan_lock.release()

    def test_pointer_failure_never_switches_active_catalog(self):
        target = self.base/'copy'
        plan = self.server.storage.preview(str(target), 'move')
        old_token = self.server.token
        with patch('catalog.storage.write_pointer', side_effect=PermissionError('read-only config')):
            with self.assertRaises(PermissionError):
                self.server.storage.apply(plan['token'])
        self.assertIs(self.server.catalog, self.c)
        self.assertEqual(self.server.token, old_token)
        self.assertEqual(read_pointer(self.config, 'unused'), self.c.data_dir)
        self.assertTrue(self.c.db_path.exists())
        self.assertTrue((target/'catalog.sqlite3').exists())

    def test_invalid_existing_database_not_opened(self):
        target = self.base/'invalid'
        target.mkdir()
        (target/'catalog.sqlite3').write_bytes(b'not sqlite')
        import sqlite3
        with self.assertRaises((ValueError, sqlite3.DatabaseError)):
            self.server.storage.preview(str(target), 'open')
        self.assertIs(self.server.catalog, self.c)
