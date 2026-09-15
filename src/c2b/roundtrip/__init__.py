"""Utility 4: read a template DXF back into the normalised model and verify the round trip.

The template DXF is the drafter's working copy: they may move a beam, retype a mark or
delete a column. Geometry and mark text are therefore always read fresh from the drawing;
the ``C2B`` XDATA is used only for identity (which element this was) and for values a
drawing cannot carry (level elevations, offsets). Anything the drafter changed shows up in
the verification report.
"""
