"""Core-owned numeric constants shared by domain schemas and planners.

These values live in ``core`` so low-level schemas never need to import a
higher layer. The network VLAN modules re-export them, preserving every
existing import path with the same integer objects.
"""

VLAN_ID_MIN = 1
VLAN_ID_MAX = 4094

__all__ = ["VLAN_ID_MAX", "VLAN_ID_MIN"]
