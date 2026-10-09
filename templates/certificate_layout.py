"""Single predefined certificate layout used by the PDF renderer.

All template copy, colors, and geometry live here so the "one predefined
template" is trivially reviewable and replaceable.
"""

from reportlab.lib.colors import HexColor

PAGE_WIDTH, PAGE_HEIGHT = 595, 842  # A4 portrait (points)

ACCENT_DARK = HexColor("#1F3A5F")
ACCENT_GOLD = HexColor("#B8860B")
INK = HexColor("#222222")
MUTED = HexColor("#555555")

BORDER_OUTER_MARGIN = 24
BORDER_INNER_MARGIN = 36

TITLE = "CERTIFICATE OF ACHIEVEMENT"
DEFAULT_EVENT_NAME = "the program"
PRESENTED_BY = "This certificate is proudly presented to"
# Format string: the submitted event name is substituted at render time.
RECOGNITION_TEXT = (
    "in recognition of successful completion of {event_name} "
    "and outstanding performance."
)
ISSUER_NAME = "AEREO"
ISSUER_TITLE = "Authorized Signatory"
FOOTER_NOTE = "This certificate is issued electronically."

NAME_FONT = "Helvetica-Bold"
NAME_MAX_SIZE = 36
NAME_MIN_SIZE = 18

TITLE_FONT = "Helvetica-Bold"
TITLE_MAX_SIZE = 26
TITLE_MIN_SIZE = 14
