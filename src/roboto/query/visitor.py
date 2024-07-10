# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import abc
import typing

from .conditions import (
    Condition,
    ConditionGroup,
    ConditionType,
)


class ConditionVisitor(abc.ABC):
    def visit(self, cond: ConditionType) -> typing.Optional[ConditionType]:
        if isinstance(cond, Condition):
            return self.visit_condition(cond)
        elif isinstance(cond, ConditionGroup):
            return self.visit_condition_group(cond)
        else:
            raise ValueError(f"Unknown condition type: {type(cond)}")

    @abc.abstractmethod
    def visit_condition(self, condition: Condition) -> typing.Optional[ConditionType]:
        raise NotImplementedError("visit_condition")

    @abc.abstractmethod
    def visit_condition_group(
        self, condition_group: ConditionGroup
    ) -> typing.Optional[ConditionType]:
        raise NotImplementedError("visit_condition_group")


class BaseVisitor(ConditionVisitor):
    def visit_condition(self, condition: Condition) -> typing.Optional[ConditionType]:
        return condition

    def visit_condition_group(
        self, condition_group: ConditionGroup
    ) -> typing.Optional[ConditionType]:
        conditions = []
        for condition in condition_group.conditions:
            visited = self.visit(condition)
            if visited:
                conditions.append(visited)

        condition_group.conditions = conditions

        return condition_group
