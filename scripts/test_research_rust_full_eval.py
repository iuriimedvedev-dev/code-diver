import dataclasses
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import research_rust_full_eval as evaluation
from code_diver.config import AppConfig, ConfigLoader
from code_diver.config.embedding_profile_registry import EmbeddingProfileRegistry
from code_diver.providers import embedding_provider_builder as builder

from research_rust_full_eval import append, load_completed, quality, schedule, summarize


class FullEvaluationTests(unittest.TestCase):
    def test_external_recognized_profile_never_manages_runtime(self):
        embedding = dataclasses.replace(EmbeddingProfileRegistry().get("qwen3-0.6b").config,
                                        runtime_mode="external", dimensions=1024)
        c = AppConfig(embedding=embedding)
        self.assertEqual(builder.local_embedding_profile_key(c), "qwen3-0.6b")
        with patch.object(builder, "RuntimeConfigStore") as store, \
                patch.object(builder, "EmbeddingRuntimeManager") as manager, \
                patch.object(builder, "create_embedding_provider") as factory:
            builder.make_embedding_provider(c)
        store.assert_not_called()
        manager.assert_not_called()
        for field in ("model", "url", "dimensions", "document_prefix", "query_prefix"):
            self.assertEqual(factory.call_args.kwargs[field], getattr(embedding, field))

    def test_managed_default_still_ensures_runtime(self):
        c = AppConfig(embedding=EmbeddingProfileRegistry().get("qwen3-0.6b").config)
        with patch.object(builder, "RuntimeConfigStore") as store, \
                patch.object(builder, "EmbeddingRuntimeManager") as manager, \
                patch.object(builder, "create_embedding_provider"):
            store.return_value.load.return_value.embedding_profile = "qwen3-0.6b"
            builder.make_embedding_provider(c)
        manager.return_value.ensure_running.assert_called_once_with()

    def test_runtime_mode_loaded_and_invalid_rejected(self):
        self.assertEqual(ConfigLoader()._embedding({"runtime_mode": "external"}).runtime_mode, "external")
        for value in ("typo", None, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ConfigLoader()._embedding({"runtime_mode": value})

    def test_external_still_validates_index_metadata(self):
        c = AppConfig(embedding=dataclasses.replace(
            EmbeddingProfileRegistry().get("qwen3-0.6b").config, runtime_mode="external"))
        with patch.object(builder, "RuntimeConfigStore") as store, \
                patch.object(builder, "EmbeddingRuntimeManager") as manager, \
                self.assertRaisesRegex(ValueError, "model mismatch"):
            builder.make_embedding_provider(c, {"model": "wrong-model"})
        store.assert_not_called()
        manager.assert_not_called()

    def test_managed_unconfigured_runtime_still_rejected(self):
        c = AppConfig(embedding=EmbeddingProfileRegistry().get("qwen3-0.6b").config)
        with patch.object(builder, "RuntimeConfigStore") as store, \
                patch.object(builder, "EmbeddingRuntimeManager") as manager:
            store.return_value.exists.return_value = False
            with self.assertRaisesRegex(RuntimeError, "not configured"):
                builder.make_embedding_provider(c)
        manager.assert_not_called()

    def test_endpoint_options_propagate(self):
        args = evaluation.parse_args(["--run", "smoke", "--embedding-runtime-mode", "external",
            "--embedding-url", "http://127.0.0.1:8001/v1/embeddings",
            "--qdrant-url", "http://127.0.0.1:6333",
            "--python-ce-url", "http://127.0.0.1:18081/v1/rerank",
            "--rust-ce-url", "http://127.0.0.1:18083/v1/rerank"])
        c = evaluation.config(args)
        command = evaluation.native_command(c, args.rust_ce_url)
        self.assertEqual(c.embedding.url, args.embedding_url)
        self.assertEqual(c.embedding.runtime_mode, "external")
        self.assertEqual(c.storage.qdrant.url, args.qdrant_url)
        self.assertEqual(c.cross_encoder_rerank.url, args.python_ce_url)
        for flag, value in (("--embedding-url", args.embedding_url), ("--qdrant-url", args.qdrant_url),
                            ("--ce-url", args.rust_ce_url)):
            self.assertEqual(command[command.index(flag) + 1], value)

    def test_invalid_cli_options(self):
        for option, value in (("--embedding-url", "file:///tmp/embed"), ("--qdrant-url", "http://host:bad"),
                              ("--python-ce-url", "http://user:pass@host/rerank"),
                              ("--rust-ce-url", "http://host/rerank#fragment"),
                              ("--embedding-runtime-mode", "typo"), ("--max-pairs", "0"),
                              ("--seconds", "-1"), ("--run", "..")):
            with self.subTest(option=option), self.assertRaises(SystemExit):
                evaluation.parse_args(["--run", "smoke", option, value])

    def test_eval_runtime_guard_and_compatible_defaults(self):
        c = evaluation.config()
        self.assertEqual(c.embedding.runtime_mode, "managed")
        self.assertEqual(evaluation.native_command(c, c.cross_encoder_rerank.url), evaluation.COMMAND)
        evaluation.validate_runtime(c)
        c.embedding.url = "http://127.0.0.1:8001/v1/embeddings"
        with self.assertRaisesRegex(RuntimeError, "runtime management"):
            evaluation.validate_runtime(c)
        c.embedding.runtime_mode = "external"
        evaluation.validate_runtime(c)
        c.embedding.runtime_mode = "invalid"
        with self.assertRaises(ValueError):
            builder.make_embedding_provider(c)

    def test_frozen_endpoints_mode_and_resume(self):
        args = evaluation.parse_args(["--run", "smoke", "--embedding-runtime-mode", "external",
                                      "--rust-ce-url", "http://127.0.0.1:18083/v1/rerank"])
        c = evaluation.config(args)
        command = evaluation.native_command(c, args.rust_ce_url)
        hashes = {evaluation.BIN: "569ebffd04f73b9f1d0ea798ea9a055d081713e67287a0fc2e00fb98481d8b35",
                  evaluation.MODEL: "8dcadfdc02b050fd35ebafca7f436c822859ff38cfeba4f9bd1203abc90e5010"}
        with patch.object(evaluation, "digest", side_effect=lambda p: hashes.get(p, "test-hash")), \
                patch.object(evaluation.subprocess, "check_output", return_value="test-head"), \
                patch.object(evaluation.platform, "platform", return_value="test-platform"), \
                patch.object(Path, "is_file", return_value=True):
            identity = evaluation.freeze(c, {"key": {}}, {"all": ["key"]}, command)
        self.assertEqual(identity["native_command"], command)
        self.assertEqual(identity["effective_config"]["embedding"]["runtime_mode"], "external")
        self.assertEqual(identity["effective_config"]["embedding"]["url"], args.embedding_url)
        self.assertEqual(identity["effective_config"]["storage"]["qdrant"]["url"], args.qdrant_url)
        self.assertEqual(identity["effective_config"]["cross_encoder_rerank"]["url"], args.python_ce_url)
        with tempfile.TemporaryDirectory(dir=".tmp") as directory:
            path = Path(directory) / "manifest.json"
            evaluation.check_manifest(path, identity)
            evaluation.check_manifest(path, identity)
            for section, field in (("embedding", "url"), ("embedding", "runtime_mode"),
                                   ("cross_encoder_rerank", "url"), ("storage", "qdrant")):
                changed = evaluation.json.loads(evaluation.encoded(identity))
                changed["effective_config"][section][field] = "changed"
                with self.assertRaisesRegex(ValueError, "Frozen identities changed"):
                    evaluation.check_manifest(path, changed)
            changed = {**identity, "native_command": evaluation.native_command(c, "http://other/v1/rerank")}
            with self.assertRaises(ValueError):
                evaluation.check_manifest(path, changed)
            evaluation.check_manifest(path, identity)

    def test_native_launch_and_probe_endpoints(self):
        args = evaluation.parse_args(["--run", "smoke", "--embedding-url", "http://127.0.0.1:8001/v1/embeddings",
            "--qdrant-url", "http://127.0.0.1:6333", "--python-ce-url", "http://127.0.0.1:18081/v1/rerank",
            "--rust-ce-url", "http://127.0.0.1:18083/v1/rerank"])
        c = evaluation.config(args)
        urls = evaluation.endpoint_urls(c, args.rust_ce_url)
        self.assertEqual(urls, {"qdrant": args.qdrant_url + "/collections/" + c.storage.qdrant.collection,
                               "embedding": "http://127.0.0.1:8001/v1/models",
                               "python_ce": "http://127.0.0.1:18081/v1/models",
                               "rust_ce": "http://127.0.0.1:18083/v1/models"})
        command = evaluation.native_command(c, args.rust_ce_url)
        with tempfile.TemporaryDirectory(dir=".tmp") as directory, \
                patch.object(evaluation.subprocess, "Popen") as popen, \
                patch.object(evaluation.Native, "messages", return_value="Server mode: reading queries"):
            native = evaluation.Native(Path(directory), "test", command)
            self.assertEqual(popen.call_args.args[0], command)
            native.writer.close()
            native.log.close()

    def test_schedule_is_paired_complete_and_deterministic(self):
        planned = schedule(list("abcdefgh"))
        self.assertEqual(planned, schedule(list("abcdefgh")))
        self.assertEqual(len(set(planned)), 16)
        for i in range(0, len(planned), 2):
            self.assertEqual(planned[i][0], planned[i + 1][0])
            self.assertEqual({planned[i][1], planned[i + 1][1]}, {"python", "rust"})

    def test_glob_directory_rank_and_failure(self):
        paths = ["miss", "src/a.kt", "dir/sub/a.java"]
        self.assertEqual(quality(paths, ["glob:src/*.kt"])["rr"], .5)
        self.assertEqual(quality(paths, ["dir/"])["first_relevant_rank"], 3)
        self.assertEqual(quality(paths, ["src"], True)["rr"], 0)
        self.assertEqual(quality(["miss"] * 10 + ["src"], ["src"])["hit_at_10"], 0)

    def test_checkpoint_pending_and_duplicates(self):
        Path("artifacts/research/2026-09-07_rust-full-eval").mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir="artifacts/research/2026-09-07_rust-full-eval") as directory:
            path = Path(directory) / "journal.jsonl"
            event = {"index": 0, "pair": ["key", "rust"], "event": "begin"}
            append(path, event)
            rows, pending = load_completed(path, [("key", "rust")])
            self.assertEqual(len(pending), 1)
            self.assertFalse(rows)
            append(path, {**event, "event": "result"})
            rows, pending = load_completed(path, [("key", "rust")])
            self.assertEqual(len(rows), 1)
            self.assertFalse(pending)
            append(path, event)
            with self.assertRaises(ValueError):
                load_completed(path, [("key", "rust")])

    def test_summary_keeps_failure_denominator_and_paired_delta(self):
        rows = {i: {"pair": [key, arm], "wall_ms": latency, **quality(paths, ["gold"], failed)}
                for i, (key, arm, latency, paths, failed) in enumerate([
                    ("a", "python", 10, ["gold"], False), ("a", "rust", 20, ["gold"], True),
                    ("b", "python", 30, [], False), ("b", "rust", 40, ["gold"], False)])}
        summary = summarize(rows, {"all": ["a", "b"]})["all"]
        self.assertEqual(summary["rust"]["attempted"], 2)
        self.assertEqual(summary["rust"]["failures"], 1)
        self.assertEqual(summary["rust"]["hit_at_10"], .5)
        self.assertEqual(summary["rust"]["p95_ms"], 40)
        self.assertEqual(summary["paired"]["rust_minus_python_rr"], 0)


if __name__ == "__main__":
    unittest.main()