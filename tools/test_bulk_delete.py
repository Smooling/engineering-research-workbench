"""Deletion regression checks using memory fixtures; never touch the workspace."""
from __future__ import annotations

import copy
import ast
from datetime import datetime
from pathlib import Path
import threading
from functools import wraps
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace
from typing import Any
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def isolated_definitions(file, names, namespace):
    # Importing the full app can migrate personal configuration. Compile the
    # actual definitions in isolation so this suite cannot touch that data.
    tree = ast.parse((ROOT / file).read_text(encoding="utf-8"))
    nodes = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), file, "exec"), namespace)


todos = ModuleType("isolated_todos")
todos.__dict__.update(Any=Any, datetime=datetime, _LOCK=threading.RLock(), _load=Mock(), _save=Mock())
isolated_definitions("app/todos.py", {"list_todos", "_decorate", "is_overdue", "parse_due", "delete_many"}, todos.__dict__)
server = ModuleType("isolated_server")
server.__dict__.update(todos=todos, indexer=SimpleNamespace(delete_docs=Mock(), refresh_todos=Mock()),
                       wraps=wraps, nullcontext=nullcontext, mutation_lock=threading.RLock())
isolated_definitions("server.py", {"serialized_write", "_batch_ids", "_delete_documents", "handle_api_post"}, server.__dict__)


class BulkDeleteTests(unittest.TestCase):
    def test_selection_validation(self):
        self.assertEqual(server._batch_ids({"ids": ["a", "a", "b"]}), ["a", "b"])
        for value in (None, [], "a", [1], [""], [" "], ["a"] * 1001):
            with self.subTest(value=str(value)[:25]), self.assertRaises(ValueError):
                server._batch_ids({"ids": value})

    def test_manual_cleanup_rechecks_completed_and_keeps_unselected(self):
        records = [
            {"id": "done", "done": True, "due": "2020-01-01"},
            {"id": "pending", "done": False},
            {"id": "unselected", "done": True},
        ]
        with patch.object(todos, "_load", side_effect=lambda: copy.deepcopy(records)), \
                patch.object(todos, "_save", side_effect=lambda rows: records.__setitem__(slice(None), rows)) as save:
            # Reading old completed items never triggers automatic deletion.
            self.assertEqual(len(todos.list_todos()), 3)
            save.assert_not_called()
            result = todos.delete_many(["done", "pending", "missing"], completed_only=True)
            self.assertEqual(result["deleted"], ["done"])
            self.assertEqual([x["id"] for x in result["failed"]], ["pending", "missing"])
            self.assertEqual([x["id"] for x in records], ["pending", "unselected"])
            save.assert_called_once()
            result = todos.delete_many(["pending", "pending"])
            self.assertEqual(result["deleted"], ["pending"])
            self.assertEqual([x["id"] for x in records], ["unselected"])

    def test_document_partial_failure_is_reported(self):
        remove = Mock(return_value={"deleted": ["one", "four"], "failed": [{"id": "gone"}, {"id": "locked"}]})
        with patch.object(server.indexer, "delete_docs", remove):
            result = server._delete_documents(["one", "gone", "locked", "four"])
        self.assertEqual(result["deleted"], ["one", "four"])
        self.assertEqual([x["id"] for x in result["failed"]], ["gone", "locked"])
        remove.assert_called_once_with(["one", "gone", "locked", "four"])

    def test_batch_routes_precede_single_record_routes(self):
        handler = SimpleNamespace(send_json=Mock(side_effect=lambda data, *args: data))
        with patch.object(server.todos, "delete_many", return_value={"deleted": ["a"], "failed": []}) as remove, \
                patch.object(server.indexer, "refresh_todos") as refresh:
            result = server.handle_api_post(handler, "/api/todos/batch-delete", {"ids": ["a", "a"], "completed_only": True})
            remove.assert_called_once_with(["a"], completed_only=True)
            refresh.assert_called_once()
            self.assertEqual(result["deleted"], ["a"])
        with patch.object(server, "_delete_documents", return_value={"deleted": ["d"], "failed": []}) as remove:
            server.handle_api_post(handler, "/api/docs/batch-delete", {"ids": ["d"]})
            remove.assert_called_once_with(["d"])


if __name__ == "__main__":
    unittest.main()
