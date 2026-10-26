"""Keep executable workshop examples compatible and final copies in sync."""
from __future__ import annotations

import ast
import os
import re
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

PLAYER_DIR = Path(__file__).resolve().parents[1]
ROOT = PLAYER_DIR.parents[2]
sys.path.insert(0, str(PLAYER_DIR))

PYTHON_BLOCK = re.compile(r"^```python[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
CANONICAL_COPIES = {
    "08_use_the_note_reader_in_the_game.md": "agent.py",
    "08_read_the_secret_note.md": "agent_note_reader.py",
    "05_add_session_logging.md": "log.py",
    "06_test_agent42_transport_specialist.md": "agent_agent42.py",
    "07_test_the_city_guide_agent.md": "agent_city_guide.py",
}


class WorkshopSnippetTests(unittest.TestCase):
    def test_all_lesson_python_examples_compile_and_import(self) -> None:
        module_count = 0
        fragment_count = 0
        log_ast = ast.dump(ast.parse((PLAYER_DIR / "log.py").read_text(encoding="utf-8")))
        with (
            patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "1"}, clear=True),
            patch("socket.socket.connect", side_effect=AssertionError("Examples must not connect on import")),
        ):
            for path in sorted((ROOT / "instructions").glob("[0-9][0-9]_*.md")):
                for index, code in enumerate(PYTHON_BLOCK.findall(path.read_text(encoding="utf-8"))):
                    with self.subTest(lesson=path.name, block=index):
                        tree = ast.parse(code)
                        has_main_guard = any(
                            isinstance(statement, ast.If)
                            and isinstance(statement.test, ast.Compare)
                            and isinstance(statement.test.left, ast.Name)
                            and statement.test.left.id == "__name__"
                            for statement in tree.body
                        )
                        if has_main_guard or ast.dump(tree) == log_ast:
                            compiled = compile(tree, f"{path.name}:block-{index}", "exec")
                            exec(compiled, {
                                "__name__": "workshop_example",
                                "__file__": str(PLAYER_DIR / "agent.py"),
                            })
                            module_count += 1
                        else:
                            # Explanatory excerpts rely on the surrounding async main.
                            wrapped = "async def example():\n" + textwrap.indent(code, "    ")
                            compile(wrapped, f"{path.name}:fragment-{index}", "exec")
                            fragment_count += 1
        self.assertGreaterEqual(module_count, 8)
        self.assertGreater(fragment_count, 0)

    def test_final_copied_examples_match_runnable_sources(self) -> None:
        for lesson, source in CANONICAL_COPIES.items():
            with self.subTest(lesson=lesson, source=source):
                expected = ast.dump(ast.parse((PLAYER_DIR / source).read_text(encoding="utf-8")))
                blocks = PYTHON_BLOCK.findall(
                    (ROOT / "instructions" / lesson).read_text(encoding="utf-8")
                )
                actual = [ast.dump(ast.parse(block)) for block in blocks]
                self.assertIn(expected, actual, f"Refresh the {source} example in {lesson}.")


if __name__ == "__main__":
    unittest.main()
