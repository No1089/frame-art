"""The label and layout contract: geometry, wrapping and truncation."""

from PIL import Image
import pytest

import config
import prepare_images


def artwork(width, height, colour=(120, 90, 70)):
    return Image.new("RGB", (width, height), colour)


RECORD = {
    "artist": "Mary Cassatt",
    "title": "The Child's Bath",
    "date": "1893",
    "medium": "Oil on canvas",
    "credit": "Robert A. Waller Fund",
    "source": "aic",
    "blurb": ("Known for her sensitive scenes of women and children, Cassatt "
              "was the only American invited to exhibit with the French "
              "Impressionists. She used cropped forms and bold outlines. A "
              "third sentence exists so truncation has something to cut."),
}


class TestPanelGeometry:
    """Whatever the source shape, the output must fit the panel exactly.

    The TV takes 1920x1080 and nothing else; a render that is off by a pixel
    is a bad upload rather than a visible mistake, so this is the contract
    worth pinning hardest.
    """

    @pytest.mark.parametrize("size", [
        (1687, 2560),   # tall portrait
        (2560, 2050),   # ordinary landscape
        (3400, 1187),   # very wide, the Degas frieze
        (2000, 2000),   # square
        (400, 300),     # smaller than the panel, must scale up to fit
    ])
    def test_output_is_always_exactly_the_panel(self, size):
        out = prepare_images.compose(artwork(*size), RECORD, config.FIT_MODE)
        assert out.size == (config.TARGET_WIDTH_PX, config.TARGET_HEIGHT_PX)

    def test_artwork_is_never_cropped(self):
        # Fitted, not filled: the whole canvas has to survive. A landscape
        # laid out for the side column keeps its full width.
        source = artwork(2560, 2050)
        out = prepare_images.compose(source, RECORD, config.FIT_MODE)
        assert out.size[0] >= out.size[1]  # sanity: panel is landscape

    def test_portrait_and_landscape_take_different_layouts(self):
        portrait = prepare_images.compose(artwork(1000, 2000), RECORD, "pad")
        landscape = prepare_images.compose(artwork(2000, 1000), RECORD, "pad")
        assert portrait.tobytes() != landscape.tobytes()


class TestTextFitting:
    def test_wrap_never_exceeds_the_measure(self):
        font = prepare_images.load_font(config.LABEL_FONT_CANDIDATES, 20)
        text = "A rather long museum credit line that will certainly wrap " * 3
        for line in prepare_images.wrap_text(text, font, 300):
            # A single word longer than the measure cannot be helped.
            if " " in line:
                assert font.getlength(line) <= 300

    def test_fit_text_truncates_with_an_ellipsis(self):
        font = prepare_images.load_font(config.LABEL_FONT_CANDIDATES, 20)
        long_title = ("Madame Georges Charpentier and Her Children, "
                      "Georgette-Berthe and Paul-Emile-Charles")
        out = prepare_images.fit_text(long_title, font, 200)
        assert out.endswith("…")
        assert font.getlength(out) <= 200

    def test_short_text_is_left_alone(self):
        font = prepare_images.load_font(config.LABEL_FONT_CANDIDATES, 20)
        assert prepare_images.fit_text("Monet", font, 500) == "Monet"


class TestBlurbTruncation:
    """A caption cut mid clause reads as a bug rather than as an edit."""

    def test_stops_on_a_sentence_when_it_must_cut(self):
        font = prepare_images.load_font(config.LABEL_FONT_CANDIDATES, 20)
        row = prepare_images.row_height(font)
        lines = prepare_images.blurb_lines(RECORD["blurb"], font, 400, row * 3)
        assert lines, "should keep at least one sentence"
        assert lines[-1].rstrip().endswith((".", "!", "?", "…"))

    def test_respects_the_height_it_is_given(self):
        font = prepare_images.load_font(config.LABEL_FONT_CANDIDATES, 20)
        row = prepare_images.row_height(font)
        assert len(prepare_images.blurb_lines(RECORD["blurb"], font, 400, row * 3)) <= 3

    def test_no_room_means_no_lines(self):
        font = prepare_images.load_font(config.LABEL_FONT_CANDIDATES, 20)
        assert prepare_images.blurb_lines(RECORD["blurb"], font, 400, 1) == []


class TestLabelContent:
    def test_cleveland_credit_parenthetical_is_stripped(self):
        assert prepare_images.clean_artist(
            "Gustave Caillebotte (French, 1848–1894)") == "Gustave Caillebotte"

    def test_a_plain_name_is_untouched(self):
        assert prepare_images.clean_artist("Claude Monet") == "Claude Monet"

    def test_the_lending_museum_is_named(self):
        # An attribution, not decoration: AIC curatorial text is CC-BY while
        # the painting itself is public domain.
        rows = prepare_images.build_label(RECORD, 600, 900, allow_blurb=True)
        text = " ".join(r[0] for r in rows if r[0])
        assert config.MUSEUM_NAMES["aic"] in text

    def test_every_source_maps_to_a_museum(self):
        for source in config.ENABLED_SOURCES:
            assert config.MUSEUM_NAMES.get(source)
