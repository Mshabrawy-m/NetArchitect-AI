"""Custom exception hierarchy for the NetArchitect AI application layer.

This module defines exceptions raised and inspected by the application and
agent layers. They are intentionally separate from Pydantic's validation
mechanism: schema ``model_validator`` methods raise plain ``ValueError``,
which Pydantic surfaces as ``pydantic.ValidationError``. The classes here
exist so application code can distinguish domain error categories (a
duplicate id at runtime, a missing link endpoint, an overlapping subnet, a
violated constraint, exceeded resource limits, a configuration problem)
without relying on string introspection of validation errors.

The base :class:`NetArchitectError` lets any caller catch "any NetArchitect
AI domain error" with a single ``except`` clause.
"""


class NetArchitectError(Exception):
    """Base class for all NetArchitect AI domain errors."""


class SchemaError(NetArchitectError):
    """Base class for schema-structure problems discovered at runtime.

    Raised by application logic (not by Pydantic validators) when a
    structure violates an invariant the application layer enforces outside
    the typed models.
    """


class DuplicateIdError(SchemaError):
    """Two entities share an identifier that must be unique."""


class MissingEndpointError(SchemaError):
    """A link references an endpoint that does not exist."""


class DeviceNotFoundError(SchemaError):
    """A referenced device id does not exist in the topology."""


class LinkNotFoundError(SchemaError):
    """A referenced link id does not exist in the topology."""


class OverlappingSubnetError(SchemaError):
    """Two subnets overlap and cannot coexist in the same plan."""


class InvalidVlanIdError(SchemaError):
    """A VLAN id is outside the valid 1-4094 range."""


class InsufficientAddressSpaceError(SchemaError):
    """A set of subnet requirements cannot fit inside the parent block.

    The message lists every requirement that could not be allocated; the
    allocator never truncates a request silently.
    """


class TwinSchemaVersionError(SchemaError):
    """A digital-twin JSON payload uses an unknown or unsupported schema version.

    Raised before model validation so callers get an actionable message instead
    of a generic field error when a payload was produced by a newer build.
    """


class ConstraintViolationError(NetArchitectError):
    """An optimization constraint (hard or soft) was violated."""


class LimitsExceededError(NetArchitectError):
    """A bounded resource limit was exceeded."""


class SimulationError(NetArchitectError):
    """Base class for simulation-engine failures."""


class SimulationRuntimeExceeded(SimulationError):
    """A simulation run exceeded its configured wall-clock budget."""


class ScenarioValidationError(SimulationError):
    """A scenario is malformed or references entities outside the baseline twin."""


class OptimizationError(NetArchitectError):
    """Base class for optimization-engine failures."""


class OptimizationValidationError(OptimizationError):
    """An optimization candidate or setting is structurally invalid."""


class OptimizationRuntimeExceeded(OptimizationError):
    """An optimization run exceeded its configured wall-clock search budget."""


class ConfigError(NetArchitectError):
    """Application configuration is missing or invalid."""


class LLMError(NetArchitectError):
    """Base class for language-model provider failures."""


class LLMMissingKeyError(LLMError):
    """No API key is configured for the requested provider."""


class LLMAuthenticationError(LLMError):
    """The provider rejected the configured API key."""


class LLMTimeoutError(LLMError):
    """A provider request exceeded its wall-clock timeout."""


class LLMRateLimitError(LLMError):
    """The provider kept returning HTTP 429 after bounded retries."""


class LLMProviderError(LLMError):
    """The provider is unavailable or returned an unusable HTTP response."""


class LLMMalformedResponseError(LLMError):
    """The provider response envelope or JSON payload could not be parsed."""


class LLMSchemaError(LLMError):
    """Structured output failed schema validation after bounded repairs."""


class LLMBudgetExceededError(LLMError):
    """The per-session LLM call or token budget is exhausted."""


class AgentError(NetArchitectError):
    """Base class for agent-framework failures."""


class AgentValidationError(AgentError):
    """An agent contract, plan, or workflow state is structurally invalid."""


class ToolError(AgentError):
    """Base class for tool-registry failures."""


class ToolNotFoundError(ToolError):
    """A requested tool is not registered."""


class ToolNotAllowedError(ToolError):
    """A tool exists but is outside the calling agent's allowlist."""


class ToolInputError(ToolError):
    """A tool input failed validation before execution."""


class ToolOutputError(ToolError):
    """A tool output failed validation after execution."""


class WorkflowError(AgentError):
    """Base class for orchestrator and workflow failures."""


class WorkflowCycleError(WorkflowError):
    """A workflow plan contains a dependency cycle."""


class WorkflowLimitError(WorkflowError):
    """A workflow hit a structural or resource limit."""
