"""Unit tests for the agents' shared output models (no network, no LLM)."""

import pytest
from pydantic import ValidationError

from biosciences_temporal.agents.models import GeneInfo

pytestmark = pytest.mark.unit

TP53 = {"hgnc_id": "HGNC:11998", "symbol": "TP53", "name": "tumor protein p53"}


def test_gene_info_accepts_hgnc_curie():
    assert GeneInfo(**TP53).hgnc_id == "HGNC:11998"


@pytest.mark.parametrize("bad_id", ["NOT_FOUND", "11998", "HGNC:", "HGNC:TP53", "hgnc:11998", ""])
def test_gene_info_rejects_non_hgnc_id(bad_id):
    # AGE-743: the resolve agent returned GeneInfo(hgnc_id="NOT_FOUND") for an
    # unknown symbol, which validated and read as a successful resolution.
    with pytest.raises(ValidationError):
        GeneInfo(**{**TP53, "hgnc_id": bad_id})


def test_gene_info_location_is_optional():
    assert GeneInfo(**TP53).location is None
    assert GeneInfo(**TP53, location="17p13.1").location == "17p13.1"
