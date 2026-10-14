"""Catalog bootstrap, offline recovery and actual Store icon eligibility, without GI."""
import ast
from contextlib import redirect_stdout
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import time
from types import MethodType, SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import store_catalog as Catalog

loader = importlib.machinery.SourceFileLoader('catalog_refresh', str(ROOT / 'iso/src/polder-store-catalog-refresh'))
spec = importlib.util.spec_from_loader(loader.name, loader)
Refresh = importlib.util.module_from_spec(spec)
loader.exec_module(Refresh)

KINDS = SimpleNamespace(CACHED=1, LOCAL=2, REMOTE=3, STOCK=4)


class Icon:
    def __init__(self, kind, filename=None, name=None, width=64, url=None):
        self.kind, self.filename, self.name, self.width = kind, filename, name, width
        self.url = url
    def get_kind(self): return self.kind
    def get_filename(self): return self.filename
    def get_name(self): return self.name
    def get_url(self): return self.url
    def get_width(self): return self.width


class Component:
    def __init__(self, identifier, kind='desktop', package='real-app', icons=()):
        self.identifier, self.kind, self.package, self.icons = identifier, kind, package, icons
    def get_id(self): return self.identifier
    def get_kind(self): return self.kind
    def get_name(self): return self.identifier
    def get_summary(self): return ''
    def get_bundle(self, kind): return None
    def get_pkgname(self): return self.package
    def get_categories(self): return []
    def get_icons(self): return self.icons


def store_nodes():
    tree = ast.parse((HERE / 'store.py').read_text(encoding='utf-8'))
    app = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'App')
    store = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Store')
    icon = next(node for node in store.body if isinstance(node, ast.FunctionDef) and node.name == 'set_icon')
    loaded = next(node for node in store.body if isinstance(node, ast.FunctionDef) and node.name == 'catalog_loaded')
    load = next(node for node in store.body if isinstance(node, ast.FunctionDef) and node.name == 'load')
    watch = next(node for node in store.body if isinstance(node, ast.FunctionDef) and node.name == 'watch_catalog')
    namespace = {'AS': SimpleNamespace(BundleKind=SimpleNamespace(FLATPAK='flatpak'), IconKind=KINDS),
                 'Catalog': Catalog, 'Gtk': SimpleNamespace(IconSize=SimpleNamespace(DIALOG=1)),
                 'POOL': mock.Mock(), 'time': time, 'threading': mock.Mock()}
    exec(compile(ast.Module(body=[app, icon, loaded, load, watch], type_ignores=[]), str(HERE / 'store.py'), 'exec'), namespace)
    return namespace


class CatalogTests(unittest.TestCase):
    def test_real_apps_remain_visible_without_icons(self):
        app_type = store_nodes()['App']
        components = [Component('Visible'), Component('Visible'), Component('Library', kind='library'),
                      Component('NoInstaller', package=None)]
        apps = Catalog.collect_apps(components, 'desktop', lambda c: app_type(c, []))
        self.assertEqual([app.id for app in apps], ['Visible'])
        self.assertFalse(apps[0].has_icon())

    def test_actual_store_uses_stock_or_generic_placeholder(self):
        namespace = store_nodes()
        for icons, expected in (([], 'application-x-executable'), ([Icon(KINDS.STOCK, name='accessories-text-editor')], 'accessories-text-editor')):
            app = namespace['App'](Component('Visible', icons=icons), [])
            image = mock.Mock()
            namespace['set_icon'](None, image, app, 48)
            image.set_from_icon_name.assert_called_once_with(expected, 1)
            namespace['POOL'].submit.assert_not_called()

    def test_icon_directories_appear_after_initial_catalog_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(Catalog.icon_directories([str(root)]), [])
            directory = root / 'debian-trixie-main/64x64'
            directory.mkdir(parents=True)
            icon = directory / 'editor.png'; icon.write_bytes(b'icon')
            local, remote, stock = Catalog.resolve_icons([Icon(KINDS.CACHED, filename='editor.png')], KINDS, Catalog.icon_directories([str(root)]))
            self.assertEqual(local, str(icon)); self.assertIsNone(remote)

    def test_remote_icon_has_a_real_url_and_unsafe_scheme_is_ignored(self):
        self.assertEqual(Catalog.resolve_icons([Icon(KINDS.REMOTE, name='https://example.org/icon.png')], KINDS, [])[1], 'https://example.org/icon.png')
        self.assertIsNone(Catalog.resolve_icons([Icon(KINDS.REMOTE, name='file:///etc/passwd')], KINDS, [])[1])

    def test_remote_icon_name_is_a_basename_and_url_is_separate(self):
        icon = Icon(KINDS.REMOTE, name='icon.png', url='https://example.invalid/icon.png')
        self.assertEqual(Catalog.resolve_icons([icon], KINDS, [])[1], 'https://example.invalid/icon.png')
        with tempfile.TemporaryDirectory() as tmp:
            cached = Path(tmp) / 'icon.png'; cached.write_bytes(b'icon')
            local, remote, stock = Catalog.resolve_icons([icon], KINDS, [tmp])
            self.assertEqual(local, str(cached)); self.assertIsNone(remote)

    def test_clean_catalog_retries_without_terminal_instructions(self):
        clean = Catalog.read_status('/nonexistent/polder-store-test-status')
        self.assertTrue(Catalog.should_refresh(clean, 0, 0, now=1000))
        self.assertIn('automatisch', Catalog.status_message(clean, 0))
        self.assertIn('opgeslagen', Catalog.status_message({'phase': 'retry'}, 42))
        self.assertIn('automatisch', Catalog.status_message({'phase': 'retry'}, 0))

    def test_offline_busy_and_in_progress_attempts_are_bounded(self):
        for phase in ('retry', 'refreshing'):
            self.assertFalse(Catalog.should_refresh({'phase': phase, 'updated_at': 900}, 0, 0, now=1000))
        self.assertTrue(Catalog.should_refresh({'phase': 'retry', 'updated_at': 100}, 0, 0, now=1000))
        self.assertTrue(Catalog.should_refresh({'phase': 'refreshing', 'updated_at': 100}, 0, 0, now=1000))
        self.assertFalse(Catalog.should_refresh({'phase': 'retry', 'updated_at': 100}, 0, 990, now=1000))
        self.assertIn('pakketbeheerder', Catalog.status_message({'phase': 'retry', 'reason': 'busy'}, 0))

    def test_fresh_cached_catalog_needs_no_network(self):
        ready = {'phase': 'ready', 'updated_at': 990}
        self.assertFalse(Catalog.should_refresh(ready, 100, 0, now=1000))
        self.assertTrue(Catalog.should_refresh(ready, 100, 0, now=1000 + Catalog.REFRESH_SECONDS))

    def test_corrupt_status_is_recoverable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'status.json'; path.write_text('{')
            self.assertEqual(Catalog.read_status(path)['phase'], 'not_started')
            path.write_text(json.dumps({'schema': 1, 'phase': 'ready', 'updated_at': None}))
            self.assertEqual(Catalog.read_status(path)['phase'], 'not_started')

    def test_actual_store_retains_cached_apps_on_empty_or_failed_reload(self):
        loaded = store_nodes()['catalog_loaded']
        for error in (None, RuntimeError('offline')):
            previous_pool = object()
            store = SimpleNamespace(closed=False, apps=['cached'], pool=previous_pool,
                                    catalog_loading=True, catalog_reload_pending=False,
                                    catalog_error=None, update_catalog_status=mock.Mock())
            loaded(store, object(), [], error)
            self.assertEqual(store.apps, ['cached']); self.assertIs(store.pool, previous_pool)
            self.assertFalse(store.catalog_loading); self.assertIsNotNone(store.catalog_error)

    def test_refresh_arriving_during_load_queues_reload_after_completion(self):
        for error in (None, RuntimeError('offline')):
            namespace = store_nodes()
            store = SimpleNamespace(closed=False, apps=[], pool=None, byid={}, category=None,
                                    catalog_loading=True, catalog_reload_pending=False,
                                    catalog_seen=('old',), catalog_last_load=0,
                                    catalog_status={'phase': 'refreshing', 'updated_at': 1},
                                    catalog_last_request=0, catalog_error=None,
                                    update_catalog_status=mock.Mock(), request_catalog_refresh=mock.Mock(),
                                    show_home=mock.Mock(), stack=mock.Mock(), search=mock.Mock())
            store.stack.get_visible_child_name.return_value = 'loading'
            store.search.get_text.return_value = ''
            store.load = MethodType(namespace['load'], store)
            with mock.patch.object(Catalog, 'read_status', return_value={'phase': 'ready', 'updated_at': 2}), mock.patch.object(Catalog, 'catalog_signature', return_value=('new',)), mock.patch.object(Catalog, 'should_refresh', return_value=False):
                namespace['watch_catalog'](store)
                self.assertTrue(store.catalog_reload_pending)
                namespace['threading'].Thread.assert_not_called()
                namespace['catalog_loaded'](store, object(), [], error)
            namespace['threading'].Thread.assert_called_once()
            namespace['threading'].Thread.return_value.start.assert_called_once()
            self.assertFalse(store.catalog_reload_pending)
            self.assertTrue(store.catalog_loading)


class RefreshTests(unittest.TestCase):
    def test_success_publishes_ready_and_fixed_metadata_commands(self):
        published, commands = [], []
        def run(argv, timeout):
            commands.append((argv, timeout)); return True, None
        with redirect_stdout(io.StringIO()):
            self.assertEqual(Refresh.refresh(run, published.append), 0)
        self.assertEqual(published[-1]['phase'], 'ready')
        self.assertEqual(len(commands), 4)
        self.assertEqual(commands[0][0][-1], 'update')
        self.assertIn('--appstream', commands[-1][0])
        self.assertNotIn('--arch', commands[-1][0])
        self.assertFalse(any('install' in argv or 'upgrade' in argv for argv, timeout in commands))

    def test_offline_still_reads_cached_appstream_and_retries(self):
        published, commands = [], []
        def run(argv, timeout):
            commands.append(argv)
            return (True, None) if argv[0] == 'appstreamcli' else (False, 'offline')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(Refresh.refresh(run, published.append), 75)
        self.assertEqual(len(commands), 4)
        self.assertEqual(published[-1]['phase'], 'retry')
        self.assertEqual(published[-1]['sources']['appstream'], 'ready')

    def test_apt_busy_publishes_a_useful_retry_reason(self):
        published = []
        with redirect_stdout(io.StringIO()):
            result = Refresh.refresh(lambda argv, timeout: (False, 'busy') if argv[0] == 'apt-get' else (True, None), published.append)
        self.assertEqual(result, 75); self.assertEqual(published[-1]['reason'], 'busy')

    def test_atomic_status_is_public_but_no_raw_command_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            Refresh.write_status({'phase': 'ready'}, Path(tmp))
            path = Path(tmp) / 'status.json'
            status = json.loads(path.read_text())
            self.assertEqual(status['schema'], 1)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
            self.assertEqual(list(Path(tmp).glob('.status-*')), [])

    def test_command_timeout_terminates_its_process_group(self):
        self.assertEqual(Refresh.run_command((sys.executable, '-c', 'import time; time.sleep(30)'), 0.05), (False, 'offline'))

    def test_no_arguments_and_nonblocking_lock(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(Refresh, 'RUNTIME_DIR', Path(tmp)), mock.patch.object(Refresh.os, 'geteuid', return_value=0):
            lock = open(Path(tmp) / 'refresh.lock', 'w')
            Refresh.fcntl.flock(lock, Refresh.fcntl.LOCK_EX | Refresh.fcntl.LOCK_NB)
            with mock.patch.object(Refresh.sys, 'argv', ['refresh']), mock.patch.object(Refresh, 'refresh') as run, redirect_stdout(io.StringIO()):
                self.assertEqual(Refresh.main(), 75); run.assert_not_called()
            lock.close()
            with mock.patch.object(Refresh.sys, 'argv', ['refresh', '--arbitrary-command']), mock.patch.object(Refresh, 'refresh') as run, redirect_stdout(io.StringIO()), mock.patch('sys.stderr', io.StringIO()):
                self.assertEqual(Refresh.main(), 2); run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
