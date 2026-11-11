"""IHSS Packet Tool: builds a print-ready IHSS provider-enrollment packet locally."""

__version__ = "0.1.0"

import logging as _logging

# pypdf logs harmless font-parsing notices for the state forms; keep the console quiet.
_logging.getLogger("pypdf").setLevel(_logging.ERROR)
