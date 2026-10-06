"""Finding fasteners without a sidecar (M4): from part names, then from geometry.

Spec 5.2's order: names first, geometry next, the sidecar last, each overriding the
one before field by field. M4 covers parts whose names say something; telling an
anonymous solid is a screw by its shape alone is v1.1.
"""

from wrenchroom.detect.names import NameHint, read_name

__all__ = ["NameHint", "read_name"]
