"""C2B - CAD to BIM.

Step 1 of the pipeline: read a client DXF, classify what is on it, extract
structural elements into the canonical schema and report everything that
could not be understood.
"""

__version__ = "0.3.0"

# Version of the canonical JSON schema written by this package. Downstream
# utilities (DXF writer, Revit importer) pin against this, not against
# ``__version__``.
SCHEMA_VERSION = "0.3.0"
