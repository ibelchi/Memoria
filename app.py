"""Local-only entry point. Python 3.10+, no mandatory third-party dependencies."""
import argparse
import json
import logging
import os
from pathlib import Path
import sys
import threading
import urllib.request
import webbrowser
from catalog.core import Catalog
from catalog.server import LocalServer
from catalog.storage import read_pointer, write_pointer


def main():
    parser = argparse.ArgumentParser(description='Catàleg personal de vídeos, només en aquest ordinador')
    parser.add_argument('--demo', action='store_true', help='catàleg fictici separat')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--config', type=Path, help='configuració compartida de la ubicació del catàleg')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--import-json', type=Path, help='importar en una base buida i sortir')
    parser.add_argument('--restore', type=Path, help='restaurar còpia SQLite en una carpeta buida i sortir')
    args = parser.parse_args()
    project = Path(__file__).resolve().parent
    config_file = args.config or project/('runtime-demo-settings.json' if args.demo else 'runtime-settings.json')
    data = (args.data_dir or read_pointer(config_file, project/('runtime-demo' if args.demo else 'runtime-personal'))).resolve()
    data.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=data / 'app.log', level=logging.INFO, encoding='utf-8')
    if args.restore:
        import sqlite3
        destination = data / 'catalog.sqlite3'
        if destination.exists():
            parser.error('Restaura en una carpeta de dades buida; el catàleg actual no es modifica.')
        with sqlite3.connect(args.restore.resolve().as_uri() + '?mode=ro', uri=True) as source:
            if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                parser.error('La còpia està malmesa')
            if source.execute('SELECT version FROM schema_version').fetchone()[0] not in (1, 2, 3, 4):
                parser.error('Versió de còpia desconeguda')
            with sqlite3.connect(destination) as target:
                source.backup(target)
        print('Còpia restaurada. Les miniatures es regeneren en reexplorar.')
        return
    catalog = Catalog(data)
    if args.import_json:
        catalog.import_empty(json.loads(args.import_json.read_text(encoding='utf8')))
        print('Anotacions importades.')
        return
    if args.demo:
        catalog.seed_demo()
    try:
        server = LocalServer(catalog, args.port, config_file=config_file)
    except OSError:
        try:
            url = 'http://127.0.0.1:' + str(args.port)
            with urllib.request.urlopen(url + '/api/config', timeout=2) as response:
                config = json.load(response)
            if config.get('app') == 'cataleg-videos' and Path(config['data_dir']).resolve() == data.resolve():
                if not args.no_browser:
                    webbrowser.open(url)
                return
        except Exception:
            pass
        raise RuntimeError('El port està ocupat per una altra aplicació o un altre catàleg. Tanca’l o indica --port 8766.')
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(server.origin)).start()
    with catalog.db() as db:
        db.execute("UPDATE scans SET status='interrupted',message='Exploració interrompuda; torna a explorar.' WHERE status='running'")
    write_pointer(config_file, data)
    if sys.stdout is not None:
        print('Catàleg disponible a ' + server.origin, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.catalog.backup()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        logging.exception('No s’ha pogut iniciar')
        if sys.executable.lower().endswith('pythonw.exe'):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, str(error), 'Catàleg de vídeos', 16)
        else:
            raise
