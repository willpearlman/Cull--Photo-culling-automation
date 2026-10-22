"""What the photographer does in Lightroom after Cull writes sidecars, per Lightroom mode.

Both modes get the same sidecars (star rating, color label, keywords next to each RAW). Pick
and reject flags never travel through XMP in either app, so picks are 5 stars and rejects 1.
The modes differ in when Cull must run and how Lightroom picks the sidecars up.
"""

MODES = {
    "classic": {
        "name": "Lightroom Classic",
        "when": "Before or after you import.",
        "summary": "Classic can re-read sidecars at any time with Read Metadata from Files.",
        "before_export": [
            "If these photos are already in your catalog, first select them all in Library and "
            "choose Metadata > Save Metadata to File (Ctrl+S, Cmd+S on Mac). This writes your "
            "existing edits into the sidecars so Cull adds to them instead of replacing them.",
        ],
        "after_export": [
            "Not imported yet: import the shoot folder as usual. Classic reads the ratings, "
            "labels and keywords during import.",
            "Already imported: in Library, select the photos, then choose Metadata > Read "
            "Metadata from Files. This replaces the catalog's metadata for those photos with "
            "what is in the sidecars.",
            "Filter by rating: 5 stars are Cull's picks, 1 star are its rejects. To flag the "
            "rejects, filter to 1 star, select all and press X.",
        ],
    },
    "cloud": {
        "name": "Lightroom",
        "when": "Before you import. Lightroom only reads sidecars when photos are added.",
        "summary": "Run Cull on the card or folder first, then add the folder to Lightroom.",
        "before_export": [
            "Do not import the photos into Lightroom yet. Lightroom reads sidecars only when "
            "photos are added, so ratings written after import never show up.",
        ],
        "after_export": [
            "In Lightroom, choose File > Add Photos, pick the shoot folder and add it. Lightroom "
            "reads the ratings and keywords from the sidecars as it imports.",
            "Filter by rating: 5 stars are Cull's picks, 1 star are its rejects.",
            "Already imported before running Cull? Lightroom will not pick up the new ratings. "
            "Remove those photos from Lightroom and add the folder again (this discards any "
            "edits made in Lightroom).",
        ],
    },
}


def guide(mode):
    """Instructions for one mode, or None when no mode is chosen yet."""
    return MODES.get(mode)
