"""Rotation state, the interval the TV actually accepts, and stills naming."""

import json
import pytest

import config
import export_stills
import frame_control


@pytest.fixture
def state(tmp_path, monkeypatch):
    """Point the rotation state at a temp file, not the real library."""
    monkeypatch.setattr(frame_control, "STATE_FILE", str(tmp_path / "state.json"))
    return tmp_path / "state.json"


MANIFEST = {f"/prepared/{i}.jpg": {"content_id": f"MY_F{i:04d}",
                                   "artist": "Claude Monet",
                                   "title": f"Work {i}"} for i in range(1, 6)}


class TestPicking:
    def test_never_repeats_the_piece_already_up(self, state):
        # At a three minute cadence a plain random choice lands on the same
        # painting noticeably often, which reads as the rotation being stuck.
        frame_control._save_state(last_content_id="MY_F0003")
        for _ in range(40):
            content_id, _ = frame_control.pick(MANIFEST)
            assert content_id != "MY_F0003"

    def test_a_single_work_is_still_shown(self, state):
        only = {"/prepared/1.jpg": {"content_id": "MY_F0001"}}
        frame_control._save_state(last_content_id="MY_F0001")
        content_id, _ = frame_control.pick(only)
        assert content_id == "MY_F0001"

    def test_empty_manifest_picks_nothing(self, state):
        assert frame_control.pick({}) == (None, {})

    def test_entries_without_a_content_id_are_ignored(self, state):
        # A null id used to reach the manifest when an upload acknowledgement
        # was late; selecting one would fail.
        mixed = {"a": {"content_id": None}, "b": {"content_id": "MY_F0009"}}
        for _ in range(10):
            assert frame_control.pick(mixed)[0] == "MY_F0009"


class TestCadence:
    def test_not_due_immediately_after_showing(self, state):
        frame_control._save_state(last_rotate_at=frame_control.time.time())
        assert not frame_control.due(3)

    def test_due_once_the_interval_has_passed(self, state):
        frame_control._save_state(
            last_rotate_at=frame_control.time.time() - 4 * 60)
        assert frame_control.due(3)

    def test_due_when_nothing_has_ever_been_shown(self, state):
        assert frame_control.due(3)


class TestArtModeTransition:
    """Entering art mode must change the picture at once.

    Otherwise pressing power leaves an Art Store piece up until the interval
    happens to come round, which is the thing that was actually annoying.
    """

    def test_transition_into_art_mode_is_detected(self, state):
        frame_control._save_state(artmode_on=False)
        assert frame_control.entering_artmode(True)

    def test_staying_in_art_mode_is_not_a_transition(self, state):
        frame_control._save_state(artmode_on=True)
        assert not frame_control.entering_artmode(True)

    def test_leaving_art_mode_is_not_a_transition(self, state):
        frame_control._save_state(artmode_on=True)
        assert not frame_control.entering_artmode(False)

    def test_the_observation_is_remembered(self, state):
        frame_control.entering_artmode(True)
        assert json.loads(state.read_text())["artmode_on"] is True


class TestSlideshowIntervals:
    """The TV accepts four values and rejects everything else with error -7.

    They are exactly the four options in its own slideshow menu, so this is
    a fixed set rather than a range.
    """

    def test_the_accepted_set_is_what_was_measured(self):
        assert config.SLIDESHOW_INTERVALS == [3, 15, 60, 1440]

    @pytest.mark.parametrize("bad", [1, 5, 10, 30, 120, 720])
    def test_plausible_but_rejected_values_are_not_offered(self, bad):
        assert bad not in config.SLIDESHOW_INTERVALS

    def test_the_rotation_cadence_is_one_the_tv_would_accept(self):
        # Not required, since we drive rotation ourselves, but a mismatch
        # here usually means someone misunderstood which knob they turned.
        assert config.ROTATE_MIN_INTERVAL_MIN in config.SLIDESHOW_INTERVALS


class TestStillNames:
    def test_named_for_a_human_reading_the_share(self):
        name = export_stills.readable_name(
            {"artist": "Claude Monet", "title": "Water Lilies",
             "source": "aic", "source_id": "16568"}, {})
        assert name == "Claude Monet - Water Lilies.jpg"

    def test_cleveland_parenthetical_is_stripped_here_too(self):
        name = export_stills.readable_name(
            {"artist": "Edgar Degas (French, 1834–1917)", "title": "Jockey",
             "source": "cma", "source_id": "1"}, {})
        assert name.startswith("Edgar Degas - Jockey")

    def test_a_collision_is_disambiguated_not_overwritten(self):
        record = {"artist": "Claude Monet", "title": "Water Lilies",
                  "source": "met", "source_id": "999"}
        taken = {"Claude Monet - Water Lilies.jpg"}
        name = export_stills.readable_name(record, taken)
        assert name not in taken
        assert "met-999" in name

    def test_a_hostile_title_cannot_escape_the_directory(self, tmp_path):
        """Titles come from museum APIs, so treat them as untrusted input.

        The property that matters is not the absence of dots, which are
        harmless on their own, but that the name resolves to a file directly
        inside the destination.
        """
        name = export_stills.readable_name(
            {"artist": "A/B", "title": "../../etc/passwd",
             "source": "aic", "source_id": "1"}, {})
        assert "/" not in name and "\\" not in name
        assert (tmp_path / name).resolve().parent == tmp_path.resolve()

    def test_a_title_of_only_punctuation_still_yields_a_filename(self):
        name = export_stills.readable_name(
            {"artist": "...", "title": "...",
             "source": "aic", "source_id": "1"}, {})
        assert name.endswith(".jpg") and len(name) > len(".jpg")
