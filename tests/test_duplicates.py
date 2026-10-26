from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from catalog.core import Catalog


class DuplicateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.c = Catalog(self.base/'data')
        self.first = self.base/'first'; self.first.mkdir()
        self.second = self.base/'second'; self.second.mkdir()
        self.a = self.c.add_root(str(self.first), 'belchi')
        self.b = self.c.add_root(str(self.second), 'nuria')

    def tearDown(self):
        self.temp.cleanup()

    def video(self, root, name, content):
        folder = self.first if root == self.a else self.second
        file = folder/name; file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
        return self.c.identify(root, file, name)[0]

    def test_content_groups_keep_metadata_and_whole_group_when_one_copy_matches(self):
        a = self.video(self.a, 'original.mp4', b'content-one')
        b = self.video(self.b, 'sub/copy.mp4', b'content-one')
        self.video(self.b, 'different.mp4', b'content-two')
        self.c.patch(a, {'description': 'Moment especial'})
        group = self.c.create_collection('Projecte')
        self.c.collection_members(group['id'], [b])
        before = self.c.export()
        with patch('catalog.identity.full_hash', side_effect=AssertionError('GET must not hash')):
            result = self.c.duplicates({'owner': 'belchi', 'q': 'especial'})
        self.assertEqual(result['total_groups'], 1)
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['extra_copies'], 1)
        items = {v['id']: v for v in result['items']}
        self.assertTrue(items[a]['matches_filters'])
        self.assertFalse(items[b]['matches_filters'])
        self.assertEqual(items[b]['collections'], [{'id':group['id'], 'name':'Projecte'}])
        self.assertEqual(items[b]['owner_id'], 'nuria')
        self.assertEqual(Path(items[b]['full_path']), self.second/'sub/copy.mp4')
        self.assertEqual(before['tables'], self.c.export()['tables'])
        self.assertEqual((self.first/'original.mp4').read_bytes(), b'content-one')

    def test_partial_missing_and_retired_hashes_do_not_create_duplicates(self):
        a = self.video(self.a, 'a.mp4', b'same-content')
        b = self.video(self.b, 'b.mp4', b'same-content')
        with self.c.db() as db:db.execute('UPDATE videos SET sha256=NULL WHERE id=?', (b,))
        result = self.c.duplicates({})
        self.assertEqual(result['total_groups'], 0)
        self.assertEqual(result['unverified'], 1)
        with self.c.db() as db:
            db.execute('UPDATE videos SET sha256=(SELECT sha256 FROM videos WHERE id=?),retired=1 WHERE id=?', (a,b))
        self.assertEqual(self.c.duplicates({})['total_groups'], 0)

    def test_exclusions_hide_copies_but_missing_disk_keeps_last_known_match(self):
        a = self.video(self.a, 'a.mp4', b'content')
        b = self.video(self.b, 'b.mp4', b'content')
        with self.c.db() as db:
            db.execute('UPDATE roots SET available=0 WHERE id=?', (self.b,))
        result = self.c.duplicates({})
        self.assertEqual(result['total_groups'], 1)
        self.assertFalse(next(v for v in result['items'] if v['id']==b)['root_available'])
        plan = self.c.preview_removal(a, 'exclude'); self.c.apply_removal(a, plan['token'])
        self.assertEqual(self.c.duplicates({})['total_groups'], 0)
        self.assertEqual(self.c.duplicates({'excluded':'1'})['total_groups'], 0)
        plan = self.c.preview_removal(b, 'exclude'); self.c.apply_removal(b, plan['token'])
        self.assertEqual(self.c.duplicates({'excluded':'1'})['total_groups'], 1)

    def test_pagination_counts_groups_and_never_splits_a_group(self):
        for i in range(3):
            for j in range(3):self.video(self.a, f'{i}-{j}.mp4', str(i).encode())
        first = self.c.duplicates({'limit':'2'})
        second = self.c.duplicates({'limit':'2', 'page':'2'})
        self.assertEqual((first['total_groups'], first['total'], first['pages']), (3,9,2))
        self.assertEqual(len(first['items']), 6)
        self.assertEqual(len(second['items']), 3)
        self.assertFalse({v['id'] for v in first['items']} & {v['id'] for v in second['items']})
        self.assertEqual(len(self.c.duplicates({'limit':'all'})['items']), 9)
        self.assertEqual(self.c.duplicates({'limit':'2','page':'100'})['page'], 2)


if __name__ == '__main__':
    unittest.main()
