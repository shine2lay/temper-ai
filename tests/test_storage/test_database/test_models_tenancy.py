"""Tests for multi-tenant DB models (ToolConfigDB, profile tables, constants)."""

from temper_ai.storage.database.models_tenancy import (
    CONFIG_TYPE_AGENT,
    CONFIG_TYPE_STAGE,
    CONFIG_TYPE_TOOL,
    CONFIG_TYPE_WORKFLOW,
    PROFILE_DB_MAP,
    PROFILE_TYPE_BUDGET,
    PROFILE_TYPE_ERROR_HANDLING,
    PROFILE_TYPE_LLM,
    PROFILE_TYPE_MEMORY,
    PROFILE_TYPE_OBSERVABILITY,
    PROFILE_TYPE_SAFETY,
    VALID_CONFIG_TYPES,
    VALID_PROFILE_TYPES,
    AgentConfigDB,
    BudgetProfileDB,
    ErrorHandlingProfileDB,
    LLMProfileDB,
    MemoryProfileDB,
    ObservabilityProfileDB,
    SafetyProfileDB,
    StageConfigDB,
    ToolConfigDB,
    WorkflowConfigDB,
)


class TestConfigTypeConstants:
    """Tests for config type constants."""

    def test_valid_config_types_includes_tool(self) -> None:
        assert CONFIG_TYPE_TOOL in VALID_CONFIG_TYPES

    def test_valid_config_types_includes_all_four(self) -> None:
        assert VALID_CONFIG_TYPES == frozenset(
            {
                CONFIG_TYPE_WORKFLOW,
                CONFIG_TYPE_STAGE,
                CONFIG_TYPE_AGENT,
                CONFIG_TYPE_TOOL,
            }
        )

    def test_config_type_tool_value(self) -> None:
        assert CONFIG_TYPE_TOOL == "tool"


class TestToolConfigDB:
    """Tests for ToolConfigDB model."""

    def test_table_name(self) -> None:
        assert ToolConfigDB.__tablename__ == "tool_configs"

    def test_has_same_fields_as_agent_config(self) -> None:
        tool_fields = set(ToolConfigDB.model_fields.keys())
        agent_fields = set(AgentConfigDB.model_fields.keys())
        assert tool_fields == agent_fields

    def test_default_version(self) -> None:
        row = ToolConfigDB(
            tenant_id="t1",
            name="test",
            config_data={"key": "value"},
        )
        assert row.version == 1

    def test_default_description(self) -> None:
        row = ToolConfigDB(
            tenant_id="t1",
            name="test",
            config_data={},
        )
        assert row.description == ""

    def test_id_auto_generated(self) -> None:
        row = ToolConfigDB(
            tenant_id="t1",
            name="test",
            config_data={},
        )
        assert row.id is not None
        assert len(row.id) > 0


class TestProfileTypeConstants:
    """Tests for profile type constants."""

    def test_valid_profile_types_count(self) -> None:
        assert len(VALID_PROFILE_TYPES) == 6

    def test_valid_profile_types_values(self) -> None:
        expected = {
            "llm",
            "safety",
            "error_handling",
            "observability",
            "memory",
            "budget",
        }
        assert VALID_PROFILE_TYPES == expected

    def test_profile_type_llm(self) -> None:
        assert PROFILE_TYPE_LLM == "llm"

    def test_profile_type_safety(self) -> None:
        assert PROFILE_TYPE_SAFETY == "safety"

    def test_profile_type_error_handling(self) -> None:
        assert PROFILE_TYPE_ERROR_HANDLING == "error_handling"

    def test_profile_type_observability(self) -> None:
        assert PROFILE_TYPE_OBSERVABILITY == "observability"

    def test_profile_type_memory(self) -> None:
        assert PROFILE_TYPE_MEMORY == "memory"

    def test_profile_type_budget(self) -> None:
        assert PROFILE_TYPE_BUDGET == "budget"


class TestProfileDBMap:
    """Tests for PROFILE_DB_MAP mapping."""

    def test_maps_all_profile_types(self) -> None:
        assert set(PROFILE_DB_MAP.keys()) == VALID_PROFILE_TYPES

    def test_llm_maps_to_correct_model(self) -> None:
        assert PROFILE_DB_MAP["llm"] is LLMProfileDB

    def test_safety_maps_to_correct_model(self) -> None:
        assert PROFILE_DB_MAP["safety"] is SafetyProfileDB

    def test_error_handling_maps_to_correct_model(self) -> None:
        assert PROFILE_DB_MAP["error_handling"] is ErrorHandlingProfileDB

    def test_observability_maps_to_correct_model(self) -> None:
        assert PROFILE_DB_MAP["observability"] is ObservabilityProfileDB

    def test_memory_maps_to_correct_model(self) -> None:
        assert PROFILE_DB_MAP["memory"] is MemoryProfileDB

    def test_budget_maps_to_correct_model(self) -> None:
        assert PROFILE_DB_MAP["budget"] is BudgetProfileDB


class TestProfileTables:
    """Tests for profile table models."""

    def test_all_profile_tables_have_correct_fields(self) -> None:
        expected_fields = {
            "id",
            "tenant_id",
            "name",
            "description",
            "config_data",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        }
        for name, model in PROFILE_DB_MAP.items():
            fields = set(model.model_fields.keys())
            assert fields == expected_fields, f"{name} has wrong fields: {fields}"

    def test_profiles_have_no_version_field(self) -> None:
        for name, model in PROFILE_DB_MAP.items():
            assert (
                "version" not in model.model_fields
            ), f"{name} should not have version field"

    def test_llm_profile_table_name(self) -> None:
        assert LLMProfileDB.__tablename__ == "llm_profiles"

    def test_safety_profile_table_name(self) -> None:
        assert SafetyProfileDB.__tablename__ == "safety_profiles"

    def test_error_handling_profile_table_name(self) -> None:
        assert ErrorHandlingProfileDB.__tablename__ == "error_handling_profiles"

    def test_observability_profile_table_name(self) -> None:
        assert ObservabilityProfileDB.__tablename__ == "observability_profiles"

    def test_memory_profile_table_name(self) -> None:
        assert MemoryProfileDB.__tablename__ == "memory_profiles"

    def test_budget_profile_table_name(self) -> None:
        assert BudgetProfileDB.__tablename__ == "budget_profiles"

    def test_profile_default_description(self) -> None:
        row = LLMProfileDB(
            tenant_id="t1",
            name="test",
            config_data={},
        )
        assert row.description == ""

    def test_profile_id_auto_generated(self) -> None:
        row = SafetyProfileDB(
            tenant_id="t1",
            name="test",
            config_data={},
        )
        assert row.id is not None
        assert len(row.id) > 0


class TestConfigModelsExist:
    """Verify all expected config models are importable."""

    def test_workflow_config_exists(self) -> None:
        assert WorkflowConfigDB.__tablename__ == "workflow_configs"

    def test_stage_config_exists(self) -> None:
        assert StageConfigDB.__tablename__ == "stage_configs"

    def test_agent_config_exists(self) -> None:
        assert AgentConfigDB.__tablename__ == "agent_configs"

    def test_tool_config_exists(self) -> None:
        assert ToolConfigDB.__tablename__ == "tool_configs"
