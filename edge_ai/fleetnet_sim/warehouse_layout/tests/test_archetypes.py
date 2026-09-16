import pytest

from fleetnet_layout.config.enums import Archetype, ScaleClass
from fleetnet_layout.generation.generator import LayoutGenerationError, generate_layout
from fleetnet_layout.generation.sampling import SamplingOverrides

ALL_ARCHETYPES = list(Archetype)


@pytest.mark.parametrize("archetype", ALL_ARCHETYPES)
def test_archetype_produces_at_least_one_valid_layout(archetype):
    # Pinned to small/medium scale to keep the suite fast — large/very_large
    # layouts (hundreds of aisles) are exercised separately in the
    # integration-style demonstration script, not on every test run.
    successes = 0
    for seed in range(20):
        scale = ScaleClass.SMALL if seed % 2 == 0 else ScaleClass.MEDIUM
        try:
            layout = generate_layout(seed, SamplingOverrides(archetype=archetype, scale_class=scale))
            if layout.validation.valid:
                successes += 1
        except LayoutGenerationError:
            continue
    assert successes >= 1, f"{archetype} produced zero valid layouts across 20 seeds"


@pytest.mark.parametrize("industry", ["ecommerce", "cold_storage", "manufacturing"])
def test_industry_conditioned_generation_works(industry):
    from fleetnet_layout.config.enums import IndustryType

    layout = generate_layout(7, SamplingOverrides(archetype=Archetype.GRID, industry_type=IndustryType(industry)))
    assert layout.config.warehouse.industry_type.value == industry
    assert layout.validation.valid
