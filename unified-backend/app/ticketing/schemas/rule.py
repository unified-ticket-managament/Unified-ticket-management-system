from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.ticketing.enums.rule_enums import (
    RuleActionType,
    RuleCategory,
    RuleCombinator,
    RuleConditionField,
    RuleConditionOperator,
)
from app.ticketing.schemas.common import ORMBase


class RuleConditionItem(BaseModel):
    field: str
    operator: str
    value: Any

    @model_validator(mode="after")
    def _check_field_operator(self) -> "RuleConditionItem":
        if self.field not in RuleConditionField.ALL:
            raise ValueError(f"Unknown condition field: {self.field}")

        fixed_operator = RuleConditionOperator.FIXED_BY_FIELD.get(self.field)
        if fixed_operator is not None and self.operator != fixed_operator:
            raise ValueError(
                f"Field '{self.field}' must use operator '{fixed_operator}'."
            )
        if fixed_operator is None and self.operator not in RuleConditionOperator.ALL:
            raise ValueError(f"Unknown condition operator: {self.operator}")

        if self.field == RuleConditionField.CLIENT:
            if not isinstance(self.value, list) or not self.value:
                raise ValueError("Client condition value must be a non-empty list of client ids.")
        elif self.field == RuleConditionField.HAS_ATTACHMENT:
            if not isinstance(self.value, bool):
                raise ValueError("has_attachment condition value must be a boolean.")
        else:
            if not isinstance(self.value, str) or not self.value.strip():
                raise ValueError(f"Condition value for '{self.field}' must be non-empty text.")

        return self


class RuleConditionGroup(BaseModel):
    combinator: str = RuleCombinator.AND
    rules: list[RuleConditionItem] = Field(default_factory=list)

    @field_validator("combinator")
    @classmethod
    def _check_combinator(cls, value: str) -> str:
        if value not in RuleCombinator.ALL:
            raise ValueError(f"Unknown combinator: {value}")
        return value


class RuleActionItem(BaseModel):
    type: str
    # create_folder / move_to_folder:
    folder_name: str | None = None
    # forward_to:
    employee_user_ids: list[UUID] | None = None
    # forward_to — Distribution List references, resolved fresh to
    # their current active members at every execution (never a
    # snapshot) — see RuleEngineService._execute_action. Merged with
    # employee_user_ids at execution time, not at save time.
    distribution_list_ids: list[UUID] | None = None

    @model_validator(mode="after")
    def _check_action_shape(self) -> "RuleActionItem":
        if self.type not in RuleActionType.ALL:
            raise ValueError(f"Unknown action type: {self.type}")

        if self.type in (RuleActionType.CREATE_FOLDER, RuleActionType.MOVE_TO_FOLDER):
            if not self.folder_name or not self.folder_name.strip():
                raise ValueError(f"'{self.type}' requires a non-empty folder_name.")
        elif self.type == RuleActionType.FORWARD_TO:
            if not self.employee_user_ids and not self.distribution_list_ids:
                raise ValueError(
                    "'forward_to' requires at least one employee_user_ids or "
                    "distribution_list_ids entry."
                )

        return self


def _validate_category_scope(category: str, conditions: RuleConditionGroup, exceptions: RuleConditionGroup, actions: list[RuleActionItem]) -> None:
    if category not in RuleCategory.ALL:
        raise ValueError(f"Unknown rule category: {category}")

    allowed_fields = set(RuleConditionField.BY_CATEGORY[category])
    allowed_actions = set(RuleActionType.BY_CATEGORY[category])

    for group_name, group in (("conditions", conditions), ("exceptions", exceptions)):
        for item in group.rules:
            if item.field not in allowed_fields:
                raise ValueError(
                    f"Condition field '{item.field}' is not valid for {category} ({group_name})."
                )

    for action in actions:
        if action.type not in allowed_actions:
            raise ValueError(f"Action '{action.type}' is not valid for {category}.")

    if category == RuleCategory.OTP_RULE:
        forward_actions = [a for a in actions if a.type == RuleActionType.FORWARD_TO]
        if len(forward_actions) != 1:
            raise ValueError("OTP Rules require exactly one 'forward_to' action.")


class RuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    category: str
    is_enabled: bool = True
    conditions: RuleConditionGroup
    exceptions: RuleConditionGroup = Field(default_factory=RuleConditionGroup)
    actions: list[RuleActionItem] = Field(..., min_length=1)
    stop_processing: bool = False
    # Explicitly added/shared/assigned users — an empty list (the
    # default) means this rule is private to its creator. Distinct
    # from a forward_to action's employee_user_ids: forwarding a
    # matching email to someone is never itself a grant of rule/folder
    # access.
    shared_user_ids: list[UUID] = Field(default_factory=list)
    # Same grant, extended to Distribution Lists (see
    # app.ticketing.models.distribution_list) — every current, active
    # member of a listed Distribution List gets the same view/manage
    # access shared_user_ids grants an individual employee, resolved
    # fresh at every request. Validated server-side in RuleService
    # against real, active Distribution Lists — never trusted as-is.
    shared_distribution_list_ids: list[UUID] = Field(default_factory=list)

    @field_validator("conditions")
    @classmethod
    def _check_conditions_nonempty(cls, value: RuleConditionGroup) -> RuleConditionGroup:
        if not value.rules:
            raise ValueError("A rule needs at least one condition.")
        return value

    @model_validator(mode="after")
    def _check_scope(self) -> "RuleCreate":
        _validate_category_scope(self.category, self.conditions, self.exceptions, self.actions)
        return self


class RuleUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    is_enabled: bool
    conditions: RuleConditionGroup
    exceptions: RuleConditionGroup = Field(default_factory=RuleConditionGroup)
    actions: list[RuleActionItem] = Field(..., min_length=1)
    stop_processing: bool = False
    shared_user_ids: list[UUID] = Field(default_factory=list)
    shared_distribution_list_ids: list[UUID] = Field(default_factory=list)

    @field_validator("conditions")
    @classmethod
    def _check_conditions_nonempty(cls, value: RuleConditionGroup) -> RuleConditionGroup:
        if not value.rules:
            raise ValueError("A rule needs at least one condition.")
        return value


class RuleEnabledUpdate(BaseModel):
    is_enabled: bool


class RuleReorderRequest(BaseModel):
    direction: str

    @field_validator("direction")
    @classmethod
    def _check_direction(cls, value: str) -> str:
        if value not in ("up", "down"):
            raise ValueError("direction must be 'up' or 'down'.")
        return value


class RuleResponse(ORMBase):
    rule_id: UUID
    name: str
    category: str
    is_enabled: bool
    conditions: dict
    exceptions: dict
    actions: list
    stop_processing: bool
    priority: int
    created_by: UUID | None
    shared_user_ids: list[UUID]
    shared_distribution_list_ids: list[UUID]
    created_at: datetime
    updated_at: datetime
    # Whether the *current viewer* (not just anyone) can edit/delete/
    # toggle/reorder this specific rule — distinct from being able to
    # merely see it. Defaults True because create/update/set_enabled
    # only ever return a rule the caller just successfully mutated
    # (already proven manageable); list_all/reorder explicitly
    # override this per-rule since rule:view_all can surface rules the
    # viewer can see but not manage — see rule_access.can_manage_rule.
    can_manage: bool = True
