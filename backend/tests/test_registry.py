"""India's company registry: the local copy and the live fallback."""

import pytest

from app.registry import store


@pytest.mark.registry
class TestLocalCopy:
    @pytest.fixture(autouse=True)
    def _needs_import(self):
        if not store.available():
            pytest.skip("registry.db has not been imported")

    def test_lookup_by_cin(self):
        rec = store.get_local("U65929KA2018PLC116815")
        assert rec and rec["name"] == "ZERODHA BROKING LIMITED"
        assert rec["status"] == "Active" and rec["registered"] == "2018-09-25"

    def test_name_search_ranks_the_exact_match_first(self):
        hits = store.search_local("zerodha broking", limit=5)
        assert hits and hits[0]["name"] == "ZERODHA BROKING LIMITED"

    def test_search_is_prefix_friendly(self):
        assert store.search_local("razorpay soft", limit=3), "typeahead should match a partial word"

    def test_unknown_cin_is_absent(self):
        assert store.get_local("U00000KA2010PTC000000") is None

    def test_city_is_derived_from_the_registered_address(self):
        rec = store.get_local("U65929KA2018PLC116815")
        assert rec["city"] == "Bengaluru"

    def test_stats_report_completeness(self):
        stats = store.stats()
        assert stats["available"] and stats["companies"] > 1000


class TestAddressParsing:
    @pytest.mark.parametrize("address,expected", [
        ("29/9, DABRI PALAM ROAD VIJAY ENCLAVE,NEW DELHI,South West Delhi,Delhi,110045-India", "Delhi"),
        ("3rd Floor, M3M Urbana,sector 67,Gurgaon,Haryana,India-122102", "Gurugram"),
        ("153/154, 4th Cross, J.P NAGAR, BANGALORE,Bangalore,Karnataka,560078-India", "Bengaluru"),
        ("", None),
    ])
    def test_city_from_address(self, address, expected):
        assert store.city_from_address(address) == expected


class TestNameVariants:
    def test_guesses_the_usual_legal_suffixes(self):
        variants = store.name_variants("Acme Robotics")
        assert "ACME ROBOTICS PRIVATE LIMITED" in variants
        assert "ACME ROBOTICS LIMITED" in variants

    def test_strips_an_existing_suffix_first(self):
        assert "ACME PRIVATE LIMITED" in store.name_variants("Acme Pvt Ltd")


@pytest.mark.network
class TestLiveApi:
    @pytest.mark.asyncio_compatible
    def test_live_cin_lookup(self):
        import asyncio

        record, how = asyncio.run(store.lookup_cin("U65929KA2018PLC116815"))
        assert record and record["name"] == "ZERODHA BROKING LIMITED"
        assert how in ("local", "live")
