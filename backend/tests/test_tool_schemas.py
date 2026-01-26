"""Test tool schema generation for Pydantic-XML hybrid architecture.

This module validates that the tool schemas correctly include Field descriptions
in the JSON Schema output, ensuring Gemini 3 Pro receives proper parameter metadata.
"""

from typing import Any

import pytest

from app.agents.tools import get_tool_definitions


def _get_tool_schemas() -> dict[str, dict[str, Any]]:
    """Get tool schemas as a dict mapping name to schema info."""
    tool_defs = get_tool_definitions()
    return {t["name"]: t for t in tool_defs}


class TestToolSchemas:
    """Validate tool schemas include Field descriptions."""

    def test_tools_have_parameter_descriptions(self) -> None:
        """Verify all tools with parameters have descriptions in their schemas."""
        schemas = _get_tool_schemas()

        # Tools that should have parameters with descriptions
        tools_with_params = [
            "search_web",
            "spawn_agent",
            "create_plan",
            "get_plan",
            "update_plan",
            "delete_plan",
            "add_task_to_plan",
            "update_task",
            "remove_task_from_plan",
            "s3_upload_file",
            "s3_download_file",
            "s3_upload_string_content",
            "s3_read_string_content",
            "s3_delete_object",
            "s3_generate_presigned_download_url",
            "s3_generate_presigned_upload_post_url",
            "s3_copy_file",
            "python_execute_code",
            "extract_webpage",
            "s3_fetch_image",
            "generate_image",
            "search_openalex",
            "search_semantic_scholar",
            "search_semantic_scholar_bulk",
            "search_arxiv",
        ]

        for tool_name in tools_with_params:
            assert tool_name in schemas, f"Tool {tool_name} not found in agent"
            tool_info = schemas[tool_name]
            params = tool_info.get("parameters", {})

            # Check if schema has properties (parameters)
            if "properties" in params:
                properties = params["properties"]
                for param_name, param_schema in properties.items():
                    # Each parameter should have a description from Field()
                    assert "description" in param_schema, (
                        f"Tool {tool_name}.{param_name} missing description. "
                        f"Ensure Field(description='...') is used with Annotated."
                    )
                    assert param_schema["description"], (
                        f"Tool {tool_name}.{param_name} has empty description"
                    )

    def test_search_web_schema(self) -> None:
        """Verify search_web has correct schema structure."""
        schemas = _get_tool_schemas()

        assert "search_web" in schemas
        tool_info = schemas["search_web"]
        params = tool_info.get("parameters", {})

        # Check required fields
        properties = params.get("properties", {})
        assert "query" in properties
        assert "max_results" in properties

        # Check query description
        assert "description" in properties["query"]
        assert "search" in properties["query"]["description"].lower()

    def test_spawn_agent_schema(self) -> None:
        """Verify spawn_agent has model selection guidance in param descriptions."""
        schemas = _get_tool_schemas()

        assert "spawn_agent" in schemas
        tool_info = schemas["spawn_agent"]
        params = tool_info.get("parameters", {})

        properties = params.get("properties", {})
        assert "user_input" in properties
        assert "model_name" in properties

        # Check model_name has guidance
        model_desc = properties["model_name"].get("description", "")
        assert "gemini" in model_desc.lower() or "model" in model_desc.lower()

    def test_generate_image_schema(self) -> None:
        """Verify generate_image has model options in schema."""
        schemas = _get_tool_schemas()

        assert "generate_image" in schemas
        tool_info = schemas["generate_image"]
        params = tool_info.get("parameters", {})

        properties = params.get("properties", {})
        assert "prompt" in properties
        assert "model" in properties
        assert "aspect_ratio" in properties

        # Check model enum or description mentions imagen/gemini
        model_info = properties.get("model", {})
        model_desc = model_info.get("description", "")
        assert "model" in model_desc.lower() or "imagen" in str(model_info).lower()

    def test_academic_search_tools_have_query_params(self) -> None:
        """Verify academic search tools exist and have proper schemas."""
        schemas = _get_tool_schemas()

        academic_tools = [
            "search_openalex",
            "search_semantic_scholar",
            "search_semantic_scholar_bulk",
            "search_arxiv",
            "list_arxiv_categories",
        ]

        for tool_name in academic_tools:
            assert tool_name in schemas, f"Academic tool {tool_name} not found"
            tool_info = schemas[tool_name]
            params = tool_info.get("parameters", {})

            # All should have properties except list_arxiv_categories
            if tool_name != "list_arxiv_categories":
                assert "properties" in params, f"{tool_name} missing properties"
                assert "query" in params["properties"], f"{tool_name} missing query param"

    def test_s3_tools_have_consistent_schemas(self) -> None:
        """Verify S3 tools have consistent parameter naming."""
        schemas = _get_tool_schemas()

        # Tools that use object_name
        object_name_tools = [
            "s3_read_string_content",
            "s3_delete_object",
            "s3_generate_presigned_download_url",
            "s3_generate_presigned_upload_post_url",
            "s3_fetch_image",
        ]

        for tool_name in object_name_tools:
            assert tool_name in schemas
            params = schemas[tool_name].get("parameters", {})
            properties = params.get("properties", {})
            assert "object_name" in properties, f"{tool_name} missing object_name param"

    def test_python_execute_code_schema(self) -> None:
        """Verify python_execute_code has code and timeout params."""
        schemas = _get_tool_schemas()

        assert "python_execute_code" in schemas
        tool_info = schemas["python_execute_code"]
        params = tool_info.get("parameters", {})

        properties = params.get("properties", {})
        assert "code" in properties
        assert "timeout" in properties

        # Check timeout has description about seconds
        timeout_desc = properties["timeout"].get("description", "")
        assert "second" in timeout_desc.lower() or "time" in timeout_desc.lower()


class TestToolSchemaSnapshot:
    """Snapshot tests for schema stability."""

    def test_tool_count(self) -> None:
        """Verify expected number of tools are registered."""
        schemas = _get_tool_schemas()

        # Expected tools (update this count if tools are added/removed)
        expected_tool_count = 29

        assert len(schemas) == expected_tool_count, (
            f"Expected {expected_tool_count} tools, found {len(schemas)}. "
            f"Tools: {sorted(schemas.keys())}"
        )

    def test_all_tools_have_xml_docstrings(self) -> None:
        """Verify all tools have XML-structured docstrings via description."""
        schemas = _get_tool_schemas()

        for tool_name, tool_info in schemas.items():
            description = tool_info.get("description", "")

            # All tools should have <tool_def> or <intent> XML structure
            assert "<tool_def>" in description or "<intent>" in description, (
                f"Tool {tool_name} missing XML docstring structure. "
                f"Docstring should contain <tool_def> and <intent> tags."
            )
