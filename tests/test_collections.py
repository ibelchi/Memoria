from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from catalog.core import Catalog


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.c = Catalog(self.base/'data')
        self.c.seed_demo()
        self.ids = [v['id'] for v in self.c.videos({})['items']]

    def tearDown(self):
        self.temp.cleanup()

    def test_create_rename_many_memberships_and_filter_with_search(self):
        a = self.c.create_collection('  Muntatge estiu  ')
        b = self.c.create_collection('Família')
        self.c.collection_members(a['id'], self.ids[:3])
        self.c.collection_members(a['id'], self.ids[:3])
        self.c.collection_members(b['id'], [self.ids[0]])
        self.assertEqual(self.c.videos({'collection': a['id']})['total'], 3)
        self.assertEqual(len(self.c.video(self.ids[0])['collections']), 2)
        self.c.patch(self.ids[0], {'description': 'Contingut especial'})
        self.assertEqual(self.c.videos({'collection': a['id'], 'q': 'especial'})['total'], 1)
        self.c.rename_collection(a['id'], 'Nou nom')
        with self.assertRaises(ValueError):
            self.c.create_collection(' NOU   NOM ')
        with self.assertRaises(ValueError):
            self.c.rename_collection(b['id'], 'nou nom')
        reopened = Catalog(self.c.data_dir)
        self.assertEqual(reopened.videos({'collection': a['id']})['total'], 3)
        self.assertEqual(next(c for c in reopened.collections() if c['id']==a['id'])['name'], 'Nou nom')

    def test_remove_and_delete_keep_media_annotations_and_other_collections(self):
        root = self.base/'media'
        root.mkdir()
        file = root/'clip.mp4'
        file.write_bytes(b'untouched-media')
        rid = self.c.add_root(str(root), 'belchi')
        ident, _ = self.c.identify(rid, file, file.name)
        self.c.patch(ident, {'description': 'Keep annotations', 'reviewed': True})
        self.c.apply_tags([ident], ['Keep tag'])
        a, b = self.c.create_collection('A'), self.c.create_collection('B')
        self.c.collection_members(a['id'], [ident])
        self.c.collection_members(b['id'], [ident])
        self.c.collection_members(a['id'], [ident], remove=True)
        self.c.delete_collection(a['id'])
        v = self.c.video(ident)
        self.assertEqual(v['description'], 'Keep annotations')
        self.assertTrue(v['reviewed'])
        self.assertEqual(v['tags'][0]['name'], 'Keep tag')
        self.assertEqual(v['collections'][0]['id'], b['id'])
        self.assertEqual(file.read_bytes(), b'untouched-media')

    def test_export_restore_preserves_collections_and_atomic_add(self):
        a = self.c.create_collection('Muntatge')
        self.c.collection_members(a['id'], self.ids[:2])
        with self.assertRaises(ValueError):
            self.c.collection_members(a['id'], [self.ids[2], 'unknown'])
        self.assertEqual(self.c.videos({'collection': a['id']})['total'], 2)
        document = self.c.export()
        self.assertEqual(document['version'], 4)
        restored = Catalog(self.base/'restored')
        restored.import_empty(document)
        self.assertEqual(restored.export()['tables'], document['tables'])

    def test_recovery_keeps_source_memberships_and_transfers_provisional_memberships(self):
        root = self.base/'media'
        root.mkdir()
        source = root/'old.mp4'
        source.write_bytes(b'content-to-relocate')
        rid = self.c.add_root(str(root), 'belchi')
        ident, _ = self.c.identify(rid, source, source.name)
        self.c.patch(ident, {'description': 'Original'})
        a, b = self.c.create_collection('Source group'), self.c.create_collection('New group')
        self.c.collection_members(a['id'], [ident])
        destination = root/'new.mp4'
        source.rename(destination)
        target, _ = self.c.identify(rid, destination, destination.name)
        self.c.collection_members(b['id'], [target])
        self.c.collection_members(a['id'], [target])
        self.c.apply_recovery([{'source_id': ident, 'target_id': target}])
        self.assertEqual({c['id'] for c in self.c.video(ident)['collections']}, {a['id'], b['id']})
        self.assertEqual(self.c.videos({'collection': a['id']})['total'], 1)
        self.assertEqual(self.c.videos({'collection': b['id']})['items'][0]['id'], ident)

    def test_migration_from_schema2_and_legacy_json(self):
        folder = self.base/'legacy'
        with patch.object(Catalog, 'migrate_collections', lambda self: None), patch.object(Catalog, 'migrate_workflow', lambda self: None):
            old = Catalog(folder)
            old.seed_demo()
            with old.db() as db:
                db.execute("UPDATE annotations SET description='Preserved before collections' WHERE video_id=(SELECT id FROM videos LIMIT 1)")
        migrated = Catalog(folder)
        with migrated.db() as db:
            self.assertEqual(db.execute('SELECT version FROM schema_version').fetchone()[0], 4)
        self.assertEqual(migrated.videos({'q': 'preserved'})['total'], 1)
        self.assertEqual(migrated.collections(), [])
        document = migrated.export()
        document['version'] = 2
        document['tables'].pop('collections')
        document['tables'].pop('collection_videos')
        restored = Catalog(self.base/'legacy-import')
        restored.import_empty(document)
        self.assertEqual(restored.videos({'q': 'preserved'})['total'], 1)
        self.assertEqual(restored.collections(), [])
