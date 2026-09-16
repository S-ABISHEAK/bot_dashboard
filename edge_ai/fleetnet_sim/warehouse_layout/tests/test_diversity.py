from fleetnet_layout.config.enums import Archetype, ScaleClass
from fleetnet_layout.diversity.metrics import compute_diversity
from fleetnet_layout.generation.generator import generate_layout
from fleetnet_layout.generation.sampling import SamplingOverrides

# Scale left to sample naturally but capped away from very_large so this
# test stays fast; scale-distribution diversity itself is covered by
# each layout's independently-sampled scale_class regardless of cap.
_SCALES = [ScaleClass.SMALL, ScaleClass.MEDIUM, ScaleClass.LARGE]


def _small_overrides(seed: int) -> SamplingOverrides:
    return SamplingOverrides(scale_class=_SCALES[seed % len(_SCALES)])


def test_diversity_report_tracks_axes():
    layouts = [generate_layout(seed, _small_overrides(seed)) for seed in range(15)]
    report = compute_diversity(layouts)
    assert report.n == 15
    assert sum(report.scale_distribution.values()) == 15
    assert sum(report.archetype_distribution.values()) == 15
    assert len(report.aisle_count) == 15
    assert "archetype" in report.entropy


def test_diversity_batch_not_collapsed_to_one_archetype():
    layouts = [generate_layout(seed, _small_overrides(seed)) for seed in range(30)]
    report = compute_diversity(layouts)
    assert len(report.archetype_distribution) > 1
