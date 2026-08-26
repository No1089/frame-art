"""Test setup.

Nothing here touches a museum API or the TV, on purpose. Those are the two
things most likely to change, and mocking them would mean asserting the
behaviour this code originally assumed, which is precisely what turned out
to be wrong: a Met mock would happily encode "filters apply regardless of
parameter order" and pass for ever while the real endpoint did the opposite.

So these tests pin down our own logic, and the external behaviour stays
documented in the README where a human can re-check it.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
