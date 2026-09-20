import hashlib
import io
from contextlib import redirect_stdout
from datetime import datetime
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from tools import load_video_streams as lvs


SETTINGS = SimpleNamespace(
    WA_ADMIN_NUMBER="491700000000",
    WA_SRV="wa.local",
    WA_PORT=9009,
)
BERLIN = ZoneInfo("Europe/Berlin")


class FakeQuerySet(object):
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.filter_kwargs = None
        self.calls = []

    def filter(self, **kwargs):
        self.filter_kwargs = kwargs
        return self

    def values(self, *fields):
        if not fields:
            return self.rows
        projected = []
        for row in self.rows:
            projected.append({field: row.get(field) for field in fields})
        self.rows = projected
        return self

    def update_or_create(self, **kwargs):
        self.calls.append(kwargs)
        return (SimpleNamespace(pk=len(self.calls)), True)

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)


class FakeModel(object):
    def __init__(self, rows=None):
        self.objects = FakeQuerySet(rows)


def _uts(year, month, day, hour=19, minute=30):
    return int(datetime(year, month, day, hour, minute, tzinfo=BERLIN).timestamp())


def _match(
    match_id,
    matchday,
    home="Eisbaeren Berlin",
    guest="Straubing Tigers",
    date=None,
    video_url="",
    home_short="EBB",
    guest_short="STR",
):
    return {
        "id": match_id,
        "matchday": matchday,
        "date": date if date is not None else 1000 + matchday,
        "video_url": video_url,
        "home_team__team_name": home,
        "home_team__short_name": home_short,
        "guest_team__team_name": guest,
        "guest_team__short_name": guest_short,
    }


VIDEO_HTML = """
<html><body>
<section data-aria-title="Kürzlich hinzugefügt">
  <h2>Kürzlich hinzugefügt</h2>
  <ul class="swiper-wrapper" aria-label="Events: Kürzlich hinzugefügt">
    <li>
      <a href="/event/koelner-haie-grizzlys-wolfsburg/1/1"
         aria-label="Hauptrunde Spieltag 1, Freitag 18. September, Kölner Haie gegen Grizzlys Wolfsburg, PENNY DEL">
        <div class="team-event-content__team">Kölner Haie</div>
        <div class="team-event-content__team">Grizzlys Wolfsburg</div>
      </a>
    </li>
    <li>
      <a href="https://www.magentasport.de/event/die-konferenz-der-penny-del/2/2"
         aria-label="Hauptrunde Spieltag 1, Freitag 18. September, Die Konferenz der PENNY DEL, PENNY DEL">
      </a>
    </li>
    <li>
      <a href="/event/eisbaeren-berlin-straubing-tigers/11660955/446580"
         aria-label="Hauptrunde Spieltag 1, Donnerstag 17. September, Eisbären Berlin gegen Straubing Tigers, PENNY DEL">
        <div class="team-event-content__team">Eisbären Berlin</div>
        <div class="team-event-content__team">Straubing Tigers</div>
      </a>
    </li>
    <li>
      <a href="/event/eisbaeren-berlin-adler-mannheim/11602664/432252"
         aria-label="Finale Spiel 4, Donnerstag 30. April, Eisbären Berlin gegen Adler Mannheim, PENNY DEL">
        <div class="team-event-content__team">Eisbären Berlin</div>
        <div class="team-event-content__team">Adler Mannheim</div>
      </a>
    </li>
  </ul>
</section>
</body></html>
"""

VIDEO_HTML = """
<html><body>
<section data-aria-title="Kürzlich hinzugefügt">
  <h2>Kürzlich hinzugefügt</h2>
  <ul class="swiper-wrapper" aria-label="Events: Kürzlich hinzugefügt">
    <li>
      <a href="/event/koelner-haie-grizzlys-wolfsburg/1/1"
         aria-label="Hauptrunde Spieltag 1, Freitag 18. September, Kölner Haie gegen Grizzlys Wolfsburg, PENNY DEL">
        <div class="team-event-content__team">Kölner Haie</div>
        <div class="team-event-content__team">Grizzlys Wolfsburg</div>
      </a>
    </li>
    <li>
      <a href="https://www.magentasport.de/event/die-konferenz-der-penny-del/2/2"
         aria-label="Hauptrunde Spieltag 1, Freitag 18. September, Die Konferenz der PENNY DEL, PENNY DEL">
      </a>
    </li>
    <li>
      <a href="/event/eisbaeren-berlin-straubing-tigers/11660955/446580"
         aria-label="Hauptrunde Spieltag 1, Donnerstag 17. September, Eisbären Berlin gegen Straubing Tigers, PENNY DEL">
        <div class="team-event-content__team">Eisbären Berlin</div>
        <div class="team-event-content__team">Straubing Tigers</div>
      </a>
    </li>
    <li>
      <a href="/event/eisbaeren-berlin-adler-mannheim/11602664/432252"
         aria-label="Finale Spiel 4, Donnerstag 30. April, Eisbären Berlin gegen Adler Mannheim, PENNY DEL">
        <div class="team-event-content__team">Eisbären Berlin</div>
        <div class="team-event-content__team">Adler Mannheim</div>
      </a>
    </li>
  </ul>
</section>
</body></html>
"""

SHELL_HTML = """
<html><body>
<section data-aria-title="Kürzlich hinzugefügt">
  <h2>Kürzlich hinzugefügt</h2>
  <event-lane-lazy-loader lane-type="event-lane" prop-url="/components/eventLane/12416">
  </event-lane-lazy-loader>
</section>
</body></html>
"""

LANE_PAYLOAD = {
    "data": {
        "data": [
            {
                "type": "teamEvent",
                "target_url": "/event/koelner-haie-grizzlys-wolfsburg/1/1",
                "metadata": {
                    "description_bold": "PENNY DEL",
                    "details": {
                        "home": {"name_full": "Kölner Haie"},
                        "away": {"name_full": "Grizzlys Wolfsburg"},
                    },
                    "scheduled_start": {"original": "2026-09-18 19:30:00"},
                },
            },
            {
                "type": "conferenceEvent",
                "target_url": "/event/die-konferenz-der-penny-del/2/2",
                "metadata": {
                    "description_bold": "PENNY DEL",
                    "scheduled_start": {"original": "2026-09-18 19:30:00"},
                },
            },
            {
                "type": "teamEvent",
                "target_url": "/event/eisbaeren-berlin-straubing-tigers/11660955/446580",
                "metadata": {
                    "description_bold": "PENNY DEL",
                    "details": {
                        "home": {"name_full": "Eisbären Berlin"},
                        "away": {"name_full": "Straubing Tigers"},
                    },
                    "scheduled_start": {
                        "original": "2026-09-17 19:00:00",
                        "iso_date": "2026-09-17T17:00:00.000Z",
                    },
                },
            },
            {
                "type": "teamEvent",
                "target_url": "/event/other-league/3/3",
                "metadata": {
                    "description_bold": "DEL2",
                    "details": {
                        "home": {"name_full": "Eisbären Berlin"},
                        "away": {"name_full": "Adler Mannheim"},
                    },
                    "scheduled_start": {"original": "2026-04-30 19:00:00"},
                },
            },
        ]
    }
}


class LoadVideoStreamsTests(SimpleTestCase):
    def test_parse_args_defaults(self):
        args = lvs.parse_args([])
        self.assertFalse(args.debug)
        self.assertFalse(args.dry_run)
        self.assertIsNone(args.season_id)
        self.assertEqual(args.url, lvs.DEFAULT_VIDEO_LIST_URL)
        self.assertEqual(args.url, "https://www.magentasport.de/del")

    def test_parse_args_reads_flags(self):
        args = lvs.parse_args(
            ["-d", "--dry-run", "--season-id", "4", "--url", "http://videos.test"]
        )
        self.assertTrue(args.debug)
        self.assertTrue(args.dry_run)
        self.assertEqual(args.season_id, 4)
        self.assertEqual(args.url, "http://videos.test")
        self.assertTrue(lvs.parse_args(["--debug"]).debug)

    def test_load_season_id_counts_rows(self):
        season_model = FakeModel([{"id": 1}, {"id": 2}, {"id": 3}])
        self.assertEqual(lvs.load_season_id(season_model=season_model), 3)

    def test_load_matches_projects_team_and_video_fields(self):
        rows = [_match(10, 1), _match(11, 2, video_url="https://already.stored")]
        match_model = FakeModel(rows)
        matches = lvs.load_matches(7, match_model=match_model)
        self.assertEqual(match_model.objects.filter_kwargs, {"season_id": 7})
        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0]["home_team__team_name"], "Eisbaeren Berlin")
        self.assertEqual(matches[1]["video_url"], "https://already.stored")

    def test_matches_missing_video_skips_filled_rows(self):
        missing = lvs.matches_missing_video(
            [
                _match(10, 1),
                _match(11, 2, video_url="https://already.stored"),
                _match(12, 3, video_url=None),
                {"id": 13, "matchday": None, "video_url": ""},
            ]
        )
        self.assertEqual([row["id"] for row in missing], [10, 12])

    def test_fetch_html_uses_requests(self):
        payload = b"<html>videos</html>"
        response = mock.Mock()
        response.content = payload
        get_fn = mock.Mock(return_value=response)
        result = lvs.fetch_html("https://example.test/videos", get_fn=get_fn)
        get_fn.assert_called_once_with(
            "https://example.test/videos",
            timeout=lvs.HTTP_TIMEOUT_SECONDS,
            headers=lvs.HTTP_HEADERS,
        )
        response.raise_for_status.assert_called_once()
        self.assertEqual(result, payload)

    def test_parse_event_label_reads_german_date_and_teams(self):
        parsed = lvs.parse_event_label(
            "Hauptrunde Spieltag 1, Donnerstag 17. September, "
            "Eisbären Berlin gegen Straubing Tigers, PENNY DEL"
        )
        self.assertEqual(parsed["weekday"], "Donnerstag")
        self.assertEqual(parsed["day"], 17)
        self.assertEqual(parsed["month"], 9)
        self.assertEqual(parsed["home"], "Eisbären Berlin")
        self.assertEqual(parsed["guest"], "Straubing Tigers")

    def test_parse_event_label_skips_conference_and_other_competitions(self):
        self.assertIsNone(
            lvs.parse_event_label(
                "Hauptrunde Spieltag 1, Freitag 18. September, "
                "Die Konferenz der PENNY DEL, PENNY DEL"
            )
        )
        self.assertIsNone(
            lvs.parse_event_label(
                "Freitag 18. September, Eisbären Berlin gegen Straubing Tigers, DEL2"
            )
        )

    def test_name_similarity_folds_umlauts_and_tokens(self):
        self.assertEqual(lvs.name_similarity("Eisbären Berlin", "Eisbaeren Berlin"), 1.0)
        self.assertGreaterEqual(lvs.name_similarity("Kölner Haie", "Koelner Haie"), 0.99)
        self.assertGreaterEqual(
            lvs.name_similarity("EHC Red Bull München", "EHC Muenchen"), 0.92
        )
        self.assertLess(lvs.name_similarity("Eisbären Berlin", "Adler Mannheim"), 0.5)

    def test_extract_video_entries_keeps_penny_del_team_events(self):
        soup = lvs.parse_soup(VIDEO_HTML)
        entries = lvs.extract_video_entries(soup)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].home, "Kölner Haie")
        self.assertEqual(entries[1].home, "Eisbären Berlin")
        self.assertEqual(entries[1].guest, "Straubing Tigers")
        self.assertEqual(entries[1].day, 17)
        self.assertEqual(entries[1].month, 9)
        self.assertEqual(
            entries[1].link,
            "https://www.magentasport.de/event/eisbaeren-berlin-straubing-tigers/11660955/446580",
        )
        self.assertEqual(entries[2].month, 4)
        self.assertEqual(entries[2].day, 30)

    def test_generate_api_token_hashes_salt_day_and_path(self):
        now_uts = int(datetime(2026, 9, 20, 8, 0, tzinfo=BERLIN).timestamp())
        path = "/api/v3/components/eventLane/12416"
        token = lvs.generate_api_token(path, now_uts=now_uts)
        day_unix = lvs.token_day_unix(now_uts=now_uts)
        expected = hashlib.sha256(
            "{0}{1}{2}".format(lvs.API_TOKEN_SALT, day_unix, path).encode("utf-8")
        ).hexdigest()
        self.assertEqual(token, expected)
        self.assertEqual(len(token), 64)

    def test_find_recent_lane_prop_url_reads_lazy_loader(self):
        soup = lvs.parse_soup(SHELL_HTML)
        self.assertEqual(
            lvs.find_recent_lane_prop_url(soup),
            "/components/eventLane/12416",
        )
        self.assertIsNone(lvs.find_recent_events_list(soup))

    def test_extract_video_entries_from_payload_skips_conference(self):
        entries = lvs.extract_video_entries_from_payload(LANE_PAYLOAD)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].home, "Kölner Haie")
        self.assertEqual(entries[1].home, "Eisbären Berlin")
        self.assertEqual(entries[1].guest, "Straubing Tigers")
        self.assertEqual(entries[1].day, 17)
        self.assertEqual(entries[1].month, 9)
        self.assertEqual(
            entries[1].link,
            "https://www.magentasport.de/event/eisbaeren-berlin-straubing-tigers/11660955/446580",
        )

    def test_load_video_entries_uses_html_when_list_is_present(self):
        json_get_fn = mock.Mock()
        entries = lvs.load_video_entries(VIDEO_HTML, json_get_fn=json_get_fn)
        self.assertEqual(len(entries), 3)
        json_get_fn.assert_not_called()

    def test_load_video_entries_fetches_lane_from_unrendered_shell(self):
        response = mock.Mock()
        response.json.return_value = LANE_PAYLOAD
        json_get_fn = mock.Mock(return_value=response)
        now_uts = int(datetime(2026, 9, 20, 8, 0, tzinfo=BERLIN).timestamp())
        entries = lvs.load_video_entries(
            SHELL_HTML,
            json_get_fn=json_get_fn,
            now_uts=now_uts,
        )
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[1].home, "Eisbären Berlin")
        token = lvs.generate_api_token(
            "/api/v3/components/eventLane/12416",
            now_uts=now_uts,
        )
        json_get_fn.assert_called_once_with(
            "https://www.magentasport.de/api/v3/components/eventLane/12416",
            params={"token": token},
            timeout=lvs.HTTP_TIMEOUT_SECONDS,
            headers=lvs.JSON_HEADERS,
        )

    def test_select_video_updates_fuzzy_matches_date_and_teams(self):
        soup = lvs.parse_soup(VIDEO_HTML)
        entries = lvs.extract_video_entries(soup)
        matches = [
            _match(100, 1, date=_uts(2026, 9, 17)),
            _match(
                101,
                52,
                home="Eisbaeren Berlin",
                guest="Adler Mannheim",
                date=_uts(2026, 4, 30),
                guest_short="MAN",
            ),
            _match(
                102,
                2,
                home="Eisbaeren Berlin",
                guest="Straubing Tigers",
                date=_uts(2026, 4, 4),
            ),
        ]
        updates = lvs.select_video_updates(entries, matches)
        self.assertEqual(
            [(item.match_id, item.matchday) for item in updates],
            [(100, 1), (101, 52)],
        )
        self.assertIn("eisbaeren-berlin-straubing-tigers", updates[0].link)
        self.assertIn("eisbaeren-berlin-adler-mannheim", updates[1].link)

    def test_select_video_updates_skips_filled_and_unrelated_matches(self):
        entries = [
            lvs.VideoEntry(
                "https://www.magentasport.de/event/a",
                "Eisbären Berlin",
                "Straubing Tigers",
                17,
                9,
                "Donnerstag",
                "label",
            )
        ]
        updates = lvs.select_video_updates(
            entries,
            [
                _match(200, 1, home="Kölner Haie", guest="Grizzlys Wolfsburg", date=_uts(2026, 9, 17)),
                _match(201, 2, date=_uts(2026, 9, 18)),
            ],
        )
        self.assertEqual(updates, [])

    def test_persist_video_urls_calls_update_or_create(self):
        fake_match = FakeModel()
        updates = [
            lvs.VideoUpdate(100, 12, "https://magenta.test/a", "Eisbären Berlin", "Straubing")
        ]
        saved = lvs.persist_video_urls(updates, match_model=fake_match)
        self.assertEqual(saved, updates)
        self.assertEqual(
            fake_match.objects.calls,
            [{"id": 100, "defaults": {"video_url": "https://magenta.test/a"}}],
        )

    def test_persist_video_urls_dry_run_prints_without_writing(self):
        fake_match = FakeModel()
        updates = [
            lvs.VideoUpdate(100, 12, "https://magenta.test/a", "Eisbären Berlin", "Straubing")
        ]
        output = io.StringIO()
        with redirect_stdout(output):
            saved = lvs.persist_video_urls(updates, match_model=fake_match, dry_run=True)
        self.assertEqual(saved, updates)
        self.assertEqual(fake_match.objects.calls, [])
        self.assertIn("dry-run video Spieltag 12: https://magenta.test/a", output.getvalue())

    def test_format_admin_message_lists_new_videos(self):
        message = lvs.format_admin_message(
            ["Spieltag: 12: https://magenta.test/a", "Spieltag: 8: https://magenta.test/b"]
        )
        self.assertIn("*load_video_streams.py*", message)
        self.assertIn("Neue Videos eingetragen:", message)
        self.assertIn("Spieltag: 12: https://magenta.test/a", message)

    def test_whatsapp_configured_requires_admin_number(self):
        self.assertTrue(lvs.whatsapp_configured(SETTINGS))
        self.assertFalse(lvs.whatsapp_configured(SimpleNamespace(WA_SRV="x", WA_PORT=1)))
        self.assertFalse(lvs.whatsapp_configured(SimpleNamespace()))

    def test_dispatch_whatsapp_sends_admin_message(self):
        sent = []
        sent_flag = lvs.dispatch_whatsapp(
            SETTINGS,
            SETTINGS.WA_ADMIN_NUMBER,
            "hello",
            send_fn=lambda *args: sent.append(args),
        )
        self.assertTrue(sent_flag)
        self.assertEqual(
            sent,
            [(SETTINGS.WA_SRV, SETTINGS.WA_PORT, SETTINGS.WA_ADMIN_NUMBER, "hello")],
        )

    def test_notify_admin_dry_run_prints_without_whatsapp_settings(self):
        sent = []
        output = io.StringIO()
        with redirect_stdout(output):
            sent_flag = lvs.notify_admin(
                ["Spieltag: 12: https://magenta.test/a"],
                SimpleNamespace(),
                send_fn=lambda *args: sent.append(args),
                dry_run=True,
            )
        self.assertTrue(sent_flag)
        self.assertEqual(sent, [])
        printed = output.getvalue()
        self.assertIn("dry-run whatsapp WA_ADMIN_NUMBER:", printed)
        self.assertIn("Neue Videos eingetragen:", printed)

    def test_notify_admin_skips_when_there_are_no_videos(self):
        sent = []
        sent_flag = lvs.notify_admin(
            [],
            SETTINGS,
            send_fn=lambda *args: sent.append(args),
        )
        self.assertFalse(sent_flag)
        self.assertEqual(sent, [])

    def test_run_stores_videos_and_notifies_admin(self):
        fake_match = FakeModel()
        sent = []
        saved = lvs.run(
            argv=["--season-id", "5"],
            now_uts=2000,
            matches=[
                _match(100, 1, date=_uts(2026, 9, 17)),
                _match(
                    101,
                    52,
                    home="Eisbaeren Berlin",
                    guest="Adler Mannheim",
                    date=_uts(2026, 4, 30),
                    guest_short="MAN",
                ),
                _match(102, 9, video_url="https://old"),
            ],
            html=VIDEO_HTML,
            match_model=fake_match,
            settings_obj=SETTINGS,
            send_fn=lambda *args: sent.append(args),
        )
        self.assertEqual(
            [(item.match_id, item.matchday) for item in saved],
            [(100, 1), (101, 52)],
        )
        self.assertEqual(len(fake_match.objects.calls), 2)
        self.assertEqual(len(sent), 1)
        _srv, _port, recipient, message = sent[0]
        self.assertEqual(recipient, SETTINGS.WA_ADMIN_NUMBER)
        self.assertIn("Neue Videos eingetragen:", message)
        self.assertIn("Spieltag: 1: https://www.magentasport.de/event/", message)

    def test_run_stores_videos_from_unrendered_shell(self):
        fake_match = FakeModel()
        sent = []
        saved = lvs.run(
            argv=["--season-id", "5"],
            now_uts=2000,
            matches=[_match(100, 1, date=_uts(2026, 9, 17))],
            html=SHELL_HTML,
            lane_payload=LANE_PAYLOAD,
            match_model=fake_match,
            settings_obj=SETTINGS,
            send_fn=lambda *args: sent.append(args),
        )
        self.assertEqual([(item.match_id, item.matchday) for item in saved], [(100, 1)])
        self.assertEqual(len(sent), 1)
        self.assertIn("eisbaeren-berlin-straubing-tigers", saved[0].link)

    def test_run_dry_run_prints_without_writing_or_sending(self):
        fake_match = FakeModel()
        sent = []
        output = io.StringIO()
        with redirect_stdout(output):
            saved = lvs.run(
                argv=["--dry-run", "--season-id", "5"],
                now_uts=2000,
                matches=[_match(100, 1, date=_uts(2026, 9, 17))],
                html=VIDEO_HTML,
                match_model=fake_match,
                settings_obj=SETTINGS,
                send_fn=lambda *args: sent.append(args),
            )
        self.assertEqual(len(saved), 1)
        self.assertEqual(fake_match.objects.calls, [])
        self.assertEqual(sent, [])
        printed = output.getvalue()
        self.assertIn("dry-run video Spieltag 1:", printed)
        self.assertIn("dry-run whatsapp {0}:".format(SETTINGS.WA_ADMIN_NUMBER), printed)

    def test_run_skips_whatsapp_when_settings_missing(self):
        sent = []
        output = io.StringIO()
        with redirect_stdout(output):
            saved = lvs.run(
                argv=["--season-id", "5"],
                now_uts=2000,
                matches=[_match(100, 1, date=_uts(2026, 9, 17))],
                html=VIDEO_HTML,
                match_model=FakeModel(),
                settings_obj=SimpleNamespace(),
                send_fn=lambda *args: sent.append(args),
            )
        self.assertEqual(len(saved), 1)
        self.assertEqual(sent, [])
        self.assertIn("skipped whatsapp: WhatsApp settings missing", output.getvalue())

    def test_run_debug_logs_function_calls(self):
        output = io.StringIO()
        with redirect_stdout(output):
            lvs.run(
                argv=["--debug", "--season-id", "5"],
                now_uts=2000,
                matches=[_match(100, 1, date=_uts(2026, 9, 17))],
                html=VIDEO_HTML,
                match_model=FakeModel(),
                settings_obj=SETTINGS,
                send_fn=lambda *args: None,
            )
        printed = output.getvalue()
        for snippet in (
            "parse_args",
            "run()",
            "matches_missing_video",
            "parse_soup",
            "load_video_entries",
            "extract_video_entries",
            "find_recent_events_list",
            "parse_event_label",
            "name_similarity",
            "select_video_updates",
            "persist_video_urls",
            "format_video_line",
            "whatsapp_configured",
            "notify_admin",
            "dispatch_whatsapp",
            "format_admin_message",
        ):
            self.assertIn(snippet, printed)

    def test_main_returns_runtime_error_on_failure(self):
        with mock.patch.object(lvs, "run", side_effect=RuntimeError("boom")):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = lvs.main([])
        self.assertEqual(rc, lvs.EXIT_RUNTIME_ERROR)
        self.assertIn("load_video_streams failed: boom", output.getvalue())

    def test_main_reports_stored_count(self):
        with mock.patch.object(
            lvs,
            "run",
            return_value=[
                lvs.VideoUpdate(1, 12, "https://magenta.test/a", "Eisbären Berlin", "Straubing")
            ],
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = lvs.main([])
        self.assertEqual(rc, lvs.EXIT_SUCCESS)
        self.assertIn("stored 1 video urls", output.getvalue())
