"""Deployed graph entry for the main imaging_scientist agent.

The main ``imaging_scientist_agent`` is exposed via ``__getattr__`` lazy loading
in ``imaging_scientist/imaging_scientist.py`` so it doesn't construct on plain
``import imaging_scientist``. ``langgraph dev`` 's symbol resolver inspects
module attributes directly and doesn't trigger ``__getattr__``, so we
re-export here to make it visible.
"""

from imaging_scientist.imaging_scientist import imaging_scientist_agent

__all__ = ["imaging_scientist_agent"]
