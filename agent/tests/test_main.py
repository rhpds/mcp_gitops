"""Unit tests for main.py"""
import pytest
from pydantic import ValidationError

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import extract_json_tool_call, FailureReport


class TestExtractJsonToolCall:
    """Tests for the extract_json_tool_call function."""

    def test_extracts_valid_tool_call(self):
        """Should extract a valid JSON tool call from text."""
        content = 'Some text before {"name":"create_issue","arguments":{"title":"test"}} and after'
        result = extract_json_tool_call(content, ["create_issue"])
        assert result is not None
        assert result["name"] == "create_issue"
        assert result["arguments"]["title"] == "test"

    def test_extracts_tool_call_without_valid_names_filter(self):
        """Should extract any tool call when no valid_tool_names provided."""
        content = '{"name":"any_tool","arguments":{"key":"value"}}'
        result = extract_json_tool_call(content)
        assert result is not None
        assert result["name"] == "any_tool"

    def test_returns_none_for_invalid_tool_name(self):
        """Should return None when tool name not in valid list."""
        content = '{"name":"invalid_tool","arguments":{}}'
        result = extract_json_tool_call(content, ["create_issue", "pods_log"])
        assert result is None

    def test_returns_none_for_missing_name_field(self):
        """Should return None when JSON lacks 'name' field."""
        content = '{"arguments":{"key":"value"}}'
        result = extract_json_tool_call(content)
        assert result is None

    def test_returns_none_for_no_json(self):
        """Should return None when no JSON present."""
        content = "This is just plain text without any JSON"
        result = extract_json_tool_call(content)
        assert result is None

    def test_returns_none_for_invalid_json(self):
        """Should return None for malformed JSON."""
        content = '{"name": "test", "arguments": {broken}'
        result = extract_json_tool_call(content)
        assert result is None

    def test_extracts_first_valid_tool_call(self):
        """Should return the first valid tool call when multiple exist."""
        content = '{"name":"first_tool","arguments":{}} and {"name":"second_tool","arguments":{}}'
        result = extract_json_tool_call(content, ["first_tool", "second_tool"])
        assert result is not None
        assert result["name"] == "first_tool"

    def test_handles_nested_json(self):
        """Should handle nested JSON structures."""
        content = '''{"name":"create_issue","arguments":{"body":"### Error\\nDetails here"}}'''
        result = extract_json_tool_call(content, ["create_issue"])
        assert result is not None
        assert result["name"] == "create_issue"
        assert "Error" in result["arguments"]["body"]

    def test_handles_complex_nested_arguments(self):
        """Should handle deeply nested argument structures."""
        content = '{"name":"pods_log","arguments":{"namespace":"default","name":"my-pod","tailLines":10}}'
        result = extract_json_tool_call(content, ["pods_log"])
        assert result is not None
        assert result["arguments"]["tailLines"] == 10

    def test_extracts_from_multiline_content(self):
        """Should extract JSON from multiline text."""
        content = """Here is the analysis:

The pod is failing due to an error.

{"name":"create_issue","arguments":{"title":"Pod failure"}}

Please review the above."""
        result = extract_json_tool_call(content, ["create_issue"])
        assert result is not None
        assert result["name"] == "create_issue"

    def test_skips_invalid_matches_first_valid(self):
        """Should skip non-tool JSON and find valid tool call."""
        content = '{"other":"data"} then {"name":"create_issue","arguments":{}}'
        result = extract_json_tool_call(content, ["create_issue"])
        assert result is not None
        assert result["name"] == "create_issue"


class TestFailureReport:
    """Tests for the FailureReport Pydantic model."""

    def test_valid_report_with_all_fields(self):
        """Should accept a report with all fields."""
        report = FailureReport(
            namespace="default",
            pod_name="my-pod-abc123",
            container_name="main"
        )
        assert report.namespace == "default"
        assert report.pod_name == "my-pod-abc123"
        assert report.container_name == "main"

    def test_valid_report_without_container_name(self):
        """Should accept a report without container_name (optional)."""
        report = FailureReport(
            namespace="production",
            pod_name="api-server-xyz"
        )
        assert report.namespace == "production"
        assert report.pod_name == "api-server-xyz"
        assert report.container_name is None

    def test_rejects_missing_namespace(self):
        """Should reject a report missing namespace."""
        with pytest.raises(ValidationError):
            FailureReport(pod_name="my-pod")

    def test_rejects_missing_pod_name(self):
        """Should reject a report missing pod_name."""
        with pytest.raises(ValidationError):
            FailureReport(namespace="default")

    def test_accepts_empty_string_fields(self):
        """Should accept empty strings for required fields."""
        report = FailureReport(namespace="", pod_name="")
        assert report.namespace == ""
        assert report.pod_name == ""
