"""Identifier decoding and value comparison — the rules the ledger runs on."""

import pytest

from app.onboarding.checks import (
    canon_city, compare, decode_cin, decode_gstin, gstin_check_digit,
    normalise_website, registrable_domain,
)


class TestCin:
    def test_decodes_a_valid_cin(self):
        d = decode_cin("U65929KA2018PLC116815")
        assert d["valid"] and d["state"] == "Karnataka"
        assert d["incorporation_year"] == 2018
        assert d["company_type"] == "Public limited"
        assert d["listed"] is False

    def test_accepts_an_llpin(self):
        d = decode_cin("ABD-0345")
        assert d["valid"] and d["company_type"] == "Limited liability partnership"
        assert d["incorporation_year"] is None

    @pytest.mark.parametrize("bad", ["", "U123", "X65929KA2018PLC116815", "65929KA2018PLC116815"])
    def test_rejects_malformed(self, bad):
        assert decode_cin(bad)["valid"] is False


class TestGstin:
    def test_valid_gstin_decodes(self):
        d = decode_gstin("29AAACR5055K1Z3")
        assert d["valid"] and d["state"] == "Karnataka"
        assert d["pan"] == "AAACR5055K" and d["pan_holder"] == "Company"

    def test_check_digit_catches_a_typo(self):
        d = decode_gstin("29AAACR5055K1Z9")
        assert d["valid"] is False and "Check digit" in d["error"]

    def test_check_digit_algorithm(self):
        assert gstin_check_digit("29AAACR5055K1Z") == "3"
        assert gstin_check_digit("27AAPFU0939F1Z") == "V"


class TestCompare:
    @pytest.mark.parametrize("a,b", [("Razorpay", "RAZORPAY SOFTWARE PRIVATE LIMITED"),
                                     ("Zerodha", "Zerodha Broking Ltd"),
                                     ("Acme Labs", "acme labs")])
    def test_names_that_should_agree(self, a, b):
        assert compare("name", a, b) == "agree"

    def test_names_that_should_not(self):
        assert compare("name", "Acme Robotics", "Globex Industries") == "disagree"

    def test_city_aliases(self):
        assert compare("city", "Bangalore", "Bengaluru, India") == "agree"
        assert compare("city", "Gurgaon", "Gurugram") == "agree"
        assert compare("city", "Mumbai", "Delhi") == "disagree"

    def test_year_tolerance(self):
        assert compare("year", 2020, 2021) == "agree"
        assert compare("year", 2015, 2020) == "disagree"

    def test_domain_registration_after_founding_is_a_conflict(self):
        # A domain bought years after the company supposedly existed is odd;
        # an older domain is not.
        assert compare("domain_year", 2015, 2020) == "disagree"
        assert compare("domain_year", 2020, 2019) == "agree"

    def test_freeform_never_conflicts(self):
        assert compare("freeform", "one description", "a totally different one") == "neutral"

    def test_missing_values_are_neutral(self):
        assert compare("name", None, "Acme") == "neutral"


class TestDomains:
    @pytest.mark.parametrize("raw,expected", [
        ("https://www.acme.com/about", "acme.com"),
        ("acme.co.in", "acme.co.in"),
        ("https://sub.acme.co.uk", "acme.co.uk"),
    ])
    def test_registrable_domain(self, raw, expected):
        assert registrable_domain(raw) == expected

    def test_normalise_adds_scheme(self):
        assert normalise_website("acme.com") == "https://acme.com"

    def test_canon_city_takes_the_first_part(self):
        assert canon_city("Bengaluru, Karnataka, India") == "bengaluru"
