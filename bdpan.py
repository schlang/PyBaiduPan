import json
import os
import re
from exceptions import *
from DecryptLogin.login import Login
from config import config
import logging
from itertools import count
import pickle
import shutil
from hashlib import md5
from functools import partial
from base64 import b64encode
from datetime import datetime


class BdPan:
    URL = {'PCS': 'https://pcs.baidu.com/rest/2.0/pcs/', 'XPAN': 'https://pan.baidu.com/rest/2.0/xpan/'}
    LIST_LIMIT = 5000
    UPLOAD_SIZE = 4 << 20

    def __init__(self):
        self.bd_get = partial(self._bd_request, 'get')
        self.bd_post = partial(self._bd_request, 'post')
        self.act = self.__getattribute__(config['action'])
        self._get_logger()
        self.session = None
        self.bdstoken = None

    def _load_session(self, s_file):
        try:
            with open(s_file, 'rb') as f:
                self.session = pickle.load(f)
        except:
            pass

    def _save_session(self, s_file):
        with open(s_file, 'wb') as f:
            pickle.dump(self.session, f)

    @staticmethod
    def sizeof_fmt(num):
        for unit in ['B', 'K', 'M', 'G', 'T', 'P', 'E', 'Z']:
            if abs(num) < 1024.0:
                return "%3.1f%s" % (num, unit)
            num /= 1024.0
        return "%.1f%s" % (num, 'Y')

    @staticmethod
    def _get_bdstoken(html):
        return re.search("'bdstoken', *'([0-9a-f]+)'", html).group(1)

    @staticmethod
    def _compare_mtime(path, file_info, op):
        return os.path.getmtime(path).__getattribute__(f'__{op}__')(file_info['local_mtime'])

    def _get_logger(self):
        self.logger = logging.getLogger('BdPan')
        self.logger.setLevel(logging.INFO)
        ch = logging.FileHandler(config["log_file"]) if config.get("log_file") else logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s: %(message)s'))
        self.logger.addHandler(ch)

    def _bd_request(self, _method, method, path='file', api='XPAN', params={}, **kwargs):
        params['app_id'] = config['app_id']
        params['method'] = method
        if api == 'XPAN' and self.bdstoken:
            params['bdstoken'] = self.bdstoken
            params['logid'] = b64encode(self.session.cookies['BAIDUID'].encode('ascii'))
        return self.session.request(_method, BdPan.URL[api] + path, params=params, **kwargs)

    @log_error
    def login(self, username=None, password=None, s_file=None):
        username, password = username or config['username'], password or config['password']
        s_file = s_file or config['session']
        self._load_session(s_file)
        if self.session is None or self.bd_get('uinfo', 'nas').json()["errno"] != 0:
            infos_return, self.session = Login().baidupan(username, password, 'pc')
            if infos_return['errInfo']['no'] != '0':
                raise RuntimeError(infos_return)
        self._save_session(s_file)
        res = self.session.get('https://pan.baidu.com/disk/home')
        self.bdstoken = self._get_bdstoken(res.text)

    @log_error
    def logout(self, s_file=None):
        s_file = s_file or config['session']
        try:
            os.remove(s_file)
        except FileNotFoundError:
            pass
        self.session = None
        self.bdstoken = None

    def download_file(self, file_info, f_path, overwrite='none'):
        bd_path = file_info['path']
        f_path = os.path.join(f_path, os.path.split(bd_path)[1]) if os.path.isdir(f_path) else f_path
        if os.path.exists(f_path) and (overwrite == 'none'
                                       or (overwrite == 'mtime' and self._compare_mtime(f_path, file_info, 'ge'))):
            return
        self.logger.info(f'download {bd_path} to {f_path}')
        headers = {}
        if os.path.exists(f_path + '.part'):
            headers['Range'] = 'bytes=%d-' % os.path.getsize(f_path + '.part')
        with self.bd_get('download', api='PCS', params={'path': bd_path}, headers=headers, stream=True) as r:
            if r.status_code >= 400:
                _ = r.content
                r.raise_for_status()
            with open(f_path + '.part', 'ab') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        shutil.move(f_path + '.part', f_path)
        # there is no simple way to modify ctime. so I decide to leave it there.
        os.utime(f_path, (file_info['local_mtime'], file_info['local_mtime']))

    @covert_http_error
    def meta(self, path):
        res = self.bd_get('meta', api='PCS', params={'path': path})
        res.raise_for_status()
        return res.json()['list'][0]

    def _list(self, path, known_dir=False):
        if not known_dir:
            ret = [self.meta(path)]
        if known_dir or ret[0]['isdir'] == 1:
            ret = []
            for i in count(step=BdPan.LIST_LIMIT):
                res = raise_for_errno(self.bd_get('list', params={'dir': path, 'limit': BdPan.LIST_LIMIT, 'start': i}))
                ret += res['list']
                if len(res['list']) < BdPan.LIST_LIMIT:
                    break
        return ret

    @log_error
    def list(self, path=None):
        path = path or config['pan_path']
        for i in self._list(path):
            print(['F', 'D'][i['isdir']], '%6s' % self.sizeof_fmt(i['size']),
                  datetime.fromtimestamp(i['local_mtime']).strftime('%Y-%m-%dT%H:%M:%S'), os.path.split(i['path'])[1])

    def _download(self, bd_path, l_path, known_dir=False, overwrite='none', delete_extra=False):
        f_info = self._list(bd_path, known_dir)
        for i in f_info:
            if i['isdir']:
                local_dir = os.path.join(l_path, os.path.split(i['path'])[1])
                os.makedirs(local_dir, exist_ok=True)
                self._download(i['path'], local_dir, True, overwrite, delete_extra)
            else:
                self.download_file(i, l_path, overwrite)
        if delete_extra and os.path.isdir(l_path):
            f_name = [os.path.split(i['path'])[1] for i in f_info]
            for f in os.listdir(l_path):
                if f not in f_name:
                    try:
                        shutil.rmtree(os.path.join(l_path, f))
                    except NotADirectoryError:
                        os.remove(os.path.join(l_path, f))
                    self.logger.info(f'delete extra: {os.path.join(l_path, f)}')

    @log_error
    def download(self, src=None, dst=None, overwrite=None, delete_extra=None):
        src = src or config['pan_path']
        dst = dst or config['local_path']
        overwrite = overwrite or config['overwrite']
        delete_extra = delete_extra or config['delete_extra']
        if self.meta(src)['isdir'] == 1:
            os.makedirs(dst, exist_ok=True)
        self._download(src, dst, overwrite=overwrite, delete_extra=delete_extra)

    @staticmethod
    def file_slice(file, size=UPLOAD_SIZE):
        if os.path.getsize(file) == 0:
            yield b''
            return
        with open(file, 'rb') as f:
            for c in iter(partial(f.read, size), b''):
                yield c

    def upload_file(self, bd_path, f_path, overwrite='none', meta=None):
        if meta is not None and (
                overwrite == 'none' or (overwrite == 'mtime' and self._compare_mtime(f_path, meta, 'le'))):
            return
        self.logger.info(f'upload {f_path} to {bd_path}')
        content_md5, block_list = md5(), []
        for x in self.file_slice(f_path):
            content_md5.update(x)
            block_list.append(md5(x).hexdigest())
        content_md5, block_list = content_md5.hexdigest(), json.dumps(block_list)
        slice_md5 = md5(next(self.file_slice(f_path, 256 << 10))).hexdigest()
        data = {'path': bd_path, 'size': os.path.getsize(f_path), 'isdir': "0", 'autoinit': 1, 'block_list': block_list,
                'rtype': 0 if overwrite == 'none' else 3, 'content-md5': content_md5, "slice-md5": slice_md5,
                'local_ctime': round(os.path.getctime(f_path)), 'local_mtime': round(os.path.getmtime(f_path))}
        res = self.bd_post('precreate', data=data)
        res = raise_for_errno(res)
        if res['return_type'] == 2:  # rapid upload
            return res['info']
        params = {'type': 'tmpfile', 'path': bd_path, 'uploadid': res['uploadid']}
        for i, x in enumerate(self.file_slice(f_path)):
            params['partseq'] = i
            raise_for_errno(self.bd_post('upload', 'superfile2', api='PCS', params=params, files={'file': x}))
        fields = ('path', 'size', 'isdir', 'block_list', 'rtype', 'local_ctime', 'local_mtime')
        data = {k: v for k, v in data.items() if k in fields}
        data['uploadid'] = params['uploadid']
        res = self.bd_post('create', data=data)
        return raise_for_errno(res)

    def makedir(self, path):
        data = {'path': path, 'size': 0, 'isdir': "1", 'block_list': '[]', 'rtype': 0}
        res = self.bd_post('create', data=data)
        if res.json()['errno'] != -8:  # dir already exist
            raise_for_errno(res)

    def remove(self, *path):
        if len(path) == 0:
            return
        self.logger.info(f'remove: {path}')
        raise_for_errno(self.bd_post('filemanager', params={'opera': 'delete', 'async': 0, 'onnest': 'fail'},
                                     data={'filelist': json.dumps(path)}))

    @log_error
    def upload(self, src=None, dst=None, overwrite=None, delete_extra=None):
        src = src or config['local_path']
        dst = dst or config['pan_path']
        overwrite = overwrite or config['overwrite']
        delete_extra = delete_extra or config['delete_extra']
        meta = mute_error(self.meta)(dst)
        if os.path.isfile(src):
            if meta is not None and meta['isdir'] == 1:
                dst = os.path.join(dst, os.path.split(src)[1]).replace('\\', '/')
                meta = mute_error(self.meta)(dst)
            self.upload_file(dst, src, overwrite, meta)
        elif os.path.isdir(src):
            if meta is not None and meta['isdir'] == 0:
                raise RuntimeError('upload: unable to upload a directory to a file.')
            for root, dirs, files in os.walk(src):
                r_path = os.path.relpath(root, src)
                bd_path = os.path.join(dst, r_path if r_path != '.' else '').replace('\\', '/')
                self.makedir(bd_path)
                f_info = {f: None for f in files}
                if overwrite != 'force':
                    bd_dir = self._list(bd_path, True)
                    for x in bd_dir:
                        k = os.path.split(x['path'])[1]
                        if k in f_info:
                            f_info[k] = x
                for f, m in f_info.items():
                    self.upload_file(os.path.join(bd_path, f).replace('\\', '/'), os.path.join(root, f), overwrite, m)
                if delete_extra:
                    if overwrite == 'force':
                        bd_dir = self._list(bd_path, True)
                    d_f = [x['path'] for x in bd_dir if os.path.split(x['path'])[1] not in files + dirs]
                    self.remove(*d_f)
        else:
            raise RuntimeError('upload: local_path must be a file or a directory.')

    def sync(self, pan_path=None, local_path=None, overwrite=None):
        local_path = local_path or config['local_path']
        pan_path = pan_path or config['pan_path']
        overwrite = overwrite or config['overwrite']
        self.download(pan_path, local_path, overwrite, False)
        self.upload(local_path, pan_path, overwrite, False)


@mute_error
def main():
    pan = BdPan()
    pan.login()
    pan.act()


if __name__ == '__main__':
    main()
