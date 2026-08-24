from app.services.agronomy.gdd import single_sine_gdd


def test_gdd_zero_when_tmax_below_base():
    assert single_sine_gdd(t_min=2, t_max=10, t_base=12.5) == 0.0


def test_gdd_simple_average_when_tmin_above_base():
    assert single_sine_gdd(t_min=20, t_max=30, t_base=12.5) == 12.5


def test_gdd_single_sine_straddling_base():
    # Calculado a mano con la fórmula de Baskerville-Emin para
    # t_min=10, t_max=25, t_base=12.5 (ver docstring del módulo).
    result = single_sine_gdd(t_min=10, t_max=25, t_base=12.5)
    assert abs(result - 5.4408) < 0.001


def test_gdd_never_negative():
    assert single_sine_gdd(t_min=-5, t_max=11, t_base=12.5) == 0.0
