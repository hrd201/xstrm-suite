import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib import error

from src import control
from src.identity import IdentityService, IdentityError, EmbyClient, hints


class FakeEmby:
    def __init__(self):
        self.server = 'test-server'
        self.items = []
        self.calls = []
        self.results = [{'Name': '新·驯龙高手', 'ProductionYear': 2025,
                         'ProviderIds': {'Tmdb': '1087192'}, 'ImageUrl': 'https://image.invalid/poster.jpg',
                         'SearchProviderName': 'TheMovieDb', 'Overview': '简介'}]
        self.apply_error = False

    def call(self, path, data=None, image=False):
        self.calls.append((path, copy.deepcopy(data)))
        if path == '/System/Info':
            return {'Id': self.server}
        if path.startswith('/Items?'):
            from urllib.parse import parse_qs, urlsplit
            q = parse_qs(urlsplit(path).query)
            items = [x for x in self.items if str(x['Id']) == q['Ids'][0]] if 'Ids' in q else self.items
            start = int(q.get('StartIndex', [0])[0]); limit = int(q.get('Limit', [200])[0])
            return {'Items': copy.deepcopy(items[start:start+limit]), 'TotalRecordCount': len(items)}
        if path == '/Items/RemoteSearch/Movie':
            return copy.deepcopy(self.results)
        if path.startswith('/Items/RemoteSearch/Apply/'):
            if self.apply_error:
                raise IdentityError('Emby 请求超时', 502)
            self.items[0]['ProviderIds'] = data['ProviderIds']
            self.items[0]['Name'] = data['Name']
            return None
        if image:
            return b'image', 'image/jpeg'
        raise AssertionError(path)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = self.root/'config.yaml'; self.media = self.root/'media'
        self.file = self.media/'How.to.Train.Your.Dragon.2025.2160p.MA'/'How.to.Train.Your.Dragon.2025.strm'
        self.file.parent.mkdir(parents=True); self.file.write_text('/mnt/115/原目录/原视频.mkv', encoding='utf-8')
        control.atomic_write(self.cfg, {'output_root': str(self.media), 'emby': {'host':'http://emby','api_key':'never-expose-key'}})
        self.client = FakeEmby()
        self.client.items = [{'Id':'9','Name':'2160p.MA','Type':'Movie','Path':str(self.file), 'ProviderIds':{}}]
        self.now = 10000
        self.service = IdentityService(self.root,self.cfg,lambda _:self.client,lambda:self.now)
        # Windows cannot use the production kernel flock; Linux has a separate test.
        self.lock_patch = mock.patch.object(self.service, 'write_lock', contextlib.nullcontext)
        self.lock_patch.start(); self.addCleanup(self.lock_patch.stop)

    def search(self, **extra):
        item = self.service.listing()['items'][0]
        payload = {'item_id':item['id'],'revision':item['revision'],'query':'How to Train Your Dragon','year':2025, **extra}
        return self.service.search(payload)

    def apply(self, candidate=None):
        candidate = candidate or self.search()['candidates'][0]['id']
        return self.service.apply({'candidate_id':candidate,'confirmed':True})

    def test_search_only_and_opaque_poster_no_secret_or_remote_url(self):
        result = self.search()
        self.assertEqual(result['candidates'][0]['tmdb_id'],'1087192')
        self.assertNotIn('image.invalid',json.dumps(result))
        self.assertNotIn('never-expose',json.dumps(self.service.listing()))
        self.assertFalse(any('/Apply/' in path for path,_ in self.client.calls))
        self.assertEqual(self.file.read_text(encoding='utf-8'),'/mnt/115/原目录/原视频.mkv')
        self.assertEqual(self.service.image(result['candidates'][0]['id']),(b'image','image/jpeg'))
        self.assertIn('ProviderName=TheMovieDb',self.client.calls[-1][0])

    def test_apply_idempotent_verifies_identity_then_metadata(self):
        candidate = self.search()['candidates'][0]['id']
        result = self.apply(candidate)
        self.assertEqual(self.apply(candidate)['operation_id'],result['operation_id'])
        self.assertEqual(sum('/Apply/' in p for p,_ in self.client.calls),1)
        status = self.service.operation(result['operation_id'])
        self.assertEqual(status['state'],'refreshing')
        self.assertIn('身份已绑定',status['message'])
        self.client.items[0].update(Overview='简介',ImageTags={'Primary':'tag'})
        self.assertEqual(self.service.operation(result['operation_id'])['state'],'completed')

    def test_restart_and_new_item_id_reuses_binding_but_content_change_does_not(self):
        result = self.apply()
        restarted = IdentityService(self.root,self.cfg,lambda _:self.client,lambda:self.now)
        self.assertEqual(restarted.operation(result['operation_id'])['tmdb_id'],'1087192')
        self.client.items[0].update(Id='99', ProviderIds={})
        item = restarted.listing()['items'][0]
        self.assertEqual(item['binding']['tmdb_id'],'1087192')
        self.file.write_text('/mnt/115/另一部.mkv',encoding='utf-8')
        self.assertIsNone(restarted.listing()['items'][0]['binding'])

    def test_candidate_file_revision_server_expiry_and_confirmation_guards(self):
        candidate = self.search()['candidates'][0]['id']
        with self.assertRaises(IdentityError):self.service.apply({'candidate_id':candidate})
        self.file.write_text('/changed.mkv')
        with self.assertRaises(IdentityError):self.apply(candidate)
        candidate = self.search()['candidates'][0]['id']
        self.client.items[0]['ProviderIds']={'Tmdb':'other'}
        with self.assertRaises(IdentityError):self.apply(candidate)
        self.client.items[0]['ProviderIds']={}
        self.client.server='another-server'
        with self.assertRaises(IdentityError):self.apply(candidate)
        self.client.server='test-server';self.now+=1801
        with self.assertRaises(IdentityError):self.apply(candidate)
        self.assertFalse(any('/Apply/' in p for p,_ in self.client.calls))

    def test_request_validation_and_precise_id_filters_results(self):
        for fields in ({'year':'2025;rm'},{'tmdb_id':'0'},{'tmdb_id':'../x'},{'query':'','tmdb_id':''}):
            with self.assertRaises(IdentityError):self.search(**fields)
        self.client.results.append({'Name':'其他片','ProviderIds':{'Tmdb':'42'}})
        result=self.search(tmdb_id='1087192')
        self.assertEqual(len(result['candidates']),1)
        request_body=next(data for path,data in reversed(self.client.calls) if path=='/Items/RemoteSearch/Movie')
        self.assertNotIn('Year',request_body['SearchInfo'])
        self.assertEqual(request_body['SearchInfo']['Name'],'')

    def test_refresh_timeout_does_not_reuse_preexisting_metadata_as_success(self):
        self.client.items[0].update(Name='新·驯龙高手',ProviderIds={'Tmdb':'1087192'},Overview='旧简介',ImageTags={'Primary':'old'})
        item=self.service.listing('all')['items'][0]
        candidate=self.service.search({'item_id':item['id'],'revision':item['revision'],'tmdb_id':'1087192'})['candidates'][0]['id']
        self.client.apply_error=True
        result=self.apply(candidate)
        self.assertEqual(self.service.operation(result['operation_id'])['state'],'refreshing')
        self.now+=181
        op=self.service.operation(result['operation_id'])
        self.assertEqual(op['state'],'warning');self.assertIn('提交响应异常',op['message'])

    def test_requested_image_replacement_requires_image_change(self):
        self.client.items[0]['ImageTags']={'Primary':'old'}
        candidate=self.search()['candidates'][0]['id']
        result=self.service.apply({'candidate_id':candidate,'confirmed':True,'replace_images':True})
        self.client.items[0]['Overview']='简介'
        self.assertEqual(self.service.operation(result['operation_id'])['state'],'refreshing')
        self.now+=181
        self.assertEqual(self.service.operation(result['operation_id'])['state'],'warning')
        self.client.items[0]['ImageTags']={'Primary':'new'}
        self.assertEqual(self.service.operation(result['operation_id'])['state'],'completed')

    def test_database_upgrade_keeps_existing_history(self):
        result=self.apply()
        with self.service.db() as db:
            db.execute('ALTER TABLE operations DROP COLUMN submitted')
            db.execute('ALTER TABLE operations DROP COLUMN replace_images')
        upgraded=IdentityService(self.root,self.cfg,lambda _:self.client,lambda:self.now)
        self.assertEqual(upgraded.history()['history'][0]['id'],result['operation_id'])
        with upgraded.db() as db:
            self.assertIn('submitted',{row['name'] for row in db.execute('PRAGMA table_info(operations)')})

    def test_incomplete_is_distinct_from_unmatched_and_outside_root_excluded(self):
        self.client.items[0]['ProviderIds']={'Tmdb':'123'}
        self.assertEqual(self.service.listing()['counts']['unmatched'],0)
        self.assertEqual(len(self.service.listing('incomplete')['items']),1)
        self.client.items[0]['Path']=str(self.cfg)
        self.assertEqual(self.service.listing()['counts']['total'],0)
        self.client.items[0]['Path']=str(self.root/'outside.strm')
        Path(self.client.items[0]['Path']).write_text('/x.mkv')
        with self.assertRaises(IdentityError):self.service.item(self.client,control.read(self.cfg)[0],'9')

    def test_unknown_submit_result_is_not_false_success_and_can_recheck_warning(self):
        self.client.apply_error=True
        result=self.apply();operation=result['operation_id']
        self.now+=181
        self.assertEqual(self.service.operation(operation)['state'],'warning')
        self.client.items[0].update(Name='新·驯龙高手',ProviderIds={'Tmdb':'1087192'},Overview='完成',ImageTags={'Primary':'tag'})
        self.assertEqual(self.service.operation(operation)['state'],'completed')

    def test_parallel_candidate_for_same_item_is_blocked(self):
        first=self.search()['candidates'][0]['id'];second=self.search()['candidates'][0]['id']
        self.client.apply_error=True
        self.apply(first)
        with self.assertRaises(IdentityError):self.apply(second)
        self.assertEqual(len(self.service.history()['history']),1)

    def test_source_changed_during_verification_fails(self):
        operation=self.apply()['operation_id']
        self.file.write_text('/different.mkv')
        self.assertEqual(self.service.operation(operation)['state'],'failed')

    @unittest.skipIf(__import__('os').name=='nt','Linux kernel flock')
    def test_scan_and_identity_share_kernel_write_lock(self):
        import fcntl
        self.lock_patch.stop()
        path=self.root/'data/tasks/xstrm-write.flock';path.parent.mkdir(exist_ok=True)
        with path.open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(IdentityError):
                with self.service.write_lock():pass
        with self.service.write_lock():pass


class HintTests(unittest.TestCase):
    def test_noisy_movie_filename_and_collection_parent(self):
        result=hints('/电影/蝙蝠侠三部曲/蝙蝠侠：黑暗骑士崛起.The.Dark.Knight.Rises.2012.IMAX.UHD.Bluray.REMUX.strm')
        self.assertEqual(result['year'],2012)
        self.assertNotIn('三部曲',result['query'])
        self.assertNotIn('REMUX',result['query'])

    def test_folder_fallback_conflict_and_existing_id(self):
        result=hints('/电影/寒战 1994/2026.2160p.WEB-DL.strm')
        self.assertEqual(result['query'],'寒战');self.assertIsNone(result['year']);self.assertTrue(result['warnings'])
        self.assertEqual(hints('/电影/电影 (2025) {tmdb-123}/电影.strm')['tmdb_id'],'123')
        self.assertIn('28 Years Later',hints('/电影/惊变28年 HDR10+/28.Years.Later.2025.2160p.strm')['query'])
        self.assertEqual(hints('/电影/影片/A.Minecraft.Movie.2025.2160p.strm')['query'],'A Minecraft Movie')
        conflict=hints('/电影/影片 {tmdb-111}/影片 [tmdbid=222].strm')
        self.assertEqual(conflict['tmdb_id'],'');self.assertTrue(conflict['warnings'])

    def test_network_errors_do_not_return_upstream_secrets(self):
        client=EmbyClient({'emby':{'host':'http://emby','api_key':'secret'}})
        with mock.patch.object(client.opener,'open',side_effect=error.URLError('http://upstream/?token=secret')):
            with self.assertRaises(IdentityError) as exc:client.call('/Items')
        self.assertNotIn('secret',str(exc.exception))


if __name__=='__main__':unittest.main()
