"""skills-radar - lazy-loading skill discovery for Claude Code via MCP.

Mirrors Anthropic's Tool Search Tool pattern for Skills.
See SPEC.md for architecture and design decisions.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("skills-radar")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
