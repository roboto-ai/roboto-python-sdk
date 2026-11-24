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
    """Visitor over a query's tree of conditions, which can check, rewrite, or remove each condition it reaches.

    Roboto subclasses it to reject or rename the fields a query filters on before it runs the query. A subclass
    implements ``visit_condition`` and ``visit_condition_group``; ``visit`` calls whichever one matches the node it is
    given.
    """

    def visit(self, cond: ConditionType) -> typing.Optional[ConditionType]:
        """Visit a condition or a group of conditions, and return what the matching visit method returns.

        Args:
            cond: :py:class:`~roboto.query.Condition` or :py:class:`~roboto.query.ConditionGroup` to visit.

        Returns:
            The checked or rewritten node, or ``None`` to remove it from the query.

        Raises:
            ValueError: ``cond`` is neither a ``Condition`` nor a ``ConditionGroup``.
        """
        if isinstance(cond, Condition):
            return self.visit_condition(cond)
        elif isinstance(cond, ConditionGroup):
            return self.visit_condition_group(cond)
        else:
            raise ValueError(f"Unknown condition type: {type(cond)}")

    @abc.abstractmethod
    def visit_condition(self, condition: Condition) -> typing.Optional[ConditionType]:
        """Check or rewrite one condition.

        Args:
            condition: Condition to visit.

        Returns:
            The condition, a replacement for it, or ``None`` to remove it from the query.
        """
        raise NotImplementedError("visit_condition")

    @abc.abstractmethod
    def visit_condition_group(self, condition_group: ConditionGroup) -> typing.Optional[ConditionType]:
        """Check or rewrite a group of conditions, usually by visiting each condition in it.

        Args:
            condition_group: Group of conditions to visit.

        Returns:
            The group, a replacement for it, or ``None`` to remove it from the query.
        """
        raise NotImplementedError("visit_condition_group")


class BaseVisitor(ConditionVisitor):
    """Visitor that returns every condition unchanged, for a subclass to override only the visits it needs.

    Its group visit walks the whole tree, so a subclass that overrides only
    ``visit_condition`` still reaches every condition in nested groups.
    """

    def visit_condition(self, condition: Condition) -> typing.Optional[ConditionType]:
        """Return the condition unchanged."""
        return condition

    def visit_condition_group(self, condition_group: ConditionGroup) -> typing.Optional[ConditionType]:
        """Visit each condition in the group, and drop those whose visit returns ``None``.

        Edits the group in place: its ``conditions`` are replaced with the visited ones, so a query that holds the
        group sees the change. A group whose every condition is dropped is left with no conditions.

        Args:
            condition_group: Group of conditions to visit.

        Returns:
            The same group, with its conditions replaced.
        """
        conditions = []
        for condition in condition_group.conditions:
            visited = self.visit(condition)
            if visited:
                conditions.append(visited)

        condition_group.conditions = conditions

        return condition_group
