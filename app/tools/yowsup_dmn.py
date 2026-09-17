#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""WhatsApp daemon that announces group routes and handles inbound messages."""

from __future__ import absolute_import
from __future__ import print_function

import argparse
import os
import sys
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")

import django

django.setup()

from django.conf import settings
from game.models import Groupsetting
from game.myfunctions import lookup_sender, parse_location, parse_message, print_debug

try:
    from wa_hack_cli import TCPclient, simple_send
except ImportError:
    from game.wa_hack_cli import TCPclient, simple_send

DEBUG_ROUTE_NUMBER = "491717626871"
INITIAL_IGNORE_SECONDS = 15
RECV_BUFFER_SIZE = 1024

EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1
EXIT_DISCONNECTED = 0


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="WhatsApp daemon for tipp_game group messages."
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable extra logging, print JIDs, and announce the debug route number.",
    )
    return parser.parse_args(argv)


def load_group_jids(groupsetting_model=None):
    """Return non-empty WhatsApp group numbers from Groupsetting."""
    model = groupsetting_model or Groupsetting
    numbers = model.objects.exclude(number="").values_list("number", flat=True)
    return [number for number in numbers if number]


def collect_announce_numbers(jids, debug=False, debug_number=DEBUG_ROUTE_NUMBER):
    """Build the JID list announced to the WhatsApp server."""
    numbers = list(jids)
    if debug and debug_number and debug_number not in numbers:
        numbers.append(debug_number)
    return numbers


def build_announce_routes(jids, debug=False, debug_number=DEBUG_ROUTE_NUMBER):
    """Build the `routes announce` command for the WhatsApp server."""
    numbers = collect_announce_numbers(jids, debug=debug, debug_number=debug_number)
    return "routes announce {0}".format(",".join(numbers))


def should_ignore_initial(uts_now, uts_start, ignore_seconds=INITIAL_IGNORE_SECONDS):
    """Return True while the daemon is still in its startup ignore window."""
    return int(uts_now) - int(uts_start) <= ignore_seconds


def split_source_and_body(message):
    """Split `source - body` from an inbound WhatsApp payload."""
    try:
        source, body = message.split(" - ", 1)
    except (AttributeError, ValueError) as err:
        print("error:", err)
        return None, None
    return source, body


def resolve_sender(raw_source, lookup_fn=None):
    """Resolve chat source and sender, falling back to the raw value."""
    lookup_fn = lookup_fn or lookup_sender
    try:
        return lookup_fn(raw_source)
    except Exception:
        return raw_source, raw_source


def parse_location_body(body):
    """Extract latitude and longitude from a `location:...` body."""
    _prefix, location = body.split(":", 1)
    latitude, longitude = location.split(",", 1)
    return latitude, longitude


def handle_message_body(
    body,
    sender,
    source,
    uts_now,
    parse_message_fn=None,
    parse_location_fn=None,
):
    """Dispatch a text or location body to the matching parser."""
    parse_message_fn = parse_message_fn or parse_message
    parse_location_fn = parse_location_fn or parse_location
    if body.startswith("location"):
        latitude, longitude = parse_location_body(body)
        return parse_location_fn(latitude, longitude, sender)
    return parse_message_fn(body, sender, source, uts_now)


def handshake(client, host, port, routes):
    """Connect, complete DH key exchange, and announce routes. Return salt."""
    client.run(host, port)
    sprime, _sbase, secret = client.dh_send()
    data = client.receive_single()
    salt = client.dh_receive(data, secret, sprime)
    client.send(routes, salt)
    client.receive_single()
    return salt


def decode_verified_message(client, data, salt):
    """Base64-decode a packet and verify its integrity hash."""
    decoded = client.b64_decode(data)
    return client.check_integrity(decoded, salt)


def maybe_reply(send_reply, message, source, settings_obj, send_fn=None):
    """Send a WhatsApp reply when the parser requested one."""
    if not send_reply:
        return False
    sender = send_fn or simple_send
    sender(settings_obj.WA_SRV, settings_obj.WA_PORT, source, message)
    return True


def process_packet(
    client,
    data,
    salt,
    uts_now,
    debug,
    settings_obj,
    send_fn=None,
    lookup_fn=None,
    parse_message_fn=None,
    parse_location_fn=None,
):
    """Handle one inbound packet. Return True when a reply was sent."""
    if not salt:
        print_debug(debug, "RECEIVED MESSAGE WITHOUT HAVING A SALT!")
        print_debug(debug, data)
        return False

    message = decode_verified_message(client, data, salt)
    raw_source, body = split_source_and_body(message)
    if not raw_source:
        return False

    source, sender = resolve_sender(raw_source, lookup_fn=lookup_fn)
    print_debug(
        debug, "SOURCE: {0}, SENDER:{1} Body:{2}".format(source, sender, body)
    )

    try:
        send_reply, reply = handle_message_body(
            body,
            sender,
            source,
            uts_now,
            parse_message_fn=parse_message_fn,
            parse_location_fn=parse_location_fn,
        )
    except Exception as err:
        print_debug(debug, "ERR: {0}".format(err))
        return False

    print_debug(debug, "{0}:{1}".format(send_reply, reply))
    return maybe_reply(
        send_reply, reply, source, settings_obj, send_fn=send_fn
    )


def receive_loop(
    client,
    salt,
    uts_start,
    debug,
    settings_obj,
    time_fn=time.time,
    ignore_seconds=INITIAL_IGNORE_SECONDS,
    send_fn=None,
    lookup_fn=None,
    parse_message_fn=None,
    parse_location_fn=None,
):
    """Read packets until the server disconnects."""
    while True:
        data = client.cli_sock.recv(RECV_BUFFER_SIZE)
        if not data:
            print_debug(debug, "\nDisconnected from server")
            return EXIT_DISCONNECTED

        uts_now = int(time_fn())
        if should_ignore_initial(uts_now, uts_start, ignore_seconds):
            print_debug(
                debug,
                "\nIgnore message due to initial ignore of {0} seconds".format(
                    ignore_seconds
                ),
            )
            continue

        process_packet(
            client,
            data,
            salt,
            uts_now,
            debug,
            settings_obj,
            send_fn=send_fn,
            lookup_fn=lookup_fn,
            parse_message_fn=parse_message_fn,
            parse_location_fn=parse_location_fn,
        )


def run(
    debug=False,
    settings_obj=None,
    groupsetting_model=None,
    client_factory=None,
    time_fn=time.time,
    send_fn=None,
    lookup_fn=None,
    parse_message_fn=None,
    parse_location_fn=None,
):
    """Start the daemon, announce routes, and process inbound messages."""
    settings_obj = settings_obj or settings
    print_debug(
        debug,
        "Starting WhatsApp daemon on {0}:{1}".format(
            settings_obj.WA_SRV, settings_obj.WA_PORT
        ),
    )

    jids = load_group_jids(groupsetting_model=groupsetting_model)
    if debug:
        print_debug(debug, "got jids: {0}".format(",".join(jids)))

    routes = build_announce_routes(jids, debug=debug)
    factory = client_factory or TCPclient
    client = factory()
    if not client:
        return EXIT_RUNTIME_ERROR

    uts_start = int(time_fn())
    try:
        salt = handshake(
            client, settings_obj.WA_SRV, settings_obj.WA_PORT, routes
        )
        return receive_loop(
            client,
            salt,
            uts_start,
            debug,
            settings_obj,
            time_fn=time_fn,
            send_fn=send_fn,
            lookup_fn=lookup_fn,
            parse_message_fn=parse_message_fn,
            parse_location_fn=parse_location_fn,
        )
    finally:
        client.stop()


def main(argv=None):
    """CLI entry point."""
    args = parse_args(argv)
    try:
        return run(debug=args.debug)
    except Exception as exc:
        print("yowsup_dmn failed: {0}".format(exc))
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
