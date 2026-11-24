# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Embedding spaces: vectors computed the same way from an organization's sessions, so nearby vectors mean similar data.

A space holds one vector per window, event or whole session. Embeddings are in preview; contact Roboto to enable them
for your organization. Use ``EmbeddingSpace`` to register a space, put rows into it, read them back, and search them
for similar or unusual spans. Boards and Roboto's AI read a space's rows too. A batch of rows that Roboto rejects
raises ``RobotoEmbeddingBatchRejectedException``, and the batches written before it stay written.
"""

from ._batching import MAX_BATCH_ROWS, ROW_COLUMNS
from .embedding_space import EmbeddingSpace
from .exceptions import RobotoEmbeddingBatchRejectedException
from .operations import RegisterEmbeddingSpaceRequest, UpdateEmbeddingSpaceRequest
from .record import (
    EmbeddingBatchProblem,
    EmbeddingBatchRecord,
    EmbeddingBatchStatus,
    EmbeddingLevel,
    EmbeddingRow,
    EmbeddingSessionCoverageRecord,
    EmbeddingSpaceKind,
    EmbeddingSpaceRecord,
    PutRowsResult,
)
from .search import (
    EmbeddingAnomaliesRequest,
    EmbeddingAnomaliesResponse,
    EmbeddingAnomalyRegion,
    EmbeddingAnomalyWindow,
    EmbeddingAttributeColumn,
    EmbeddingNormalize,
    EmbeddingRankedAnomaly,
    EmbeddingRowRecord,
    EmbeddingRowsCombinedSpace,
    EmbeddingRowsCombinedSpaceFit,
    EmbeddingRowsCoverage,
    EmbeddingRowsDistance,
    EmbeddingRowsDistanceTo,
    EmbeddingRowsPage,
    EmbeddingRowsProjection,
    EmbeddingRowsProjectionFit,
    EmbeddingRowsRequest,
    EmbeddingRowsRowFilter,
    EmbeddingRowsSample,
    EmbeddingRowsSampleReport,
    EmbeddingRowsSpace,
    EmbeddingSeed,
    EmbeddingSessionAnomalies,
    EmbeddingSessionScope,
    EmbeddingSimilarHit,
    EmbeddingSimilarRequest,
    EmbeddingSimilarResponse,
    EmbeddingSimilarSeed,
    EmbeddingSpaceDistance,
    EmbeddingSpaceRef,
)

__all__ = [
    "MAX_BATCH_ROWS",
    "ROW_COLUMNS",
    "EmbeddingAnomaliesRequest",
    "EmbeddingAnomaliesResponse",
    "EmbeddingAnomalyRegion",
    "EmbeddingAnomalyWindow",
    "EmbeddingAttributeColumn",
    "EmbeddingBatchProblem",
    "EmbeddingBatchRecord",
    "EmbeddingBatchStatus",
    "EmbeddingLevel",
    "EmbeddingNormalize",
    "EmbeddingRankedAnomaly",
    "EmbeddingRow",
    "EmbeddingRowRecord",
    "EmbeddingRowsCombinedSpace",
    "EmbeddingRowsCombinedSpaceFit",
    "EmbeddingRowsCoverage",
    "EmbeddingRowsDistance",
    "EmbeddingRowsDistanceTo",
    "EmbeddingRowsPage",
    "EmbeddingRowsProjection",
    "EmbeddingRowsProjectionFit",
    "EmbeddingRowsRequest",
    "EmbeddingRowsRowFilter",
    "EmbeddingRowsSample",
    "EmbeddingRowsSampleReport",
    "EmbeddingRowsSpace",
    "EmbeddingSeed",
    "EmbeddingSessionAnomalies",
    "EmbeddingSessionCoverageRecord",
    "EmbeddingSessionScope",
    "EmbeddingSimilarHit",
    "EmbeddingSimilarRequest",
    "EmbeddingSimilarResponse",
    "EmbeddingSimilarSeed",
    "EmbeddingSpace",
    "EmbeddingSpaceDistance",
    "EmbeddingSpaceKind",
    "EmbeddingSpaceRecord",
    "EmbeddingSpaceRef",
    "PutRowsResult",
    "RegisterEmbeddingSpaceRequest",
    "RobotoEmbeddingBatchRejectedException",
    "UpdateEmbeddingSpaceRequest",
]
