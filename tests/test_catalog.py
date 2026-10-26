import hashlib
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from catalog.core import Catalog, normalize
from catalog.server import LocalServer


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.c = Catalog(self.base / 'data')
        self.c.seed_demo()

    def tearDown(self):
        self.tmp.cleanup()

    def test_search_accent_middle_dot_cross_fields_and_order(self):
        self.assertEqual(normalize('GAL·LA'), 'galla')
        matches = self.c.videos({'q': 'BICICLETA julia'})['items']
        self.assertEqual(len(matches), 1)
        v = matches[0]
        self.c.patch(v['id'], {'description': 'Menja un gelat a Roma'})
        self.assertEqual(len(self.c.videos({'q': 'julia roma gelat'})['items']), 1)
        self.assertEqual(len(self.c.videos({'q': 'julia roma mar'})['items']), 0)

    def test_persistence_review_independent_from_description(self):
        v = next(v for v in self.c.videos({})['items'] if not v['description'])
        self.c.patch(v['id'], {'reviewed': True})
        reopened = Catalog(self.c.data_dir)
        self.assertTrue(reopened.video(v['id'])['reviewed'])
        self.assertEqual(reopened.video(v['id'])['description'], '')
        self.assertNotIn(v['id'], [i['id'] for i in reopened.videos({'state': 'unreviewed'})['items']])

    def test_bulk_tags_additive_and_normalized(self):
        videos = self.c.videos({})['items']
        before = {v['id']: {t['name'] for t in v['tags']} for v in videos}
        self.c.apply_tags([v['id'] for v in videos], ['  VACANCES  ', 'vacances'])
        for v in videos:
            tags = {t['name'] for t in self.c.video(v['id'])['tags']}
            self.assertEqual(tags, before[v['id']] | {'VACANCES'})
        self.c.apply_tags([videos[0]['id']], ['vacances'], remove=True)
        self.assertEqual({t['name'] for t in self.c.video(videos[0]['id'])['tags']}, before[videos[0]['id']])

    def test_date_folder_and_pagination(self):
        r = self.c.videos({'start': '2026-08-14', 'end': '2026-08-14'})
        self.assertEqual(r['total'], 1)
        self.assertEqual(self.c.videos({'unknown': '1'})['total'], 1)
        self.assertEqual(self.c.videos({'root': 'demo', 'folder': 'Estiu'})['total'], 3)
        r = self.c.videos({'limit': '3', 'page': '2'})
        self.assertEqual(len(r['items']), 3)
        self.assertEqual(r['pages'], 4)
        self.assertIsNone(self.c.videos({'sort': 'asc'})['items'][-1]['recorded_at'])

    def test_page_sizes_default_50_and_all_has_no_100_item_cap(self):
        with self.c.db() as db:
            for i in range(115):
                ident = 'pagination-' + str(i)
                db.execute("INSERT INTO videos(id,root_id,relative_path,demo) VALUES(?,'demo',?,1)", (ident, ident+'.mp4'))
                db.execute('INSERT INTO annotations(video_id,description,updated_at) VALUES(?,?,?)', (ident, 'Pagination fixture', 'now'))
        self.assertEqual(len(self.c.videos({})['items']), 50)
        self.assertEqual(self.c.videos({})['pages'], 3)
        for size in (25, 50, 100):
            self.assertEqual(len(self.c.videos({'limit': str(size)})['items']), size)
        self.assertEqual(len(self.c.videos({'limit': '50', 'page': '3'})['items']), 25)
        all_items = self.c.videos({'limit': 'all', 'page': '3'})
        self.assertEqual((len(all_items['items']), all_items['pages'], all_items['page']), (125, 1, 1))
        self.assertEqual(self.c.videos({'limit': 'all', 'q': 'pagination'})['total'], 115)

    def test_export_restore_into_empty_and_consistent_backup(self):
        exported = self.c.export()
        restored = Catalog(self.base / 'restored')
        restored.import_empty(json.loads(json.dumps(exported)))
        self.assertEqual(restored.export()['tables'], exported['tables'])
        with self.assertRaises(ValueError):
            restored.import_empty(exported)
        backup = self.c.backup()
        with sqlite3.connect(backup) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('SELECT count(*) FROM videos').fetchone()[0], 10)

    def test_scan_incremental_original_unchanged_and_failure_preserves_annotations(self):
        root = self.base / 'media'
        root.mkdir()
        video = root / '20261025-test.mp4'
        video.write_bytes(b'fictional media fixture')
        original = hashlib.sha256(video.read_bytes()).hexdigest()
        rid = self.c.add_root(str(root), 'belchi')
        self.assertEqual(self.c.add_root(str(root), 'belchi'), rid)
        nested = root / 'nested'
        nested.mkdir()
        with self.assertRaises(ValueError):
            self.c.add_root(str(nested), 'belchi')
        probe = {'format': {'duration': '3.0'}, 'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 640, 'height': 360}]}
        class Result:
            stdout = json.dumps(probe).encode()
        with patch('catalog.core.run_media', return_value=Result()), patch('catalog.core.executable', return_value='fixture'):
            ident = self.c.index_file(rid, video, video.name)
            self.assertEqual(hashlib.sha256(video.read_bytes()).hexdigest(), original)
            self.c.patch(ident, {'description': 'Anotació de prova', 'reviewed': True})
            (self.c.cache / (ident + '.jpg')).write_bytes(b'fixture thumbnail')
            with patch('catalog.core.run_media', side_effect=AssertionError('No reextract unchanged file')):
                self.assertEqual(self.c.index_file(rid, video, video.name), ident)
        video.write_bytes(video.read_bytes() + b'changed')
        with patch('catalog.core.run_media', side_effect=RuntimeError('Bad media')), patch('catalog.core.executable', return_value='fixture'):
            with self.assertRaises(RuntimeError):
                self.c.index_file(rid, video, video.name)
        self.assertEqual(self.c.video(ident)['description'], 'Anotació de prova')
        self.assertTrue(self.c.video(ident)['retired'])
        replacement = next(v for v in self.c.videos({})['items'] if v['root_id'] == rid and not v['retired'])
        self.assertEqual(replacement['extraction'], 'error')
        self.assertEqual(replacement['description'], '')
        self.assertEqual(video.read_bytes(), b'fictional media fixturechanged')

    def test_path_escape_is_rejected(self):
        root = self.base / 'media'
        root.mkdir()
        rid = self.c.add_root(str(root), 'belchi')
        outside = self.base / 'outside.mp4'
        outside.write_bytes(b'private')
        with self.c.db() as db:
            db.execute('INSERT INTO videos(id,root_id,relative_path) VALUES(?,?,?)', ('ab123', rid, '../outside.mp4'))
            db.execute('INSERT INTO annotations(video_id,updated_at) VALUES(?,?)', ('ab123', 'now'))
        with self.assertRaises(PermissionError):
            self.c.path_for('ab123')


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.c = Catalog(self.base / 'data')
        self.c.seed_demo()
        self.server = LocalServer(self.c, 0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        h = {'Content-Type': 'application/json'}
        h.update(headers or {})
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_desktop_raise_never_leaves_window_topmost(self):
        from catalog.foreground import raise_temporarily
        from unittest.mock import Mock
        user=Mock()
        user.SetWindowPos.return_value=True
        with patch('catalog.foreground.time.sleep'):
            self.assertTrue(raise_temporarily(user,123))
        self.assertEqual(user.SetWindowPos.call_args_list[0].args[1],-1)
        self.assertEqual(user.SetWindowPos.call_args_list[-1].args[1],-2)
        user.reset_mock()
        user.SetForegroundWindow.side_effect=OSError('focus denied')
        with self.assertRaises(OSError):raise_temporarily(user,123)
        self.assertEqual(user.SetWindowPos.call_args_list[-1].args[1],-2)

    def test_desktop_actions_validate_paths_and_do_not_claim_success_when_blocked(self):
        from catalog.desktop import open_desktop_path
        with patch('catalog.desktop.restricted_desktop',return_value=True),patch('catalog.desktop.os.startfile') as launch:
            with self.assertRaises(ValueError):open_desktop_path(self.base)
            launch.assert_not_called()
        root=self.base/'desktop-videos';root.mkdir()
        file=root/'clip.mp4';file.write_bytes(b'video-fixture')
        rid=self.c.add_root(str(root),'belchi')
        ident,_=self.c.identify(rid,file,file.name)
        headers={'X-Catalog-Token':self.server.token}
        for suffix,options in (('reveal',{'select_file':True}),('open',{})):
            with patch('catalog.server.open_desktop_path',return_value={'foreground':True}) as launch:
                self.assertEqual(self.request('POST','/api/videos/'+ident+'/'+suffix,{},headers)[0],200)
                launch.assert_called_once_with(file,**options)
            with patch('catalog.server.open_desktop_path',side_effect=ValueError('restricted')):
                self.assertEqual(self.request('POST','/api/videos/'+ident+'/'+suffix,{},headers)[0],400)

    def test_transcoding_is_unavailable_and_creates_no_copies(self):
        ident=self.c.videos({})['items'][0]['id']
        status,_,_=self.request('POST','/api/videos/'+ident+'/prepare-preview',{},headers={'X-Catalog-Token':self.server.token})
        self.assertEqual(status,404)
        self.assertEqual(self.request('GET','/api/videos/'+ident+'/preview-stream')[0],404)
        self.assertFalse((self.c.data_dir/'preview-cache').exists())

    def test_external_origins_and_host_and_token(self):
        ident = self.c.videos({})['items'][0]['id']
        path = '/api/videos/' + ident
        self.assertEqual(self.request('GET', '/api/config', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('GET', '/api/config', headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.request('PATCH', path, {'description': 'bad'})[0], 403)
        self.assertEqual(self.request('PATCH', path, {'description': 'bad'}, {'X-Catalog-Token': self.server.token, 'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request('PATCH', path, {'description': 'persisted'}, {'X-Catalog-Token': self.server.token, 'Origin': self.server.origin})[0], 200)
        self.assertEqual(self.c.video(ident)['description'], 'persisted')
        self.assertEqual(self.request('PATCH', path, {'reviewed': 'false'}, {'X-Catalog-Token': self.server.token})[0], 400)

    def test_range_streaming_and_invalid_ranges(self):
        root = self.base / 'videos'
        root.mkdir()
        file = root / 'clip.mp4'
        content = b'0123456789abcdef'
        file.write_bytes(content)
        rid = self.c.add_root(str(root), 'belchi')
        with self.c.db() as db:
            db.execute('INSERT INTO videos(id,root_id,relative_path) VALUES(?,?,?)', ('ab123', rid, 'clip.mp4'))
            db.execute('INSERT INTO annotations(video_id,updated_at) VALUES(?,?)', ('ab123', 'now'))
        path = '/api/videos/ab123/stream'
        status, headers, body = self.request('GET', path, headers={'Range': 'bytes=2-5'})
        self.assertEqual((status, body), (206, b'2345'))
        self.assertEqual(headers['Content-Range'], 'bytes 2-5/16')
        self.assertEqual(self.request('GET', path, headers={'Range': 'bytes=-3'})[2], b'def')
        for value in ('bytes=999-', 'bytes=5-1', 'bytes=0-2,4-6', 'bytes=-0'):
            self.assertEqual(self.request('GET', path, headers={'Range': value})[0], 416)
        self.assertEqual(file.read_bytes(), content)

    def test_static_csp_sample_thumbnail_and_no_arbitrary_file_access(self):
        status, headers, body = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        self.assertIn('Què passa al vídeo?'.encode(), body)
        self.assertEqual(self.request('GET', '/../../app.py')[0], 404)
        ident = self.c.videos({})['items'][0]['id']
        self.assertIn(b'MOSTRA FICT', self.request('GET', '/api/videos/' + ident + '/thumbnail')[2])

    def test_public_distribution_uses_symbol_when_optional_portrait_is_absent(self):
        static=self.base/'public-web';static.mkdir()
        symbol=b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        (static/'van.svg').write_bytes(symbol)
        with patch('catalog.server.STATIC',static):
            status,headers,body=self.request('GET','/van.png')
            self.assertEqual(status,200)
            self.assertTrue(headers['Content-Type'].startswith('image/svg+xml'))
            self.assertEqual(body,symbol)
            (static/'van.png').write_bytes(b'local-portrait-fixture')
            self.assertEqual(self.request('GET','/van.png')[2],b'local-portrait-fixture')

    def test_http_recovery_preserves_annotations_and_requires_token(self):
        root = self.base/'real'
        root.mkdir()
        rid = self.c.add_root(str(root), 'belchi')
        original = root/'before.mp4'
        original.write_bytes(b'fixture-video-identity')
        ident, _ = self.c.identify(rid, original, original.name)
        self.c.patch(ident, {'description': 'Keep this', 'reviewed': True})
        self.c.apply_tags([ident], ['test'])
        dest = root/'after.mp4'
        original.rename(dest)
        target, _ = self.c.identify(rid, dest, dest.name)
        status, _, body = self.request('GET', '/api/recovery')
        groups = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(groups[0]['unique'])
        pairs = {'pairs': [{'source_id': ident, 'target_id': target}]}
        self.assertEqual(self.request('POST', '/api/recovery/apply', pairs)[0], 403)
        status, _, body = self.request('POST', '/api/recovery/apply', pairs, {'X-Catalog-Token': self.server.token})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['recovered'], 1)
        self.assertEqual(self.c.video(ident)['description'], 'Keep this')
        self.assertEqual(self.c.path_for(ident), dest.resolve())

    def test_http_root_preview_confirm_and_native_picker_select_only(self):
        root = self.base/'real'
        root.mkdir()
        rid = self.c.add_root(str(root), 'belchi')
        original = root/'before.mp4'
        original.write_bytes(b'fixture-video-identity')
        ident, _ = self.c.identify(rid, original, original.name)
        self.c.patch(ident, {'description': 'Keep this'})
        dest = self.base/'new-root'
        dest.mkdir()
        original.rename(dest/'after.mp4')
        headers = {'X-Catalog-Token': self.server.token}
        with patch('catalog.server.subprocess.run', return_value=type('Result', (), {'stdout': json.dumps(str(dest))+'\n'})()):
            status, _, body = self.request('POST', '/api/roots/pick', {'select_only': True}, headers)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)['path'], str(dest))
            self.assertEqual(len(self.c.roots()), 2)
        status, _, body = self.request('POST', '/api/roots/'+rid+'/preview', {'path': str(dest)}, headers)
        self.assertEqual(status, 200)
        plan = json.loads(body)
        self.assertEqual(plan['matched'], 1)
        self.assertEqual(next(r for r in self.c.roots() if r['id']==rid)['path'], str(root.resolve()))
        status, _, _ = self.request('POST', '/api/roots/'+rid+'/relink', {'token': plan['token']}, headers)
        self.assertEqual(status, 200)
        self.assertEqual(self.c.path_for(ident), (dest/'after.mp4').resolve())

    def test_http_collection_lifecycle_protected_and_exported(self):
        headers = {'X-Catalog-Token': self.server.token}
        self.assertEqual(self.request('POST', '/api/collections', {'name': 'Muntatge'})[0], 403)
        status, _, body = self.request('POST', '/api/collections', {'name': 'Muntatge'}, headers)
        self.assertEqual(status, 201)
        ident = json.loads(body)['id']
        video = self.c.videos({})['items'][0]['id']
        self.assertEqual(self.request('POST', '/api/collections/'+ident+'/members', {'ids': [video]}, headers)[0], 200)
        status, _, body = self.request('GET', '/api/videos?collection='+ident)
        self.assertEqual(json.loads(body)['total'], 1)
        self.assertEqual(self.request('PATCH', '/api/collections/'+ident, {'name': 'Nou nom'}, headers)[0], 200)
        self.assertEqual(self.request('POST', '/api/collections/'+ident+'/members', {'ids': [video], 'remove': 'false'}, headers)[0], 400)
        self.assertEqual(self.request('POST', '/api/collections/'+ident+'/delete', {}, headers)[0], 200)
        self.assertIsNotNone(self.c.video(video))

    def test_http_owner_required_and_conscious_exception(self):
        headers = {'X-Catalog-Token': self.server.token}
        root = self.base/'new-videos'
        root.mkdir()
        self.assertEqual(self.request('POST', '/api/roots', {'path': str(root)}, headers)[0], 400)
        status, _, body = self.request('POST', '/api/roots', {'path': str(root), 'owner_id': 'nuria'}, headers)
        self.assertEqual(status, 200)
        rid = json.loads(body)['id']
        self.assertEqual(next(r for r in self.c.roots() if r['id']==rid)['owner_id'], 'nuria')
        ident = next(v['id'] for v in self.c.videos({})['items'] if not v['description'] and not v['tags'])
        self.assertEqual(self.request('POST', '/api/bulk/annotation-decision', {'ids': [ident], 'omit': True}, headers)[0], 200)
        status, _, body = self.request('GET', '/api/videos?state=empty_by_choice&owner=belchi')
        self.assertEqual(json.loads(body)['total'], 1)

    def test_http_catalog_switch_invalidates_old_tab_token(self):
        old = self.server.token
        headers = {'X-Catalog-Token': old}
        status, _, body = self.request('POST', '/api/storage/preview', {'path': str(self.base/'empty-catalog'), 'mode': 'create'}, headers)
        self.assertEqual(status, 200)
        token = json.loads(body)['token']
        self.assertEqual(self.request('POST', '/api/storage/apply', {'token': token}, headers)[0], 200)
        self.assertNotEqual(self.server.token, old)
        self.assertEqual(self.request('POST', '/api/collections', {'name': 'Wrong catalog'}, headers)[0], 403)
        self.assertEqual(self.request('GET', '/api/videos', headers=headers)[0], 403)
        status, _, body = self.request('GET', '/api/videos')
        self.assertEqual(json.loads(body)['total'], 0)
        self.assertEqual(self.c.videos({})['total'], 10)


if __name__ == '__main__':
    unittest.main()
