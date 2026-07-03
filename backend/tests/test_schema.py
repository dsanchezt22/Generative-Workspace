"""Schema tests for DataSource (R-701/R-704 live-data framework): validation
bounds, and the single-value display components that may carry a data_source
binding (Metric, Kpi, Ring, Gauge, ProgressBar)."""

import pytest
from pydantic import ValidationError
from src.schema import DataSource, Gauge, Kpi, Metric, ProgressBar, Ring


def test_metric_with_valid_data_source_validates():
    m = Metric(
        id="m1",
        label="Temp",
        source_component_id="x",
        data_source=DataSource(provider="weather", query={"place": "Berlin"}),
    )
    assert m.data_source is not None
    assert m.data_source.provider == "weather"
    assert m.data_source.refresh_secs == 600  # default


def test_metric_invalid_provider_in_data_source_raises():
    with pytest.raises(ValidationError):
        Metric(
            id="m1",
            label="Temp",
            source_component_id="x",
            data_source={"provider": "stocks", "query": {}},
        )


@pytest.mark.parametrize("cls", [Kpi, Ring, Gauge, ProgressBar])
def test_single_value_component_accepts_data_source(cls):
    comp = cls(
        id="c1",
        label="L",
        data_source=DataSource(provider="weather", query={"lat": 1.0, "lon": 2.0}),
    )
    assert comp.data_source is not None
    assert comp.data_source.provider == "weather"


def test_component_without_data_source_defaults_to_none():
    assert Kpi(id="k1", label="L").data_source is None


def test_data_source_refresh_secs_below_min_rejected():
    with pytest.raises(ValidationError):
        DataSource(provider="weather", query={}, refresh_secs=59)


def test_data_source_refresh_secs_above_max_rejected():
    with pytest.raises(ValidationError):
        DataSource(provider="weather", query={}, refresh_secs=86401)


def test_data_source_refresh_secs_bounds_accepted():
    DataSource(provider="weather", query={}, refresh_secs=60)
    DataSource(provider="weather", query={}, refresh_secs=86400)


def test_data_source_query_too_many_keys_rejected():
    query = {f"k{i}": i for i in range(11)}
    with pytest.raises(ValidationError):
        DataSource(provider="weather", query=query)


def test_data_source_query_ten_keys_accepted():
    query = {f"k{i}": i for i in range(10)}
    DataSource(provider="weather", query=query)


def test_data_source_query_rejects_non_str_number_value():
    with pytest.raises(ValidationError):
        DataSource(provider="weather", query={"bad": [1, 2, 3]})
