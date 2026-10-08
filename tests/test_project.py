import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pyfold import FoldError
from pyfold.core import fingerprint
from pyfold.project import (PROJECT_HEADER, assemble, check_project, expand_project,
                            fold_project, fragments, rebind_project, write_tree)


def view(*sections):
    return PROJECT_HEADER + '\n' + '\n\n'.join(
        f'module {json.dumps(path)} part {part} {{\n{body}\n}}'
        for path, part, body in sections) + '\n'


class Projects(unittest.TestCase):
    sources = {
        'pkg/__init__.py': '# package\n',
        'pkg/users.py': '# header\r\nPREFIX = "user:"\r\ndef find_user(id):\r\n\treturn PREFIX + str(id)\r\n',
        'pkg/orders.py': 'from .users import find_user\n\ndef order(id):\n    return find_user(id)\n',
        'empty.py': '',
    }

    def reorganized(self):
        return {
            'concepts.fold': view(
                ('pkg/users.py', 10, 'fun find_user(id) = PREFIX + str(id)'),
                ('pkg/orders.py', 10, 'fun order(id) { return find_user(id) }')),
            'setup.fold': view(
                ('pkg/orders.py', 0, 'from .users import find_user'),
                ('pkg/users.py', 0, 'val PREFIX = "user:"'),
                ('pkg/__init__.py', 0, ''),
                ('empty.py', 0, '')),
        }

    def test_deterministic_baseline(self):
        views, metadata = fold_project(self.sources)
        self.assertEqual((views, metadata), fold_project(dict(reversed(list(self.sources.items())))))
        self.assertEqual(expand_project(views, metadata), self.sources)

    def test_many_to_many_exact_and_rebind(self):
        _, metadata = fold_project(self.sources)
        views = self.reorganized()
        self.assertTrue(check_project(views, metadata, self.sources)['ok'])
        self.assertEqual(expand_project(views, metadata), self.sources)
        rebound = rebind_project(views, self.sources)
        self.assertTrue(check_project(views, rebound, self.sources)['ok'])

    def test_filename_and_section_order_do_not_change_module_order(self):
        views = self.reorganized()
        renamed = {'z.fold': views['concepts.fold'], 'a.fold': views['setup.fold']}
        self.assertEqual(expand_project(views), expand_project(renamed))
        for path, code in expand_project(views).items():
            self.assertEqual(fingerprint(code), fingerprint(self.sources[path]))

    def test_missing_extra_and_renamed_module(self):
        _, metadata = fold_project(self.sources)
        for old, new in [('empty.py', 'extra.py'), ('pkg/users.py', 'pkg/renamed.py')]:
            views = {p: v.replace(old, new) for p,v in self.reorganized().items()}
            result = check_project(views, metadata, self.sources)
            self.assertFalse(result['ok'])
            self.assertFalse(result['module_set_matches_map'])
            self.assertFalse(result['original_file_set_matches'])
            with self.assertRaises(FoldError):
                expand_project(views, metadata)
        views = self.reorganized()
        original = dict(self.sources, missing_original_module='')
        self.assertFalse(check_project(views, metadata, original)['ok'])

    def test_duplicate_and_unsafe_paths(self):
        cases = [
            {'a.fold': view(('a.py', 0, '')), 'b.fold': view(('a.py', 0, ''))},
            {'a.fold': view(('a.py', 0, ''), ('A.py', 1, ''))},
            {'a.fold': view(('a.py', 0, ''), ('a.py/b.py', 1, ''))},
        ]
        for path in ('../escape.py', '/abs.py', 'a/../b.py', 'C:/x.py', 'a\\b.py', './x.py', 'x.txt'):
            cases.append({'a.fold': view((path, 0, ''))})
        for views in cases:
            with self.subTest(views=views), self.assertRaises(FoldError):
                assemble(views)

    def test_fragment_must_be_complete(self):
        with self.assertRaises(FoldError):
            assemble({'x.fold': view(('a.py', 0, 'fun f() {'))})

    def test_future_import_and_cross_part_val(self):
        source = {'a.py': 'from __future__ import annotations\ndef f(x: Unknown):\n return x\n'}
        views, metadata = fold_project(source)
        self.assertTrue(check_project(views, metadata, source)['ok'])
        with self.assertRaises(FoldError):
            assemble({'a.fold': view(('a.py', 0, 'val x = 1'), ('a.py', 10, 'x = 2'))})

    def test_order_and_semantic_changes_are_detected(self):
        source = {'a.py': 'x=1\nx=2\n'}
        _, metadata = fold_project(source)
        reordered = {'a.fold': view(('a.py', 20, 'var x=1'), ('a.py', 10, 'var x=2'))}
        result = check_project(reordered, metadata, source)
        self.assertFalse(result['ok'])
        self.assertFalse(result['modules']['a.py']['original_ast_matches'])
        with self.assertRaises(FoldError):
            rebind_project(reordered, source)

    def test_raw_blocks(self):
        sources = {'a.py': '@decorator\ndef f():\n return {"}": "module"}\n'}
        views, metadata = fold_project(sources)
        self.assertEqual(expand_project(views, metadata), sources)

    def test_cli_full_workflow_and_runtime_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_tree(root/'original', self.sources)
            def cli(*args):
                return subprocess.run([sys.executable, '-m', 'pyfold', 'project', *map(str,args)], capture_output=True, text=True)
            result = cli('fold', root/'original', '-o', root/'baseline')
            self.assertEqual(result.returncode, 0, result.stderr)
            write_tree(root/'views', self.reorganized())
            result = cli('rebind', root/'views', '--against', root/'original', '-o', root/'map.json')
            self.assertEqual(result.returncode, 0, result.stderr)
            result = cli('check', root/'views', '--map', root/'map.json', '--against', root/'original', '--json')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(json.loads(result.stdout)['ok'])
            for dest, args in [('canonical', []), ('restored', ['--map', root/'map.json'])]:
                result = cli('unfold', root/'views', *args, '-o', root/dest)
                self.assertEqual(result.returncode, 0, result.stderr)
            for path, source in self.sources.items():
                self.assertEqual((root/'restored'/path).read_bytes(), source.encode())
            result = subprocess.run([sys.executable, '-c', 'from pkg.orders import order; print(order(7))'], cwd=root/'canonical', capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'user:7')
            # Refuse stale output rather than silently retain deleted modules.
            self.assertNotEqual(cli('unfold', root/'views', '-o', root/'canonical').returncode, 0)

    def test_output_input_separation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(FoldError):
                write_tree(root/'input'/'output', {'x.py': ''}, [root/'input'])
            with self.assertRaises(FoldError):
                write_tree(root, {'../x.py': ''})
