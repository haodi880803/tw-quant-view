"""tw-quant engine — paper-trading / scoring engine rebuilt for GitHub Actions.

The authoritative behaviour specification is ``docs/engine-spec.md`` (with the
evidence appendices in ``docs/spec/``).  Module responsibilities follow spec §2.
Every published file (``data.json``, ``symbol/<code>.json``, ``orders.json``,
``events.json``, ``model-health.json``, ``shadow.json``, ``simple.html``) must
keep the exact shapes of spec §7 because the static viewer is frozen (spec §1.2 C1).
"""

__version__ = "2.0.0"
