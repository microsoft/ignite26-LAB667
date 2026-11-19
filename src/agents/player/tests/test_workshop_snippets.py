"""Keep executable workshop examples compatible and final copies in sync."""
from __future__ import annotations

import ast
import contextlib
import io
import os
import re
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

PLAYER_DIR = Path(__file__).resolve().parents[1]
ROOT = PLAYER_DIR.parents[2]
LESSONS_DIR = ROOT / "player" / "guided"
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
            for path in sorted(LESSONS_DIR.glob("[0-9][0-9]_*.md")):
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
                    (LESSONS_DIR / lesson).read_text(encoding="utf-8")
                )
                actual = [ast.dump(ast.parse(block)) for block in blocks]
                self.assertTrue(expected in actual, f"Refresh the {source} example in {lesson}.")


class ConversationOutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_sequential_messages_and_replies_are_printed_in_order(self) -> None:
        for lesson in ("03_connect_to_the_gaming_mcp_server.md", "05_add_session_logging.md"):
            with self.subTest(lesson=lesson):
                blocks = PYTHON_BLOCK.findall((LESSONS_DIR / lesson).read_text(encoding="utf-8"))
                code = next(block for block in blocks if 'if __name__ == "__main__":' in block)
                framework = MagicMock()
                openai = MagicMock()
                dotenv = MagicMock()
                log = MagicMock()
                log.build_logging_middleware.return_value = (None, None, None)
                mcp = framework.MCPStreamableHTTPTool.return_value
                mcp.get_prompt = AsyncMock(return_value="game instructions")
                agent = framework.Agent.return_value
                session = agent.create_session.return_value
                output = io.StringIO()
                output_at_send = []

                async def run(message, *, session):
                    output_at_send.append(output.getvalue())
                    return MagicMock(text=f"Reply to {message}")

                agent.run = AsyncMock(side_effect=run)
                namespace = {"__name__": "workshop_example", "__file__": str(PLAYER_DIR / "agent.py")}
                with (
                    patch.dict(sys.modules, {
                        "agent_framework": framework,
                        "agent_framework.openai": openai,
                        "dotenv": dotenv,
                        "log": log,
                    }),
                    patch.dict(os.environ, {
                        "AZURE_OPENAI_ENDPOINT": "https://model.invalid/openai/v1/",
                        "AZURE_OPENAI_API_KEY": "offline-key",
                        "AZURE_OPENAI_DEPLOYMENT_NAME": "model",
                        "GAME_MCP_URL": "https://game.invalid",
                        "GAME_API_KEY": "offline-key",
                    }),
                    contextlib.redirect_stdout(output),
                ):
                    exec(compile(code, lesson, "exec"), namespace)
                    await namespace["main"]()

                self.assertEqual(
                    openai.OpenAIChatClient.call_args.kwargs["azure_endpoint"],
                    "https://model.invalid",
                )
                messages = ["Hi, can we start the game?", "Yes"]
                self.assertEqual([call.args[0] for call in agent.run.await_args_list], messages)
                for call in agent.run.await_args_list:
                    self.assertIs(call.kwargs["session"], session)
                first = "You:\nHi, can we start the game?\n\n"
                first_reply = "Agent:\nReply to Hi, can we start the game?\n\n"
                second = "You:\nYes\n\n"
                second_reply = "Agent:\nReply to Yes\n\n"
                self.assertTrue(output_at_send[0].endswith(first))
                self.assertTrue(output_at_send[1].endswith(first + first_reply + second))
                self.assertTrue(output.getvalue().endswith(first + first_reply + second + second_reply))


if __name__ == "__main__":
    unittest.main()
