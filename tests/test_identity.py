import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch

from catalog.core import Catalog, now


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.c = Catalog(self.base/'data')
        self.root = self.base/'media'
        self.root.mkdir()
        self.rid = self.c.add_root(str(self.root), 'belchi')

    def tearDown(self):
        self.temp.cleanup()

    def file(self, name, content=b'video-content-unique', root=None):
        path = (root or self.root)/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def scan(self, rid=None):
        ident = str(uuid.uuid4())
        rid = rid or self.rid
        with self.c.db() as db:
            db.execute("INSERT INTO scans(id,root_id,status,started_at) VALUES(?,?,'running',?)", (ident, rid, now()))
        probe = {'format': {'duration': '2'}, 'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 320, 'height': 180}]}
        def media(args, **kw):
            if args[-1].endswith('.jpg'):
                Path(args[-1]).write_bytes(b'fixture-thumbnail')
            return type('Result', (), {'stdout': json.dumps(probe).encode()})()
        self.c.scan_lock.acquire()
        with patch('catalog.core.run_media', side_effect=media):
            self.c._scan(ident, rid)
        self.assertEqual(self.c.scan_status(ident)['status'], 'done')
        self.assertEqual(self.c.scan_status(ident)['errors'], 0)

    def annotate(self, file, description='Les meves anotacions', root_id=None):
        ident, _ = self.c.identify(root_id or self.rid, file, file.relative_to(file.parent if root_id else self.root).as_posix())
        self.c.patch(ident, {'description': description, 'reviewed': True})
        self.c.apply_tags([ident], ['Família'])
        return ident

    def test_rename_and_move_restore_original_uuid_tags_review(self):
        original = self.file('clip.mp4')
        ident = self.annotate(original)
        dest = self.root/'Any nou'/'canviat.mp4'
        dest.parent.mkdir()
        original.rename(dest)
        self.scan()
        group = self.c.recovery()[0]
        self.assertTrue(group['unique'])
        self.assertEqual(group['source']['id'], ident)
        result = self.c.apply_recovery([{'source_id': ident, 'target_id': group['targets'][0]['id']}])
        self.assertEqual(result['recovered'], 1)
        v = self.c.video(ident)
        self.assertEqual(v['relative_path'], 'Any nou/canviat.mp4')
        self.assertEqual(v['description'], 'Les meves anotacions')
        self.assertTrue(v['reviewed'])
        self.assertEqual(v['tags'][0]['name'], 'Família')
        self.assertEqual(self.c.path_for(ident), dest.resolve())
        self.assertEqual(self.c.videos({})['total'], 1)
        self.assertEqual(dest.read_bytes(), b'video-content-unique')
        self.scan()
        self.assertEqual(self.c.videos({})['total'], 1)

    def test_copy_keeps_separate_identity_and_cannot_merge_available_source(self):
        original = self.file('clip.mp4')
        ident = self.annotate(original)
        copy = self.file('copy.mp4', original.read_bytes())
        target, _ = self.c.identify(self.rid, copy, copy.name)
        self.assertEqual(self.c.recovery(), [])
        with self.assertRaises(ValueError):
            self.c.apply_recovery([{'source_id': ident, 'target_id': target}])
        self.assertEqual(self.c.video(target)['description'], '')

    def test_ambiguous_copies_require_explicit_choice(self):
        original = self.file('clip.mp4')
        ident = self.annotate(original)
        content = original.read_bytes()
        original.unlink()
        self.file('copy-a.mp4', content)
        self.file('copy-b.mp4', content)
        self.scan()
        group = self.c.recovery()[0]
        self.assertFalse(group['unique'])
        self.assertEqual(len(group['targets']), 2)
        chosen = group['targets'][0]['id']
        untouched = group['targets'][1]['id']
        self.c.apply_recovery([{'source_id': ident, 'target_id': chosen}])
        self.assertEqual(self.c.video(untouched)['description'], '')
        self.assertEqual(self.c.videos({})['total'], 2)

    def test_same_name_different_content_does_not_inherit_annotations(self):
        original = self.file('clip.mp4')
        ident = self.annotate(original)
        original.write_bytes(b'different-video-content')
        target, _ = self.c.identify(self.rid, original, original.name)
        self.assertNotEqual(target, ident)
        self.assertTrue(self.c.video(ident)['retired'])
        self.assertEqual(self.c.video(target)['description'], '')
        with self.assertRaises(FileNotFoundError):
            self.c.path_for(ident)
        self.assertFalse(self.c.recovery()[0]['targets'])

    def test_move_between_registered_roots(self):
        original = self.file('clip.mp4')
        ident = self.annotate(original)
        other = self.base/'other'
        other.mkdir()
        rid = self.c.add_root(str(other), 'belchi')
        original.rename(other/'new.mp4')
        self.scan(rid)
        group = self.c.recovery()[0]
        self.c.apply_recovery([{'source_id': ident, 'target_id': group['targets'][0]['id']}])
        self.assertEqual(self.c.video(ident)['root_id'], rid)

    def test_changed_target_or_annotated_target_is_rejected(self):
        original = self.file('clip.mp4')
        ident = self.annotate(original)
        dest = self.root/'new.mp4'
        original.rename(dest)
        self.scan()
        target = self.c.recovery()[0]['targets'][0]['id']
        self.c.patch(target, {'description': 'Una altra anotació'})
        with self.assertRaises(ValueError):
            self.c.apply_recovery([{'source_id': ident, 'target_id': target}])
        self.assertEqual(self.c.video(ident)['description'], 'Les meves anotacions')
        self.assertEqual(self.c.video(target)['description'], 'Una altra anotació')
        self.c.patch(target, {'description': ''})
        dest.write_bytes(b'changed-after-preview')
        with self.assertRaises(ValueError):
            self.c.apply_recovery([{'source_id': ident, 'target_id': target}])

    def test_root_relink_finds_reorganized_files_and_rejects_wrong_folder(self):
        first = self.file('old.mp4')
        ident = self.annotate(first)
        second = self.file('other.mp4', b'other-content')
        second_id = self.annotate(second, 'Segon vídeo')
        dest = self.base/'relocated'
        dest.mkdir()
        nested = dest/'2026'
        nested.mkdir()
        first.rename(nested/'renamed.mp4')
        second.rename(dest/'second.mp4')
        wrong = self.base/'wrong'
        wrong.mkdir()
        self.file('old.mp4', b'unrelated-content', root=wrong)
        with self.assertRaises(ValueError):
            self.c.preview_root(self.rid, str(wrong))
        plan = self.c.preview_root(self.rid, str(dest))
        self.assertEqual(plan['matched'], 2)
        self.assertEqual(self.c.roots()[0]['path'], str(self.root.resolve()))
        self.c.apply_root(self.rid, plan['token'])
        self.assertEqual(self.c.path_for(ident), (nested/'renamed.mp4').resolve())
        self.assertEqual(self.c.video(second_id)['description'], 'Segon vídeo')
        self.assertEqual(self.c.video(ident)['relative_path'], '2026/renamed.mp4')

    def test_root_preview_does_not_commit_and_stale_bytes_fail(self):
        original = self.file('old.mp4')
        ident = self.annotate(original)
        dest = self.base/'relocated'
        dest.mkdir()
        new = self.file('new.mp4', original.read_bytes(), root=dest)
        plan = self.c.preview_root(self.rid, str(dest))
        new.write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            self.c.apply_root(self.rid, plan['token'])
        self.assertEqual(self.c.path_for(ident), original.resolve())

    def test_duplicate_roots_relink_keeps_all_annotations_for_manual_recovery(self):
        a = self.file('a.mp4')
        b = self.file('b.mp4')
        ida, idb = self.annotate(a, 'A'), self.annotate(b, 'B')
        dest = self.base/'relocated'
        dest.mkdir()
        a.rename(dest/'a.mp4')
        b.rename(dest/'b.mp4')
        plan = self.c.preview_root(self.rid, str(dest))
        self.assertEqual((plan['matched'], plan['ambiguous']), (0, 2))
        self.c.apply_root(self.rid, plan['token'])
        self.scan()
        groups = self.c.recovery()
        self.assertEqual(len(groups), 2)
        self.assertTrue(all(not g['unique'] and len(g['targets']) == 2 for g in groups))
        self.assertEqual(self.c.video(ida)['description'], 'A')
        self.assertEqual(self.c.video(idb)['description'], 'B')

    def test_migration_from_v1_and_old_json_preserve_annotations_and_back_up(self):
        legacy_dir = self.base/'legacy'
        with patch.object(Catalog, 'migrate_identity', lambda self: None), patch.object(Catalog, 'migrate_collections', lambda self: None), patch.object(Catalog, 'migrate_workflow', lambda self: None):
            old = Catalog(legacy_dir)
            old.seed_demo()
            with old.db() as db:
                original_ids = [r[0] for r in db.execute('SELECT id FROM videos')]
        migrated = Catalog(legacy_dir)
        self.assertEqual([v['id'] for v in migrated.videos({})['items']].__len__(), 10)
        self.assertEqual({v['id'] for v in migrated.videos({})['items']}, set(original_ids))
        self.assertTrue(list((legacy_dir/'backups').glob('*.sqlite3')))
        with migrated.db() as db:
            self.assertEqual(db.execute('SELECT version FROM schema_version').fetchone()[0], 4)
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
        document = migrated.export()
        document['version'] = 1
        for v in document['tables']['videos']:
            for name in ('sha256', 'fingerprint', 'retired', 'identity_state'):
                v.pop(name)
        restored = Catalog(self.base/'imported')
        restored.import_empty(document)
        self.assertEqual(restored.videos({})['total'], 10)

    def test_two_missing_identical_sources_are_not_unique_and_bulk_is_atomic(self):
        a = self.file('a.mp4')
        b = self.file('b.mp4')
        ida, idb = self.annotate(a, 'A'), self.annotate(b, 'B')
        a.rename(self.root/'new-a.mp4')
        b.rename(self.root/'new-b.mp4')
        self.scan()
        groups = self.c.recovery()
        self.assertTrue(all(not g['unique'] for g in groups))
        targets = groups[0]['targets']
        pairs = [{'source_id': ida, 'target_id': targets[0]['id']}, {'source_id': idb, 'target_id': targets[1]['id']}]
        self.c.patch(targets[1]['id'], {'description': 'No fusionar'})
        with self.assertRaises(ValueError):
            self.c.apply_recovery(pairs)
        self.assertFalse(self.c.video(ida)['available'])
        self.assertEqual(self.c.video(targets[0]['id'])['description'], '')
        self.assertEqual(self.c.video(idb)['description'], 'B')

    def test_relink_rejects_overlapping_root_and_consumed_plan(self):
        video = self.file('a.mp4')
        self.annotate(video)
        dest = self.base/'other'
        dest.mkdir()
        self.file('a.mp4', video.read_bytes(), root=dest)
        other_id = self.c.add_root(str(dest), 'belchi')
        with self.assertRaises(ValueError):
            self.c.preview_root(self.rid, str(dest))
        with self.c.db() as db:
            db.execute('DELETE FROM roots WHERE id=?', (other_id,))
        plan = self.c.preview_root(self.rid, str(dest))
        self.c.apply_root(self.rid, plan['token'])
        with self.assertRaises(ValueError):
            self.c.apply_root(self.rid, plan['token'])

    def test_export_v2_preserves_identity_for_moves_after_restoring(self):
        video = self.file('old.mp4')
        ident = self.annotate(video)
        document = self.c.export()
        restored = Catalog(self.base/'restored')
        restored.import_empty(document)
        self.c = restored
        video.rename(self.root/'new.mp4')
        self.scan()
        group = restored.recovery()[0]
        restored.apply_recovery([{'source_id': ident, 'target_id': group['targets'][0]['id']}])
        self.assertEqual(restored.video(ident)['description'], 'Les meves anotacions')


if __name__ == '__main__':
    unittest.main()
