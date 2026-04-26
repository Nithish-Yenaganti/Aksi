"""Greeting utilities for the verification fixture."""

from web.message import buildMessage

DEFAULT_NAME = "Aksi"


class Greeter:
    """Formats greeting text."""

    def greet(self, name: str = DEFAULT_NAME) -> str:
        """Return a friendly greeting."""
        return f"Hello, {name}"


def greet_default() -> str:
    """Return the default greeting."""
    return Greeter().greet()
