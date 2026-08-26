"""Regressions for the three museum quirks that fail silently."""

import config
import fetch_art


class TestMetParameterOrder:
    """The Met only honours filters when q is the first parameter.

    With q trailing it ignores the department and date window and returns a
    plausible result set anyway: 241 hits instead of 12, all of them real
    paintings, none of them filtered. Nothing errors, so only a test that
    looks at the parameter order can catch a regression here.
    """

    def test_q_leads_every_query(self):
        queries = fetch_art.met_queries(config.CATEGORIES["impressionism"],
                                        [11, 21])
        assert queries, "a preset with hints should build queries"
        for params, _ in queries:
            assert params[0][0] == "q", f"q must lead, got {params[0][0]!r}"

    def test_params_are_ordered_pairs_not_a_dict(self):
        # A dict would let a later refactor reorder them invisibly.
        params, _ = fetch_art.met_queries(config.CATEGORIES["ukiyo-e"], [6])[0]
        assert isinstance(params, list)
        assert all(isinstance(pair, tuple) for pair in params)

    def test_every_named_department_is_queried(self):
        # Only department_ids[0] used to be used, silently discarding the
        # second name in every two-department preset.
        preset = config.CATEGORIES["impressionism"]
        queries = fetch_art.met_queries(preset, [11, 21])
        seen = {dict(p).get("departmentId") for p, _ in queries}
        assert seen == {11, 21}

    def test_artist_hint_is_also_the_post_filter(self):
        # Without it a fuzzy match on a hint drags in anything: an Egyptian
        # Book of the Dead once scored highly for "Albert Bierstadt".
        queries = fetch_art.met_queries(config.CATEGORIES["impressionism"], [11])
        hinted = [(p, f) for p, f in queries if f]
        assert hinted, "artist hints should produce filtered queries"
        for params, artist_filter in hinted:
            assert dict(params)["q"] == artist_filter


class TestAicImageUrl:
    """AIC returns 403 for full/full and full/max, so the size is mandatory.

    The region segment is equally mandatory and easy to lose: dropping
    "full/" while adding an explicit size turns every download into a 403.
    """

    def test_url_has_region_then_size(self):
        url = fetch_art.aic_image_url("some-image-id")
        assert f"/full/{config.AIC_IMAGE_SIZE}/0/default.jpg" in url

    def test_size_is_never_full_or_max(self):
        assert config.AIC_IMAGE_SIZE not in ("full", "max")
        url = fetch_art.aic_image_url("x")
        assert "/full/full/" not in url and "/full/max/" not in url


class TestAicQueryShape:
    def test_subjects_match_the_keyword_facet_exactly(self):
        must = fetch_art.aic_must(config.THEMES[10])
        terms = [c["terms"] for c in must if "terms" in c]
        assert {"subject_titles.keyword"} == {k for t in terms for k in t}

    def test_public_domain_is_always_required(self):
        for preset in list(config.CATEGORIES.values()) + list(config.THEMES.values()):
            must = fetch_art.aic_must(preset)
            assert {"term": {"is_public_domain": True}} in must


class TestCmaDerivative:
    """Cleveland's "full" is a preservation TIFF; one was 483 MB."""

    def test_full_is_never_chosen(self):
        images = {"full": {"url": "master.tif"},
                  "print": {"url": "print.jpg"},
                  "web": {"url": "web.jpg"}}
        assert fetch_art.cma_best_image(images)["url"] == "print.jpg"

    def test_full_is_not_even_a_fallback(self):
        assert "full" not in config.CMA_IMAGE_PREFERENCE
        assert fetch_art.cma_best_image({"full": {"url": "master.tif"}}) is None

    def test_missing_urls_are_skipped(self):
        images = {"print": {}, "web": {"url": "web.jpg"}}
        assert fetch_art.cma_best_image(images)["url"] == "web.jpg"


class TestTextCleaning:
    def test_no_space_before_punctuation_after_stripping_tags(self):
        # "<em>The Child's Bath</em>, one of" left "Bath , one of".
        out = fetch_art.plain_text("<em>The Child's Bath</em>, one of her works.")
        assert " ," not in out
        assert out == "The Child's Bath, one of her works."

    def test_entities_are_decoded_and_whitespace_collapsed(self):
        assert fetch_art.plain_text("<p>a &amp;  b</p>\n\n<p>c</p>") == "a & b c"

    def test_empty_input_is_empty_output(self):
        assert fetch_art.plain_text(None) == ""
        assert fetch_art.plain_text("") == ""
