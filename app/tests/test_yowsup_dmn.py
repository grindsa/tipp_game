import io
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from tools import yowsup_dmn as yd


SETTINGS = SimpleNamespace(WA_SRV="wa.local", WA_PORT=9009)


class FakeQuerySet(object):
    def __init__(self, rows):
        self.rows = list(rows)

    def exclude(self, **kwargs):
        if "number" in kwargs:
            skip = kwargs["number"]
            return FakeQuerySet([row for row in self.rows if row != skip])
        return self

    def values_list(self, *_args, **_kwargs):
        return list(self.rows)


class FakeGroupsetting(object):
    def __init__(self, rows):
        self.objects = FakeQuerySet(rows)


class FakeSock(object):
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.recv_sizes = []

    def recv(self, size):
        self.recv_sizes.append(size)
        if self.payloads:
            return self.payloads.pop(0)
        return b""


class FakeTCPClient(object):
    def __init__(self, payloads=None, salt="salt-value"):
        self.payloads = list(payloads or [])
        self.salt = salt
        self.cli_sock = FakeSock(self.payloads)
        self.calls = []
        self.stopped = False

    def run(self, host, port):
        self.calls.append(("run", host, port))

    def dh_send(self):
        self.calls.append(("dh_send",))
        return (11, 22, 33)

    def receive_single(self):
        self.calls.append(("receive_single",))
        return b"dh-payload"

    def dh_receive(self, data, secret, sprime):
        self.calls.append(("dh_receive", data, secret, sprime))
        return self.salt

    def send(self, text, salt):
        self.calls.append(("send", text, salt))

    def b64_decode(self, data):
        self.calls.append(("b64_decode", data))
        return data

    def check_integrity(self, message, salt):
        self.calls.append(("check_integrity", message, salt))
        return message

    def stop(self):
        self.stopped = True


class YowsupDmnTests(SimpleTestCase):
    def test_parse_args_defaults_debug_off(self):
        args = yd.parse_args([])
        self.assertFalse(args.debug)

    def test_parse_args_enables_debug_short_and_long(self):
        self.assertTrue(yd.parse_args(["-d"]).debug)
        self.assertTrue(yd.parse_args(["--debug"]).debug)

    def test_load_group_jids_skips_empty_and_none(self):
        model = FakeGroupsetting(["49111", "", None, "49222"])
        self.assertEqual(yd.load_group_jids(groupsetting_model=model), ["49111", "49222"])

    def test_collect_announce_numbers_adds_debug_route_once(self):
        jids = ["49111", "49222"]
        self.assertEqual(yd.collect_announce_numbers(jids, debug=False), jids)
        self.assertEqual(
            yd.collect_announce_numbers(jids, debug=True),
            ["49111", "49222", yd.DEBUG_ROUTE_NUMBER],
        )
        already = ["49111", yd.DEBUG_ROUTE_NUMBER]
        self.assertEqual(yd.collect_announce_numbers(already, debug=True), already)

    def test_build_announce_routes_includes_debug_number(self):
        jids = ["49111"]
        self.assertEqual(yd.build_announce_routes(jids, debug=False), "routes announce 49111")
        self.assertEqual(
            yd.build_announce_routes(jids, debug=True),
            "routes announce 49111,{0}".format(yd.DEBUG_ROUTE_NUMBER),
        )

    def test_should_ignore_initial_window(self):
        self.assertTrue(yd.should_ignore_initial(20, 10, ignore_seconds=15))
        self.assertTrue(yd.should_ignore_initial(25, 10, ignore_seconds=15))
        self.assertFalse(yd.should_ignore_initial(26, 10, ignore_seconds=15))

    def test_split_source_and_body_parses_and_rejects(self):
        self.assertEqual(
            yd.split_source_and_body("group [+49123] - hello - world"),
            ("group [+49123]", "hello - world"),
        )
        output = io.StringIO()
        with redirect_stdout(output):
            source, body = yd.split_source_and_body("no-separator")
        self.assertIsNone(source)
        self.assertIsNone(body)
        self.assertIn("error:", output.getvalue())

    def test_resolve_sender_uses_lookup_and_falls_back(self):
        source, sender = yd.resolve_sender(
            "raw", lookup_fn=lambda _value: ("group", "49123")
        )
        self.assertEqual((source, sender), ("group", "49123"))

        source, sender = yd.resolve_sender(
            "raw", lookup_fn=lambda _value: (_ for _ in ()).throw(ValueError("bad"))
        )
        self.assertEqual((source, sender), ("raw", "raw"))

    def test_parse_location_body_splits_lat_lon(self):
        self.assertEqual(yd.parse_location_body("location:52.5,13.4"), ("52.5", "13.4"))

    def test_handle_message_body_dispatches_location_and_text(self):
        parse_location = mock.Mock(return_value=(True, "arena"))
        parse_message = mock.Mock(return_value=(False, None))

        reply = yd.handle_message_body(
            "location:52.5,13.4",
            "49123",
            "group",
            100,
            parse_message_fn=parse_message,
            parse_location_fn=parse_location,
        )
        self.assertEqual(reply, (True, "arena"))
        parse_location.assert_called_once_with("52.5", "13.4", "49123")
        parse_message.assert_not_called()

        reply = yd.handle_message_body(
            "4:2",
            "49123",
            "group",
            100,
            parse_message_fn=parse_message,
            parse_location_fn=parse_location,
        )
        self.assertEqual(reply, (False, None))
        parse_message.assert_called_once_with("4:2", "49123", "group", 100)

    def test_handshake_announces_routes_and_returns_salt(self):
        client = FakeTCPClient(salt="shared-salt")
        salt = yd.handshake(client, "wa.local", 9009, "routes announce 49111")
        self.assertEqual(salt, "shared-salt")
        self.assertEqual(client.calls[0], ("run", "wa.local", 9009))
        self.assertIn(("send", "routes announce 49111", "shared-salt"), client.calls)

    def test_process_packet_skips_when_salt_missing(self):
        client = FakeTCPClient()
        send_fn = mock.Mock()
        with mock.patch.object(yd, "print_debug"):
            sent = yd.process_packet(
                client, b"payload", None, 50, True, SETTINGS, send_fn=send_fn
            )
        self.assertFalse(sent)
        send_fn.assert_not_called()

    def test_process_packet_sends_reply_for_text_message(self):
        client = FakeTCPClient()
        send_fn = mock.Mock()
        sent = yd.process_packet(
            client,
            "group [+49123] - 4:2",
            "salt",
            50,
            False,
            SETTINGS,
            send_fn=send_fn,
            lookup_fn=lambda _value: ("group", "49123"),
            parse_message_fn=lambda *_args: (True, "tip stored"),
            parse_location_fn=mock.Mock(),
        )
        self.assertTrue(sent)
        send_fn.assert_called_once_with("wa.local", 9009, "group", "tip stored")

    def test_process_packet_handles_location_without_reply(self):
        client = FakeTCPClient()
        send_fn = mock.Mock()
        sent = yd.process_packet(
            client,
            "group [+49123] - location:52.5,13.4",
            "salt",
            50,
            False,
            SETTINGS,
            send_fn=send_fn,
            lookup_fn=lambda _value: ("group", "49123"),
            parse_message_fn=mock.Mock(),
            parse_location_fn=lambda lat, lon, sender: (False, None),
        )
        self.assertFalse(sent)
        send_fn.assert_not_called()

    def test_receive_loop_ignores_startup_then_disconnects(self):
        client = FakeTCPClient(payloads=[b"ignored", b""])
        send_fn = mock.Mock()
        times = iter([10, 40])

        with mock.patch.object(yd, "print_debug"):
            rc = yd.receive_loop(
                client,
                "salt",
                uts_start=10,
                debug=True,
                settings_obj=SETTINGS,
                time_fn=lambda: next(times),
                ignore_seconds=15,
                send_fn=send_fn,
                lookup_fn=mock.Mock(),
                parse_message_fn=mock.Mock(),
                parse_location_fn=mock.Mock(),
            )
        self.assertEqual(rc, yd.EXIT_DISCONNECTED)
        send_fn.assert_not_called()

    def test_receive_loop_processes_packet_after_ignore_window(self):
        client = FakeTCPClient(payloads=["group [+49123] - 4:2", b""])
        send_fn = mock.Mock()
        times = iter([100])

        rc = yd.receive_loop(
            client,
            "salt",
            uts_start=10,
            debug=False,
            settings_obj=SETTINGS,
            time_fn=lambda: next(times),
            ignore_seconds=15,
            send_fn=send_fn,
            lookup_fn=lambda _value: ("group", "49123"),
            parse_message_fn=lambda *_args: (True, "ok"),
            parse_location_fn=mock.Mock(),
        )
        self.assertEqual(rc, yd.EXIT_DISCONNECTED)
        send_fn.assert_called_once_with("wa.local", 9009, "group", "ok")

    def test_process_packet_swallows_parser_errors(self):
        client = FakeTCPClient()
        send_fn = mock.Mock()
        with mock.patch.object(yd, "print_debug"):
            sent = yd.process_packet(
                client,
                "group [+49123] - 4:2",
                "salt",
                50,
                True,
                SETTINGS,
                send_fn=send_fn,
                lookup_fn=lambda _value: ("group", "49123"),
                parse_message_fn=mock.Mock(side_effect=RuntimeError("bad tip")),
                parse_location_fn=mock.Mock(),
            )
        self.assertFalse(sent)
        send_fn.assert_not_called()

    def test_run_prints_jids_and_adds_debug_route(self):
        client = FakeTCPClient(payloads=[b""])
        model = FakeGroupsetting(["49111", "49222"])
        logs = []

        def capture_debug(debug, text):
            if debug:
                logs.append(text)

        with mock.patch.object(yd, "print_debug", side_effect=capture_debug):
            rc = yd.run(
                debug=True,
                settings_obj=SETTINGS,
                groupsetting_model=model,
                client_factory=lambda: client,
                time_fn=lambda: 100,
                send_fn=mock.Mock(),
            )

        self.assertEqual(rc, yd.EXIT_DISCONNECTED)
        self.assertTrue(client.stopped)
        self.assertIn("got jids: 49111,49222", logs)
        self.assertTrue(any("Starting WhatsApp daemon on wa.local:9009" in item for item in logs))
        announced = [call for call in client.calls if call[0] == "send"]
        self.assertEqual(
            announced[0][1],
            "routes announce 49111,49222,{0}".format(yd.DEBUG_ROUTE_NUMBER),
        )

    def test_run_omits_jids_and_debug_route_without_debug(self):
        client = FakeTCPClient(payloads=[b""])
        model = FakeGroupsetting(["49111"])
        logs = []

        def capture_debug(debug, text):
            if debug:
                logs.append(text)

        with mock.patch.object(yd, "print_debug", side_effect=capture_debug):
            yd.run(
                debug=False,
                settings_obj=SETTINGS,
                groupsetting_model=model,
                client_factory=lambda: client,
                time_fn=lambda: 100,
                send_fn=mock.Mock(),
            )

        self.assertEqual(logs, [])
        announced = [call for call in client.calls if call[0] == "send"]
        self.assertEqual(announced[0][1], "routes announce 49111")

    def test_main_returns_runtime_error_on_failure(self):
        with mock.patch.object(yd, "run", side_effect=RuntimeError("boom")):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = yd.main(["--debug"])
        self.assertEqual(rc, yd.EXIT_RUNTIME_ERROR)
        self.assertIn("yowsup_dmn failed: boom", output.getvalue())
