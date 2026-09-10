"""
The three measured variables, defined once.

This module exists because the definition used to be split in two: `main.py` held
the human-readable label and unit, while `ebas_thredds.py` held the instrument, the
netCDF variable name and the target wavelength. The two halves drifted — the labels
claimed 550 nm while the fetch actually selected 525/520 nm — and nothing in the
code could notice. Anything that describes a variable to a human or to an agent
reads it from here.

`wavelength_nm` is the wavelength the fetch *aims* for. Selection is
nearest-neighbour with no tolerance (see `_compute_annual_mean` in
`ebas_thredds.py`), so a file offering only a distant wavelength is still accepted;
the number below is the target, not a guarantee about every underlying file.
`None` means the variable has no wavelength dimension at all.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Variable:
    key: str
    label: str
    unit: str
    instruments: tuple[str, ...]
    nc_var: str
    wavelength_nm: float | None
    qc_level: str = "lev2"


VARIABLES: dict[str, Variable] = {
    "N": Variable(
        key="N",
        label="Particle Number Concentration",
        unit="cm⁻³",
        instruments=("cpc",),
        nc_var="particle_number_concentration_amean",
        wavelength_nm=None,
    ),
    "scattering": Variable(
        key="scattering",
        label="Scattering Coefficient 525 nm",
        unit="Mm⁻¹",
        instruments=("nephelometer",),
        nc_var="aerosol_light_scattering_coefficient_amean",
        wavelength_nm=525.0,
    ),
    "absorption": Variable(
        key="absorption",
        label="Absorption Coefficient 520 nm",
        unit="Mm⁻¹",
        instruments=("filter_absorption_photometer",),
        nc_var="aerosol_absorption_coefficient_amean",
        wavelength_nm=520.0,
    ),
}
