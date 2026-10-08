import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pyfold import fold, unfold, FoldError
from pyfold.checking import check_pair, rebind
from pyfold.core import fingerprint
from pyfold.syntax import HEADER


def compile_view(view):
    return unfold(HEADER + '\n' + view)


class SyntaxV2(unittest.TestCase):
    def same(self, view, python):
        self.assertEqual(fingerprint(compile_view(view)), fingerprint(python))

    def test_indentation_independent(self):
        python = 'def f(x):\n    if x:\n        return 1\n    else:\n        return 2\n'
        for view in ['fun f(x) { if (x) { return 1 } else { return 2 } }',
                     'fun f(x) {\nif (x) {\n return 1\n} else {\n            return 2\n}\n}',
                     'fun f(x)\n{ if (x)\n{ return 1; }\nelse {return 2;} }']:
            with self.subTest(view=view):
                self.same(view, python)

    def test_interpolation_and_conditional(self):
        view = 'fun greet(name: str, excited: bool = false): str { val suffix = if (excited) "!" else "."; return "Hello, ${name}${suffix}" }'
        python = "def greet(name: str, excited: bool = False) -> str:\n suffix = '!' if excited else '.'\n return f'Hello, {name}{suffix}'\n"
        self.same(view, python)
        emitted, _ = fold(python)
        self.assertIn('${name}', emitted)
        self.assertNotIn('```', emitted)

    def test_nested_expressions(self):
        self.same('fun f(x) = call(if (x) a else b, (if (x) 1 else 2) + 3)',
                  'def f(x):\n return call(a if x else b, (1 if x else 2) + 3)')
        self.same('fun f(a,b) = if (a) (if (b) 1 else 2) else 3',
                  'def f(a,b):\n return (1 if b else 2) if a else 3')

    def test_collections_and_strings(self):
        self.same('fun f() { var x = {"}": [true, false, null]}; return (x, "if { && !", 8 // 3) }',
                  'def f():\n x = {"}": [True, False, None]}\n return (x, "if { && !", 8 // 3)')
        self.same('fun f(x) = "${x["key"]}"', "def f(x):\n return f'{x[\"key\"]}'")

    def test_loops_else_try_with(self):
        source = '''def f(items):
    for x in items:
        if x:
            continue
        else:
            break
    else:
        return None
    while items:
        items.pop()
    else:
        pass
    try:
        with open('a') as file:
            return file.read()
    except (OSError, ValueError) as error:
        raise RuntimeError('bad') from error
    else:
        return 2
    finally:
        cleanup()
'''
        view, metadata = fold(source)
        self.assertNotIn('```', view)
        self.assertIn('catch (error:', view)
        self.assertEqual(unfold(view, metadata), source)
        self.assertEqual(fingerprint(unfold(view)), fingerprint(source))

    def test_class_and_nested_functions(self):
        source = 'class C(Base, metaclass=Meta):\n def f(self):\n  def inner(x):\n   return x + 1\n  return inner(2)\n'
        view, metadata = fold(source)
        self.assertNotIn('```', view)
        self.assertEqual(unfold(view, metadata), source)

    def test_bindings(self):
        self.same('fun f() { val x = []; x.append(1); return x }',
                  'def f():\n x = []\n x.append(1)\n return x')
        for body in ['val x=1; x=2', 'val x=1; x+=1', 'val x=1; del x',
                     'val x=1; for (x in xs) {}', 'val x=1; val x=2',
                     'val x', 'val x=y=1', 'val x=1; import x',
                     'val x=1; fun inner() { nonlocal x; x=2 }']:
            with self.subTest(body=body), self.assertRaises((FoldError, SyntaxError)):
                compile_view('fun f() {' + body + '}')
        self.same('fun f() { var x=1; x=2; return x }',
                  'def f():\n x=1\n x=2\n return x')

    def test_operator_order(self):
        self.same('fun f(a,b,c) = !a == b || c && a',
                  'def f(a,b,c):\n return not a == b or c and a')

    def test_comprehension_alternatives(self):
        python = 'def names(users):\n return [u.name for u in users if u.active and u.name]'
        self.same('fun names(users) = [u.name for (u in users) if (u.active && u.name)]', python)
        self.same('fun names(users) = [u.name for u in users if (u.active && u.name)]', python)
        self.same('fun names(users) =\n    [u.name for (u in users) if (u.active && u.name)]', python)

    def test_new_runtime_behaviors(self):
        view = '''fun once(fetch, consume) { val v = fetch(); return consume(v, v) }
fun short(a, b) = a && b()
async fun resolve(x) = await x
fun retry(fetch) {
    for (attempt in range(3)) {
        try { return fetch() }
        catch (error: ValueError) { if (attempt == 2) { throw error } }
    }
}'''
        namespace = {}
        exec(compile_view(view), namespace)
        calls = []
        def fetch():
            calls.append(1)
            return object()
        self.assertTrue(namespace['once'](fetch, lambda a,b: a is b))
        self.assertEqual(len(calls), 1)
        self.assertEqual(namespace['short']([], fetch), [])
        self.assertEqual(len(calls), 1)
        def fail():
            calls.append(1)
            raise ValueError('failure')
        with self.assertRaisesRegex(ValueError, 'failure'):
            namespace['retry'](fail)
        self.assertEqual(len(calls), 4)

    def test_readme_example(self):
        import re
        readme = Path('README.md').read_text()
        sample = re.search(r'```text\n(.*?)\n```', readme, re.S)[1]
        python = unfold(sample)
        namespace = {}
        exec(python, namespace)
        self.assertEqual(namespace['greet']('Saswat', True), 'Hello, Saswat!')

    def test_failure_diagnostics(self):
        for view in ['fun f() {', 'fun f() = if (x) 1', 'fun f() { val x = }',
                     'fun f() = "${x"', 'fun f() = (1]', 'fun f() = 1 fun g() = 2',
                     'fun f() { try {} }']:
            with self.subTest(view=view), self.assertRaises((FoldError, SyntaxError)):
                compile_view(view)

    def test_determinism_and_legacy(self):
        source = 'def f(x):\n return not x\n'
        self.assertEqual(fold(source), fold(source))
        view, metadata = fold(source, legacy=True)
        self.assertTrue(view.startswith('fn '))
        self.assertEqual(unfold(view, metadata), source)
        source = 'import os\ndef f():\n return os.name\n'
        view, metadata = fold(source, legacy=True)
        self.assertEqual(unfold(view, metadata), source)

    def test_fallback(self):
        source = '@decorator\ndef f(x):\n return x\n'
        view, metadata = fold(source)
        self.assertIn('```python', view)
        self.assertEqual(unfold(view, metadata), source)


class PairChecks(unittest.TestCase):
    original = '# preserve this\r\ndef choose(x):\r\n\treturn 1 if x else 2 # choice\r\n'

    def test_reexpression_restores_exact_text(self):
        _, metadata = fold(self.original)
        edited = HEADER + '\nfun choose(x) { return if (x) 1 else 2 }\n'
        result = check_pair(edited, metadata, self.original)
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['exact_reconstruction'])
        rebound = rebind(edited, self.original)
        self.assertTrue(check_pair(edited, rebound, self.original)['ok'])

    def test_consistent_but_changed_is_not_equivalent(self):
        view, metadata = fold(self.original)
        edited = view.replace('1 else', '99 else')
        result = check_pair(edited, metadata, self.original)
        self.assertTrue(result['pair_consistent'])
        self.assertFalse(result['original_ast_matches'])
        self.assertFalse(result['ok'])
        with self.assertRaises(FoldError):
            rebind(edited, self.original)

    def test_both_halves_changed_independent_original(self):
        view, metadata = fold('def choose(x):\n return 99\n')
        self.assertFalse(check_pair(view, metadata, self.original)['ok'])

    def test_exact_text_is_separate(self):
        original = 'def f():\n return 1\n'
        differently_spelled = 'def f():\n    return 1\n'
        view, metadata = fold(original)
        result = check_pair(view, metadata, differently_spelled)
        self.assertTrue(result['original_ast_matches'])
        self.assertFalse(result['exact_reconstruction'])
        self.assertFalse(result['ok'])

    def test_cli_pair_and_rebind(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            (p/'original.py').write_bytes(self.original.encode())
            (p/'view.fold').write_text(HEADER + '\nfun choose(x) { return if (x) 1 else 2 }\n')
            def cli(*args):
                return subprocess.run([sys.executable, '-m', 'pyfold', *map(str,args)], text=True, capture_output=True)
            r = cli('rebind', p/'view.fold', '--against', p/'original.py', '-o', p/'map.json')
            self.assertEqual(r.returncode, 0, r.stderr)
            r = cli('check', p/'view.fold', '--map', p/'map.json', '--against', p/'original.py', '--json')
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(json.loads(r.stdout)['ok'])
            (p/'view.fold').write_text('fun choose(x) = 5')
            r = cli('check', p/'view.fold', '--map', p/'map.json', '--against', p/'original.py', '--json')
            self.assertEqual(r.returncode, 1)
            self.assertFalse(json.loads(r.stdout)['original_ast_matches'])
