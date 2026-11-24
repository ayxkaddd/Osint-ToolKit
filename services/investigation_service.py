# services/investigation_service.py
"""Investigation storage.

Layout (all under ``investigation_results/``)::

    investigations.json             investigation metadata (no binary data)
    current_investigation.json      the active investigation id
    <investigation_id>/
        index.json                  {result_id: summary} - listing never opens result files
        results/<result_id>.json.gz full result records (gzip-compressed JSON)
        notes/<note_id>.json        analyst notes (markdown; [[result:<id>]] links a result)
        notes/snapshots/<id>.json.gz  copy of a result attached to a note (![[snapshot:<id>]]),
        notes/images/<id>.webp        image added to a note
                                    kept when the result itself is deleted
        notes/snapshots/index.json  {snapshot_id: result_id}
        picture.webp                optional case picture (resized)
        graph.json                  the graph view: positions, hidden and removed nodes, what was added

A result can carry ``children``: follow-up lookups attached to it (e.g. the WHOIS
analysis of the domains found by an NS lookup, or the stats/groups/messages
fetched for a Funstat user) so related data stays in one group.
"""
from services.investigations.cases import CaseStore
from services.investigations.results import ResultsMixin
from services.investigations.identifiers import IdentifiersMixin
from services.investigations.timeline import TimelineMixin
from services.investigations.manual import ManualResultsMixin
from services.investigations.notes import NotesMixin
from services.investigations.migration import MigrationMixin
from services.investigations.graph import GraphMixin
# imported from here by routes and the saving decorator
from services.investigations.constants import (  # noqa: F401
    INDEX_VERSION, MANUAL_FILE_MAX_UPLOAD, MANUAL_FILES_MAX, MANUAL_SERVICE, MANUAL_TEXT_MAX, NOTE_IMAGE_MAX_UPLOAD,
)
from services.investigations.storage import _STORE_LOCK, _new_result_id  # noqa: F401
from services.investigations.summaries import find_target, summarize  # noqa: F401
from services.investigations.images import process_note_image, process_picture  # noqa: F401


class InvestigationService(CaseStore, ResultsMixin, IdentifiersMixin, TimelineMixin, ManualResultsMixin, NotesMixin, MigrationMixin,
                           GraphMixin):
    """Everything about investigations; each area is a mixin in services/investigations/."""


# The one instance the app uses (routes, the saving decorator, reports)
investigation_service = InvestigationService()
