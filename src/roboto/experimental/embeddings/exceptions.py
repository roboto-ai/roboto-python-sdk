# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from ...exceptions import RobotoInvalidRequestException
from .record import EmbeddingBatchProblem, EmbeddingBatchRecord

_PROBLEMS_IN_MESSAGE = 10


class RobotoEmbeddingBatchRejectedException(RobotoInvalidRequestException):
    """Roboto rejected a batch of embedding rows whole, so none of its rows were written.

    ``EmbeddingSpace.put_rows`` raises it and sends no batch after the rejected one. The batches it committed before
    that one are not undone.
    """

    batch: EmbeddingBatchRecord
    """Record of the rejected batch."""

    committed: list[EmbeddingBatchRecord]
    """Records of the batches the same ``put_rows`` call committed before the rejected one."""

    def __init__(self, batch: EmbeddingBatchRecord, committed: list[EmbeddingBatchRecord]) -> None:
        problems = batch.rejected or []
        listed = "; ".join(_describe(problem) for problem in problems[:_PROBLEMS_IN_MESSAGE])
        more = f" (and {len(problems) - _PROBLEMS_IN_MESSAGE} more)" if len(problems) > _PROBLEMS_IN_MESSAGE else ""
        super().__init__(f"Embedding batch {batch.batch_id} was rejected: {listed or 'no reason given'}{more}")
        self.batch = batch
        self.committed = committed

    @property
    def problems(self) -> list[EmbeddingBatchProblem]:
        """First problems Roboto found in the batch, at most 100, or an empty list when Roboto gave none."""
        return self.batch.rejected or []


def _describe(problem: EmbeddingBatchProblem) -> str:
    row = "" if problem.row is None else f"row {problem.row}: "
    session = "" if problem.session_id is None else f"[{problem.session_id}] "
    return f"{row}{session}{problem.problem}"
