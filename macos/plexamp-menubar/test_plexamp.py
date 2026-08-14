#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testy logiki wtyczki (dzialaja na kazdym systemie, bez macOS i bez Plexa)."""

import errno
import importlib.util
import io
import json
import socket
import tempfile
import unittest
import unittest.mock
import urllib.error
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "plexamp_plugin", Path(__file__).with_name("plexamp.5s.py")
)
plugin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plugin)


def session(**overrides):
    data = {
        "type": "track",
        "title": "Bohemian Rhapsody",
        "grandparentTitle": "Queen",
        "parentTitle": "A Night at the Opera",
        "parentYear": 1975,
        "viewOffset": 65000,
        "duration": 355000,
        "ratingKey": "1234",
        "Player": {"product": "Plexamp", "title": "MacBook", "state": "playing"},
        "User": {"title": "pawel"},
    }
    for key, value in overrides.items():
        if key in ("Player", "User") and isinstance(value, dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    return data


def fake_opener(payload, error=None):
    def opener(request, timeout=None):  # noqa: ARG001
        if error is not None:
            raise error
        body = json.dumps(payload).encode("utf-8")
        stream = io.BytesIO(body)
        stream.__enter__ = lambda: stream
        stream.__exit__ = lambda *args: False
        return stream

    return opener


class ConfigTests(unittest.TestCase):
    def test_defaults_when_nothing_provided(self):
        cfg = plugin.load_config(env={})
        self.assertEqual(cfg["plex_url"], "http://localhost:32400")
        self.assertEqual(cfg["players"], ["Plexamp"])
        self.assertTrue(cfg["music_only"])

    def test_file_values_override_defaults(self):
        cfg = plugin.load_config(env={}, config_data={"plex_url": "http://nas:32400/", "user": "ala"})
        self.assertEqual(cfg["plex_url"], "http://nas:32400")
        self.assertEqual(cfg["user"], "ala")

    def test_env_overrides_file_and_coerces_types(self):
        cfg = plugin.load_config(
            env={
                "VAR_PLEX_URL": "http://env:32400",
                "VAR_MAX_LENGTH": "12",
                "VAR_HIDE_WHEN_IDLE": "false",
                "VAR_PLAYERS": "Plexamp, Plex Web",
            },
            config_data={"plex_url": "http://file:32400", "max_length": 99},
        )
        self.assertEqual(cfg["plex_url"], "http://env:32400")
        self.assertEqual(cfg["max_length"], 12)
        self.assertFalse(cfg["hide_when_idle"])
        self.assertEqual(cfg["players"], ["Plexamp", "Plex Web"])

    def test_empty_env_value_does_not_override(self):
        cfg = plugin.load_config(env={"VAR_PLEX_TOKEN": ""}, config_data={"plex_token": "abc"})
        self.assertEqual(cfg["plex_token"], "abc")

    def test_default_config_sits_next_to_the_script(self):
        self.assertEqual(plugin.DEFAULT_CONFIG_PATH.parent, Path(__file__).parent)
        self.assertEqual(plugin.DEFAULT_CONFIG_PATH.name, "config.json")

    def test_config_candidates_include_script_directory(self):
        candidates = plugin.config_candidates(env={})
        self.assertIn(Path(__file__).parent / "config.json", candidates)

    def test_config_candidates_include_hidden_variant(self):
        candidates = plugin.config_candidates(env={})
        self.assertIn(Path(__file__).parent / ".plexamp-menubar.json", candidates)

    def test_config_env_override_wins(self):
        candidates = plugin.config_candidates(env={"PLEXAMP_MENUBAR_CONFIG": "/tmp/inny.json"})
        self.assertEqual(candidates, [Path("/tmp/inny.json")])

    def test_read_config_file_reads_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"plex_token": "abc"}', encoding="utf-8")
            self.assertEqual(plugin.read_config_file(path), {"plex_token": "abc"})

    def test_read_config_file_missing_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(plugin.read_config_file(Path(tmp) / "nie-ma.json"), {})

    def test_read_config_file_broken_json_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{ to nie jest json", encoding="utf-8")
            with self.assertRaises(plugin.ConfigError):
                plugin.read_config_file(path)

    def test_read_config_file_uses_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "custom.json"
            path.write_text('{"plex_url": "http://z-env:32400"}', encoding="utf-8")
            data = plugin.read_config_file(env={"PLEXAMP_MENUBAR_CONFIG": str(path)})
            self.assertEqual(data["plex_url"], "http://z-env:32400")

    def test_token_cmd_used_when_token_empty(self):
        cfg = plugin.load_config(env={}, config_data={"token_cmd": "echo secret"})
        self.assertEqual(plugin.resolve_token(cfg, runner=lambda cmd: "secret\n"), "secret")

    def test_token_cmd_failure_is_reported(self):
        cfg = plugin.load_config(env={}, config_data={"token_cmd": "boom"})

        def runner(cmd):
            raise OSError("nie ma takiej komendy")

        with self.assertRaises(plugin.ConfigError):
            plugin.resolve_token(cfg, runner=runner)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.cfg = plugin.load_config(env={})

    def test_picks_plexamp_music_session(self):
        picked = plugin.pick_session([session()], self.cfg)
        self.assertEqual(plugin.describe(picked)["title"], "Bohemian Rhapsody")

    def test_ignores_other_players(self):
        other = session(Player={"product": "Plex for Apple TV", "title": "Salon"})
        self.assertIsNone(plugin.pick_session([other], self.cfg))

    def test_ignores_video_when_music_only(self):
        movie = session(type="movie", title="Dune")
        self.assertIsNone(plugin.pick_session([movie], self.cfg))

    def test_video_allowed_when_music_only_disabled(self):
        cfg = plugin.load_config(env={}, config_data={"music_only": False})
        movie = session(type="movie", title="Dune")
        self.assertIsNotNone(plugin.pick_session([movie], cfg))

    def test_playing_wins_over_paused(self):
        paused = session(title="Cisza", Player={"state": "paused"})
        playing = session(title="Gra", Player={"state": "playing"})
        picked = plugin.pick_session([paused, playing], self.cfg)
        self.assertEqual(picked["title"], "Gra")

    def test_paused_hidden_when_disabled(self):
        cfg = plugin.load_config(env={}, config_data={"show_paused": False})
        paused = session(Player={"state": "paused"})
        self.assertIsNone(plugin.pick_session([paused], cfg))

    def test_user_filter(self):
        cfg = plugin.load_config(env={}, config_data={"user": "Pawel"})
        self.assertIsNotNone(plugin.pick_session([session()], cfg))
        self.assertIsNone(plugin.pick_session([session(User={"title": "gosc"})], cfg))

    def test_empty_players_matches_anything(self):
        cfg = plugin.load_config(env={}, config_data={"players": []})
        other = session(Player={"product": "Plex Web", "title": "Chrome"})
        self.assertIsNotNone(plugin.pick_session([other], cfg))

    def test_describe_handles_missing_fields(self):
        described = plugin.describe({"title": "Utwor", "Player": {}})
        self.assertEqual(described["artist"], "")
        self.assertEqual(described["duration_ms"], 0)


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.cfg = plugin.load_config(env={})

    def test_menu_title(self):
        track = plugin.describe(session())
        self.assertEqual(plugin.format_menu_title(track, self.cfg), "♪ Queen – Bohemian Rhapsody")

    def test_menu_title_paused_icon(self):
        track = plugin.describe(session(Player={"state": "paused"}))
        self.assertTrue(plugin.format_menu_title(track, self.cfg).startswith("⏸"))

    def test_menu_title_truncated(self):
        cfg = plugin.load_config(env={}, config_data={"max_length": 12})
        track = plugin.describe(session())
        title = plugin.format_menu_title(track, cfg)
        self.assertEqual(title, "♪ Queen – Boh…")
        self.assertEqual(len(title) - 2, 12)

    def test_menu_title_without_artist(self):
        track = plugin.describe(session(grandparentTitle="", originalTitle=""))
        self.assertEqual(plugin.format_menu_title(track, self.cfg), "♪ Bohemian Rhapsody")

    def test_pipe_is_escaped(self):
        track = plugin.describe(session(title="A | B"))
        self.assertNotIn("|", plugin.render_track(track, self.cfg).splitlines()[0])

    def test_param_value_is_safe_for_swiftbar(self):
        self.assertEqual(plugin.param_value('A "B" | C\nD'), "A 'B' │ C D")

    def test_copy_action_has_no_stray_quotes(self):
        track = plugin.describe(session(title='He said "hi"', grandparentTitle="A|B"))
        line = [l for l in plugin.render_track(track, self.cfg).splitlines() if "pbcopy" in l][0]
        self.assertEqual(line.count('"'), 2)
        self.assertEqual(line.count("|"), 1)

    def test_format_time(self):
        self.assertEqual(plugin.format_time(65000), "1:05")
        self.assertEqual(plugin.format_time(3_725_000), "1:02:05")
        self.assertEqual(plugin.format_time(None), "0:00")

    def test_progress_bar(self):
        self.assertEqual(plugin.progress_bar(0, 100, width=4), "░░░░")
        self.assertEqual(plugin.progress_bar(100, 100, width=4), "████")
        self.assertEqual(plugin.progress_bar(50, 100, width=4), "██░░")
        self.assertEqual(plugin.progress_bar(10, 0), "")

    def test_idle_output_hidden_by_default(self):
        self.assertEqual(plugin.render_idle(self.cfg), "")

    def test_idle_output_visible_when_configured(self):
        cfg = plugin.load_config(env={}, config_data={"hide_when_idle": False})
        self.assertIn("Nic nie gra", plugin.render_idle(cfg))

    def test_track_output_structure(self):
        output = plugin.render_track(plugin.describe(session()), self.cfg)
        lines = output.splitlines()
        self.assertEqual(lines[0], "♪ Queen – Bohemian Rhapsody")
        self.assertEqual(lines[1], "---")
        self.assertIn("A Night at the Opera (1975)", output)
        self.assertIn("1:05 / 5:55", output)
        self.assertIn("refresh=true", output)


class NetworkErrorTests(unittest.TestCase):
    def test_permission_denied_points_at_sandbox(self):
        description, hint = plugin.explain_network_error(
            PermissionError(errno.EPERM, "Operation not permitted")
        )
        self.assertIn("zablokowal", description)
        self.assertIn("Local Network", hint)

    def test_connection_refused_points_at_server(self):
        description, hint = plugin.explain_network_error(
            ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused")
        )
        self.assertEqual(description, "Polaczenie odrzucone")
        self.assertIn("32400", hint)

    def test_unknown_host(self):
        description, _ = plugin.explain_network_error(socket.gaierror("Name or service not known"))
        self.assertIn("nazwy hosta", description)

    def test_timeout(self):
        description, _ = plugin.explain_network_error(TimeoutError("timed out"))
        self.assertIn("limit czasu", description)

    def test_localhost_gets_ipv4_variant(self):
        self.assertEqual(
            plugin.url_variants("http://localhost:32400"),
            ["http://localhost:32400", "http://127.0.0.1:32400"],
        )

    def test_other_hosts_have_single_variant(self):
        self.assertEqual(
            plugin.url_variants("http://192.168.1.10:32400"), ["http://192.168.1.10:32400"]
        )

    def test_second_variant_is_tried_after_failure(self):
        attempts = []

        def opener(request, timeout=None):  # noqa: ARG001
            attempts.append(request.full_url)
            if "localhost" in request.full_url:
                raise urllib.error.URLError(ConnectionRefusedError(errno.ECONNREFUSED, "refused"))
            return fake_opener({"MediaContainer": {"Metadata": []}})(request, timeout)

        cfg = plugin.load_config(env={})
        self.assertEqual(plugin.fetch_sessions(cfg, "token", opener=opener), [])
        self.assertEqual(len(attempts), 2)
        self.assertIn("127.0.0.1", attempts[1])

    def test_error_carries_hint_into_menu(self):
        error = urllib.error.URLError(PermissionError(errno.EPERM, "Operation not permitted"))
        cfg = plugin.load_config(env={})
        with self.assertRaises(plugin.PlexError) as ctx:
            plugin.fetch_sessions(cfg, "token", opener=fake_opener(None, error=error))
        output = plugin.render_error(str(ctx.exception), cfg, ctx.exception.hint)
        self.assertIn("Local Network", output)
        self.assertIn("--diagnose", output)


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.cfg = plugin.load_config(env={})

    def test_fetch_returns_metadata(self):
        opener = fake_opener({"MediaContainer": {"size": 1, "Metadata": [session()]}})
        items = plugin.fetch_sessions(self.cfg, "token", opener=opener)
        self.assertEqual(len(items), 1)

    def test_fetch_empty_container(self):
        opener = fake_opener({"MediaContainer": {"size": 0}})
        self.assertEqual(plugin.fetch_sessions(self.cfg, "token", opener=opener), [])

    def test_unauthorized_message(self):
        error = urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)
        with self.assertRaises(plugin.PlexError) as ctx:
            plugin.fetch_sessions(self.cfg, "zly", opener=fake_opener(None, error=error))
        self.assertIn("token", str(ctx.exception).lower())

    def test_connection_error_message(self):
        error = urllib.error.URLError("connection refused")
        with self.assertRaises(plugin.PlexError) as ctx:
            plugin.fetch_sessions(self.cfg, "token", opener=fake_opener(None, error=error))
        self.assertIn("localhost:32400", str(ctx.exception))

    def test_build_output_without_token(self):
        output = plugin.build_output(self.cfg, "")
        self.assertIn("Brak tokenu Plex", output)

    def test_build_output_end_to_end(self):
        opener = fake_opener({"MediaContainer": {"Metadata": [session()]}})
        output = plugin.build_output(self.cfg, "token", opener=opener)
        self.assertTrue(output.startswith("♪ Queen – Bohemian Rhapsody"))

    def test_build_output_idle(self):
        opener = fake_opener({"MediaContainer": {"Metadata": []}})
        self.assertEqual(plugin.build_output(self.cfg, "token", opener=opener), "")


class DiagnoseTests(unittest.TestCase):
    def run_diagnose(self, config):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            stream = io.StringIO()
            with unittest.mock.patch.dict(
                plugin.os.environ, {"PLEXAMP_MENUBAR_CONFIG": str(path)}, clear=False
            ):
                code = plugin.diagnose(stream=stream)
            return code, stream.getvalue()

    def test_reports_missing_token(self):
        code, output = self.run_diagnose({"plex_url": "http://127.0.0.1:1"})
        self.assertEqual(code, 1)
        self.assertIn("token:         BRAK", output)

    def test_reports_unreachable_server(self):
        # port 1 na loopbacku - odmowa polaczenia jest natychmiastowa
        code, output = self.run_diagnose(
            {"plex_url": "http://127.0.0.1:1", "plex_token": "x", "timeout": 1.0}
        )
        self.assertEqual(code, 1)
        self.assertIn("Test polaczenia TCP", output)
        self.assertIn("Polaczenie odrzucone", output)
        self.assertIn("jest (1 znakow)", output)

    def test_lists_sessions_and_final_title(self):
        opener = fake_opener({"MediaContainer": {"Metadata": [session()]}})
        with unittest.mock.patch.object(plugin.urllib.request, "urlopen", opener):
            with unittest.mock.patch.object(plugin, "tcp_check", lambda *a, **k: (True, "OK")):
                code, output = self.run_diagnose(
                    {"plex_url": "http://127.0.0.1:32400", "plex_token": "x"}
                )
        self.assertEqual(code, 0)
        self.assertIn("sesji lacznie: 1", output)
        self.assertIn("♪ Queen – Bohemian Rhapsody", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
