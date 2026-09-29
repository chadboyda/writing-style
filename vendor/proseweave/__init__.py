"""proseweave: text cohesion, readability and easability measures, standard library only.

    from proseweave import Analysis, Jev
    props = Analysis(text, Jev()).properties()     # every single-text property
    basic = Analysis(text, None).basic()           # the no-key subset
    rhythm = cadence.measure(text)                 # cadence measurements, local only

See README.md for what each group of properties measures.
"""
from __future__ import annotations

from . import cadence
from . import source as _source
from .analysis import Analysis, compare, profile
from .jev import Jev, JevUnavailable

__version__ = "0.2.0"

__all__ = ["Analysis", "profile", "compare", "compare_source", "cadence", "Jev", "JevUnavailable", "__version__"]


def compare_source(source, target, j=None) -> dict:
    """Source-comparison properties of `target` against `source`.

    Each argument is a text or an Analysis. `j` is a Jev client; one is created
    from the configured key when omitted.
    """
    if j is None:
        j = Jev()
    s = source if isinstance(source, Analysis) else Analysis(source, j)
    t = target if isinstance(target, Analysis) else Analysis(target, j)
    return _source.compare(j, s, t)
