"""Validation library shim: HA 2026.11+ uses probatio, older versions voluptuous."""
try:
    import probatio as vol  # noqa: F401
except ImportError:  # pragma: no cover
    import voluptuous as vol  # noqa: F401
