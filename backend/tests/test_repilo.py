from app.services.agronomy.repilo import (
    assess_repilo_risk,
    find_longest_wet_spell,
    required_wetness_hours,
)


def test_required_hours_minimum_at_optimum():
    assert required_wetness_hours(17.5) == 12.0


def test_required_hours_increase_away_from_optimum():
    at_optimum = required_wetness_hours(17.5)
    assert required_wetness_hours(10.0) > at_optimum
    assert required_wetness_hours(25.0) > at_optimum


def test_no_infection_outside_viable_temperature_range():
    assert required_wetness_hours(3.0) == float("inf")
    result = assess_repilo_risk(continuous_wetness_hours=200.0, mean_temp_during_wetness=3.0)
    assert result.infection_triggered is False


def test_infection_triggered_when_hours_exceed_requirement():
    result = assess_repilo_risk(continuous_wetness_hours=14.0, mean_temp_during_wetness=17.5)
    assert result.infection_triggered is True
    assert result.pressure_ratio > 1.0


def test_infection_not_triggered_when_hours_below_requirement():
    result = assess_repilo_risk(continuous_wetness_hours=5.0, mean_temp_during_wetness=17.5)
    assert result.infection_triggered is False


def test_find_longest_wet_spell_picks_the_longest_contiguous_run():
    # Dos horas mojadas, una racha rota, luego tres horas mojadas seguidas (la más larga)
    samples = [
        (1.0, 0.9, 12.0),
        (1.0, 0.9, 13.0),
        (1.0, 0.0, 5.0),
        (1.0, 0.8, 16.0),
        (1.0, 0.9, 17.0),
        (1.0, 0.95, 18.0),
        (1.0, 0.0, 20.0),
    ]
    hours, mean_temp = find_longest_wet_spell(samples)
    assert hours == 3.0
    assert abs(mean_temp - 17.0) < 0.01
