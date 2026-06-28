"""Solar geometry, shadow casting and thermal-comfort sanity checks."""

import numpy as np

from app.core import solar_comfort


def test_solar_elevation_diurnal():
    # Sun is up at midday, below horizon at midnight (UAE summer).
    _, el_noon = solar_comfort.solar_position(12.0)
    _, el_mid = solar_comfort.solar_position(0.0)
    assert el_noon > 50.0
    assert el_mid < 0.0


def test_shadow_more_at_low_sun():
    """Long shadows at low sun -> more shaded area than at high noon."""
    from app.core.geo_engine import get_geo

    gd = get_geo()
    shaded_noon = solar_comfort.shadow_mask(gd.height_raster, 12.0).mean()
    shaded_evening = solar_comfort.shadow_mask(gd.height_raster, 17.0).mean()
    assert shaded_evening > shaded_noon


def test_night_is_fully_shaded():
    from app.core.geo_engine import get_geo

    gd = get_geo()
    mask = solar_comfort.shadow_mask(gd.height_raster, 1.0)
    assert mask.all()


def test_utci_higher_in_sun_than_shade():
    mrt_sun = np.array([[70.0]], dtype=np.float32)
    mrt_shade = np.array([[44.0]], dtype=np.float32)
    u_sun = solar_comfort.utci_raster(41.0, mrt_sun, 3.0, 55.0)[0, 0]
    u_shade = solar_comfort.utci_raster(41.0, mrt_shade, 3.0, 55.0)[0, 0]
    assert u_sun > u_shade


def test_heat_risk_bands_monotonic():
    assert solar_comfort.heat_risk_band(22) == "Comfortable"
    assert solar_comfort.heat_risk_band(35) == "Strong"
    assert solar_comfort.heat_risk_band(50) == "Extreme"
    assert solar_comfort.heat_risk_score(20) < solar_comfort.heat_risk_score(45)
