"""Fill missing metadata defaults in the test library and request a refresh.

Run inside the admin container. Existing nonempty provider settings are preserved.
"""
import argparse
import json
import os
from pathlib import Path
from urllib import request

import yaml


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--library', default='XSTRM-Test')
    parser.add_argument('--tmdb-only', action='store_true', help='Use TMDB for movie metadata and images')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cfg = yaml.safe_load((root / 'config/strm-sync.yaml').read_text())
    base = cfg['emby']['host'].rstrip('/') + '/emby'
    headers = {'X-Emby-Token': cfg['emby']['api_key'], 'Content-Type': 'application/json'}

    def api(path, data=None):
        req = request.Request(base + path, headers=headers,
                              data=json.dumps(data).encode() if data is not None else None)
        with request.urlopen(req, timeout=30) as response:
            raw = response.read()
        return json.loads(raw) if raw else None

    libraries = api('/Library/VirtualFolders')
    library = next(x for x in libraries if x['Name'] == args.library)
    options = library['LibraryOptions']
    backup = root / 'data' / 'metadata-library-before.json'
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(library, stream)
    available = api('/Libraries/AvailableOptions?LibraryContentType=movies&IsNewLibrary=false')
    if not options.get('TypeOptions'):
        options['TypeOptions'] = available['DefaultLibraryOptions']['TypeOptions']
    if args.tmdb_only:
        for type_options in options['TypeOptions']:
            if type_options.get('Type') == 'Movie':
                for name in ('MetadataFetchers', 'MetadataFetcherOrder', 'ImageFetchers', 'ImageFetcherOrder'):
                    type_options[name] = ['TheMovieDb']
    for name, value in [('PreferredMetadataLanguage', 'zh'), ('PreferredImageLanguage', 'zh'),
                        ('MetadataCountryCode', 'CN')]:
        if not options.get(name):
            options[name] = value
    options['DownloadImagesInAdvance'] = True
    api('/Library/VirtualFolders/LibraryOptions', {'Id': library['ItemId'], 'LibraryOptions': options})
    for item in api('/Items?ParentId=' + library['ItemId'] + '&Recursive=true&IncludeItemTypes=Movie,Video')['Items']:
        api('/Items/' + item['Id'] + '/Refresh?Recursive=false&MetadataRefreshMode=FullRefresh&ImageRefreshMode=FullRefresh&ReplaceAllMetadata=false&ReplaceAllImages=false', {})
    print('Missing provider defaults configured; metadata refresh requested.')


if __name__ == '__main__':
    main()
