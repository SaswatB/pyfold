import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pyfold import FoldError, fold, unfold
from pyfold.core import digest, fingerprint


class RoundTrips(unittest.TestCase):
    def check_source(self, source):
        view, metadata = fold(source)
        metadata = json.loads(json.dumps(metadata))
        self.assertEqual(unfold(view, metadata), source)
        self.assertEqual(fingerprint(unfold(view)), fingerprint(source))
        return view, metadata

    def test_source_fixtures(self):
        sources = [
            "", "# only a comment\n", "\n\n", "x=1; y=2 # inline\n",
            "# café\r\ndef f(x):\r\n\treturn x + 1\r\n# tail",
            "def f():\n    return\n", "x = 1", "x = 1\r\ny = 2\r\n",
            "@decorator(1)\ndef f(x):\n    return x\n",
            "def f(x):\n    if x:\n        return 1\n    return 2\n",
            'def f():\n    """A docstring."""\n    return "=> {}"\n',
            "async def f(x):\n    return await x\n",
            'text = """hello\n```\nworld"""\n',
            "def f(x: dict[str, int] = {'a': 1}, /, *, y=2) -> int:\n    return x['a'] + y\n",
            "from __future__ import annotations\ndef f(x: Unknown):\n    return x\n",
            "def f(x):\n    yield x\n",
            "def f():\n    return 1\ndef f():\n    return 2\n",
        ]
        for source in sources:
            with self.subTest(source=source):
                self.check_source(source)

    def test_repository_sources(self):
        for path in Path("pyfold").glob("*.py"):
            with self.subTest(path=path):
                self.check_source(path.read_text())

    def test_compact_functions(self):
        view, _ = self.check_source("def add(a, b):\n    return a + b\n")
        self.assertEqual(view, "#!pyfold 2\nfun add(a, b) = a + b\n")

    def test_edit_preserves_other_function(self):
        original = "def a(x):\n    return x + 1\n\n# exact\ndef b( y ):\n\treturn y*2 # keep\n"
        view, metadata = fold(original)
        output = unfold(view.replace("x + 1", "x + 3"), metadata)
        self.assertIn("# exact\ndef b( y ):\n\treturn y*2 # keep\n", output)
        namespace = {}
        exec(output, namespace)
        self.assertEqual(namespace["a"](4), 7)

    def test_standalone_evaluate_once(self):
        view = "fn once(fetch, consume) {\n let value = fetch()\n => consume(value, value)\n}\n"
        namespace = {}
        exec(unfold(view), namespace)
        calls = []
        def fetch():
            calls.append(1)
            return object()
        self.assertTrue(namespace["once"](fetch, lambda a, b: a is b))
        self.assertEqual(calls, [1])

    def test_default_evaluated_at_definition(self):
        namespace = {"calls": []}
        exec(unfold("fn f(x=calls.append(1)) => x\n"), namespace)
        namespace["f"]()
        namespace["f"]()
        self.assertEqual(namespace["calls"], [1])

    def test_python_values(self):
        namespace = {}
        exec(unfold("fn f(x) => (bool(x), 2 ** 100, -7 // 3)\n"), namespace)
        self.assertEqual(namespace["f"]([]), (False, 2**100, -3))

    def test_stale_map_does_not_override_edit(self):
        view, metadata = fold("def f():\n    return 1\n")
        self.assertIn("return 2", unfold(view.replace("= 1", "= 2"), metadata))

    def test_tampered_source(self):
        view, metadata = fold("def f():\n    return 1\n")
        metadata["units"][0]["source"] = "def f():\n    return 999\n"
        with self.assertRaises(FoldError):
            unfold(view, metadata)
        metadata["source_sha256"] = digest(metadata["units"][0]["source"])
        with self.assertRaises(FoldError):
            unfold(view, metadata)

    def test_reorder_delete_add(self):
        source = "def a():\n return 1\ndef b():\n return 2\n"
        view, metadata = fold(source)
        edited = "fn b() => 2\n\nfn c() => 3\n"
        output = unfold(edited, metadata)
        self.assertEqual(fingerprint(output), fingerprint(unfold(edited)))
        self.assertNotIn("def a", output)

    def test_invalid_syntax(self):
        for view in ["fn f() =>", "fn f() {", "```python\nx = 1",
                     "fn f() => 1; print(2)", "fn f() {\nlet return 1\n}", "var ="]:
            with self.subTest(view=view), self.assertRaises((FoldError, SyntaxError)):
                unfold(view)

    def test_invalid_python_program(self):
        with self.assertRaises(FoldError):
            fold("return 1\n")

    def test_malformed_map(self):
        for metadata in ([], {"version": 2}, {"version": 1, "units": [4]}):
            with self.subTest(metadata=metadata), self.assertRaises(FoldError):
                unfold("fn f() => 1\n", metadata)

    def test_string_delimiters(self):
        self.check_source('def f(x="=>", y="{"):\n    return {"}": x, "=>": y}\n')

    def test_cli_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            original = b"# hi\r\ndef f(x):\r\n\treturn x+1"
            (p / "a.py").write_bytes(original)
            def cli(*args):
                subprocess.run([sys.executable, "-m", "pyfold", *map(str, args)], check=True, capture_output=True)
            cli("fold", p / "a.py", "-o", p / "a.fold")
            cli("unfold", p / "a.fold", "--map", p / "a.fold.map.json", "-o", p / "b.py")
            self.assertEqual((p / "b.py").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
