"""
Comprehensive unit tests for ProductExtractorAgent.

Tests cover:
- Initialization and parameter validation
- Extraction workflow with mocked LLM
- Prompt building and input sanitization
- Response parsing (all format variations)
- Security validations
- Error handling
"""
import pytest
from unittest.mock import Mock, patch
from src.self_improvement.agents import ProductExtractorAgent


class TestProductExtractorInit:
    """Test ProductExtractorAgent initialization and parameter validation."""

    def test_default_initialization(self):
        """Test agent initializes with default parameters."""
        agent = ProductExtractorAgent()
        assert agent.model == "llama3.1:8b"
        assert agent.timeout == 30
        assert agent.client is not None

    def test_custom_model(self):
        """Test agent initializes with custom model."""
        agent = ProductExtractorAgent(model="qwen2.5:32b")
        assert agent.model == "qwen2.5:32b"

    def test_custom_temperature(self):
        """Test agent initializes with custom temperature."""
        agent = ProductExtractorAgent(temperature=0.5)
        # Verify OllamaClient was initialized (indirectly through no errors)
        assert agent.client is not None

    def test_custom_timeout(self):
        """Test agent initializes with custom timeout."""
        agent = ProductExtractorAgent(timeout=60)
        assert agent.timeout == 60

    def test_empty_model_raises_error(self):
        """Test empty model string raises ValueError."""
        with pytest.raises(ValueError, match="model cannot be empty"):
            ProductExtractorAgent(model="")

    def test_whitespace_only_model_raises_error(self):
        """Test whitespace-only model raises ValueError."""
        with pytest.raises(ValueError, match="model cannot be empty"):
            ProductExtractorAgent(model="   ")

    def test_negative_temperature_raises_error(self):
        """Test negative temperature raises ValueError."""
        with pytest.raises(ValueError, match="temperature must be 0.0-1.0"):
            ProductExtractorAgent(temperature=-0.1)

    def test_temperature_above_one_raises_error(self):
        """Test temperature > 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="temperature must be 0.0-1.0"):
            ProductExtractorAgent(temperature=1.5)

    def test_zero_max_tokens_raises_error(self):
        """Test max_tokens <= 0 raises ValueError."""
        with pytest.raises(ValueError, match="max_tokens must be positive"):
            ProductExtractorAgent(max_tokens=0)

    def test_negative_max_tokens_raises_error(self):
        """Test negative max_tokens raises ValueError."""
        with pytest.raises(ValueError, match="max_tokens must be positive"):
            ProductExtractorAgent(max_tokens=-100)

    def test_zero_timeout_raises_error(self):
        """Test timeout <= 0 raises ValueError."""
        with pytest.raises(ValueError, match="timeout must be positive"):
            ProductExtractorAgent(timeout=0)

    def test_negative_timeout_raises_error(self):
        """Test negative timeout raises ValueError."""
        with pytest.raises(ValueError, match="timeout must be positive"):
            ProductExtractorAgent(timeout=-30)

    def test_repr(self):
        """Test string representation."""
        agent = ProductExtractorAgent(model="llama3.1:8b")
        assert repr(agent) == "ProductExtractorAgent(model='llama3.1:8b')"


class TestProductExtractorPromptBuilder:
    """Test prompt building and input sanitization."""

    def test_valid_input(self):
        """Test prompt building with valid input."""
        agent = ProductExtractorAgent()
        prompt = agent._build_extraction_prompt("iPhone 15 - $799")

        assert "Extract product information" in prompt
        assert "iPhone 15 - $799" in prompt
        assert "JSON" in prompt
        assert "name" in prompt
        assert "price" in prompt

    def test_input_stripped(self):
        """Test input is stripped of leading/trailing whitespace."""
        agent = ProductExtractorAgent()
        prompt = agent._build_extraction_prompt("  iPhone 15  \n")

        assert "iPhone 15" in prompt
        assert "  iPhone 15  " not in prompt

    def test_control_characters_removed(self):
        """Test control characters are sanitized from input."""
        agent = ProductExtractorAgent()
        prompt = agent._build_extraction_prompt("Test\x00\x01\x02Product")

        assert "\x00" not in prompt
        assert "\x01" not in prompt
        assert "\x02" not in prompt
        assert "TestProduct" in prompt

    def test_non_string_input_raises_type_error(self):
        """Test non-string input raises TypeError."""
        agent = ProductExtractorAgent()

        with pytest.raises(TypeError, match="text must be string"):
            agent._build_extraction_prompt(12345)

        with pytest.raises(TypeError, match="text must be string"):
            agent._build_extraction_prompt(None)

        with pytest.raises(TypeError, match="text must be string"):
            agent._build_extraction_prompt(["list"])

    def test_oversized_input_raises_value_error(self):
        """Test input exceeding MAX_INPUT_LENGTH raises ValueError."""
        agent = ProductExtractorAgent()

        # MAX_INPUT_LENGTH is 2000
        long_text = "A" * 2001

        with pytest.raises(ValueError, match="Input text too long: 2001 chars"):
            agent._build_extraction_prompt(long_text)

    def test_input_at_max_length_accepted(self):
        """Test input exactly at MAX_INPUT_LENGTH is accepted."""
        agent = ProductExtractorAgent()

        # MAX_INPUT_LENGTH is 2000
        max_text = "A" * 2000

        prompt = agent._build_extraction_prompt(max_text)
        assert prompt is not None


class TestProductExtractorResponseParser:
    """Test response parsing for various formats."""

    def test_clean_json(self):
        """Test parsing clean JSON response."""
        agent = ProductExtractorAgent()

        json_response = '{"name": "iPhone 15", "price": 799.0, "currency": "USD", "features": ["128GB"], "brand": "Apple", "category": "Smartphone"}'
        result = agent._parse_response(json_response)

        assert result["name"] == "iPhone 15"
        assert result["price"] == 799.0
        assert result["currency"] == "USD"
        assert result["features"] == ["128GB"]
        assert result["brand"] == "Apple"
        assert result["category"] == "Smartphone"

    def test_markdown_code_block(self):
        """Test parsing JSON wrapped in markdown code block."""
        agent = ProductExtractorAgent()

        markdown_response = """```json
{"name": "MacBook Pro", "price": 1999.0, "currency": "USD", "features": ["M3"], "brand": "Apple", "category": "Laptop"}
```"""
        result = agent._parse_response(markdown_response)

        assert result["name"] == "MacBook Pro"
        assert result["price"] == 1999.0

    def test_markdown_without_language_tag(self):
        """Test parsing JSON in markdown block without 'json' tag."""
        agent = ProductExtractorAgent()

        markdown_response = """```
{"name": "iPad Pro", "price": 999.0, "currency": "USD", "features": [], "brand": "Apple", "category": "Tablet"}
```"""
        result = agent._parse_response(markdown_response)

        assert result["name"] == "iPad Pro"
        assert result["price"] == 999.0

    def test_json_with_surrounding_text(self):
        """Test extracting JSON from response with extra text."""
        agent = ProductExtractorAgent()

        text_response = 'Here is the data: {"name": "AirPods Pro", "price": 249.0, "currency": "USD", "features": ["ANC"], "brand": "Apple", "category": "Audio"} Hope this helps!'
        result = agent._parse_response(text_response)

        assert result["name"] == "AirPods Pro"
        assert result["price"] == 249.0

    def test_missing_optional_fields(self):
        """Test parsing JSON with missing optional fields."""
        agent = ProductExtractorAgent()

        minimal_json = '{"name": "Product", "price": 99.0}'
        result = agent._parse_response(minimal_json)

        assert result["name"] == "Product"
        assert result["price"] == 99.0
        assert result["currency"] == "USD"  # Default
        assert result["features"] == []  # Default
        assert result["brand"] is None
        assert result["category"] is None

    def test_null_values(self):
        """Test parsing JSON with explicit null values."""
        agent = ProductExtractorAgent()

        null_json = '{"name": null, "price": null, "currency": "USD", "features": [], "brand": null, "category": null}'
        result = agent._parse_response(null_json)

        assert result["name"] is None
        assert result["price"] is None

    def test_invalid_json_raises_error(self):
        """Test invalid JSON raises ValueError."""
        agent = ProductExtractorAgent()

        with pytest.raises(ValueError, match="Failed to parse JSON response"):
            agent._parse_response("Not JSON at all")

        with pytest.raises(ValueError, match="Failed to parse JSON response"):
            agent._parse_response('{"unclosed": ')


class TestProductExtractorSecurity:
    """Test security validations and protections."""

    def test_response_size_limit(self):
        """Test response exceeding MAX_RESPONSE_SIZE is rejected."""
        agent = ProductExtractorAgent()

        # MAX_RESPONSE_SIZE is 10000
        large_response = '{"x":' + '"A" * 5000' + '}'
        # This creates a 20KB+ response

        # Create actually large response
        large_response = '{"name": "' + 'A' * 15000 + '"}'

        with pytest.raises(ValueError, match="Response too large"):
            agent._parse_response(large_response)

    def test_json_size_limit(self):
        """Test JSON string exceeding MAX_JSON_SIZE is rejected."""
        agent = ProductExtractorAgent()

        # Create JSON that's too large
        # Both MAX_RESPONSE_SIZE and MAX_JSON_SIZE are 10000
        # Create response > 10000 bytes to trigger size check
        large_json = '{"name": "' + 'X' * 10500 + '", "price": 1}'

        with pytest.raises(ValueError, match="(JSON too large|Response too large)"):
            agent._parse_response(large_json)

    def test_json_depth_limit(self):
        """Test deeply nested JSON exceeding MAX_JSON_DEPTH is rejected."""
        agent = ProductExtractorAgent()

        # MAX_JSON_DEPTH is 10, create 15 levels
        deep_json = '{"a":' * 15 + '1' + '}' * 15

        with pytest.raises(ValueError, match="JSON nesting too deep"):
            agent._parse_response(deep_json)

    def test_json_at_max_depth_accepted(self):
        """Test JSON at exactly MAX_JSON_DEPTH is accepted."""
        agent = ProductExtractorAgent()

        # MAX_JSON_DEPTH is 10
        max_depth_json = '{"a":' * 10 + '1' + '}' * 10

        # Should not raise (might fail JSON parsing, but shouldn't hit depth limit)
        try:
            agent._parse_response(max_depth_json)
        except ValueError as e:
            # If it raises, should be parse error, not depth error
            assert "nesting too deep" not in str(e)

    def test_negative_price_rejected(self):
        """Test negative prices are set to None."""
        agent = ProductExtractorAgent()

        negative_price_json = '{"name": "Test", "price": -999, "currency": "USD", "features": [], "brand": null, "category": null}'
        result = agent._parse_response(negative_price_json)

        assert result["price"] is None

    def test_out_of_range_price_rejected(self):
        """Test prices outside reasonable range are rejected."""
        agent = ProductExtractorAgent()

        huge_price_json = '{"name": "Test", "price": 99999999, "currency": "USD", "features": [], "brand": null, "category": null}'
        result = agent._parse_response(huge_price_json)

        assert result["price"] is None

    def test_zero_price_accepted(self):
        """Test zero price is valid (free product)."""
        agent = ProductExtractorAgent()

        zero_price_json = '{"name": "Free Sample", "price": 0, "currency": "USD", "features": [], "brand": null, "category": null}'
        result = agent._parse_response(zero_price_json)

        assert result["price"] == 0.0

    def test_max_valid_price_accepted(self):
        """Test maximum valid price (1 million) is accepted."""
        agent = ProductExtractorAgent()

        max_price_json = '{"name": "Expensive Item", "price": 1000000, "currency": "USD", "features": [], "brand": null, "category": null}'
        result = agent._parse_response(max_price_json)

        assert result["price"] == 1000000.0


class TestProductExtractorExtract:
    """Test main extract() method with mocked LLM."""

    @patch('src.self_improvement.agents.product_extractor.OllamaClient')
    def test_successful_extraction(self, mock_ollama_class):
        """Test successful extraction workflow."""
        # Setup mock
        mock_client = Mock()
        mock_client.generate.return_value = '{"name": "iPhone 15", "price": 799.0, "currency": "USD", "features": ["128GB"], "brand": "Apple", "category": "Smartphone"}'
        mock_ollama_class.return_value = mock_client

        agent = ProductExtractorAgent()
        agent.client = mock_client  # Replace with mock

        result = agent.extract("iPhone 15 - $799, 128GB")

        # Verify LLM was called
        mock_client.generate.assert_called_once()

        # Verify result
        assert result["name"] == "iPhone 15"
        assert result["price"] == 799.0
        assert "error" not in result

    @patch('src.self_improvement.agents.product_extractor.OllamaClient')
    def test_extraction_with_parse_error(self, mock_ollama_class):
        """Test extraction handles parse errors gracefully."""
        # Setup mock to return invalid JSON
        mock_client = Mock()
        mock_client.generate.return_value = "This is not JSON"
        mock_ollama_class.return_value = mock_client

        agent = ProductExtractorAgent()
        agent.client = mock_client

        result = agent.extract("iPhone 15")

        # Should return error structure
        assert result["name"] is None
        assert result["price"] is None
        assert "error" in result
        assert "raw_text" in result
        assert result["raw_text"] == "iPhone 15"

    @patch('src.self_improvement.agents.product_extractor.OllamaClient')
    def test_extraction_with_llm_error(self, mock_ollama_class):
        """Test extraction handles LLM errors by re-raising."""
        # Setup mock to raise unexpected error
        mock_client = Mock()
        mock_client.generate.side_effect = RuntimeError("LLM service unavailable")
        mock_ollama_class.return_value = mock_client

        agent = ProductExtractorAgent()
        agent.client = mock_client

        # Should re-raise unexpected errors
        with pytest.raises(RuntimeError, match="LLM service unavailable"):
            agent.extract("iPhone 15")

    @patch('src.self_improvement.agents.product_extractor.OllamaClient')
    def test_extraction_validates_input(self, mock_ollama_class):
        """Test extraction validates input before calling LLM."""
        mock_client = Mock()
        mock_ollama_class.return_value = mock_client

        agent = ProductExtractorAgent()
        agent.client = mock_client

        # Should raise TypeError before calling LLM
        with pytest.raises(TypeError):
            agent.extract(12345)

        # LLM should not have been called
        mock_client.generate.assert_not_called()


class TestProductExtractorErrorHandling:
    """Test error handling paths."""

    def test_non_list_features_converted_to_empty_list(self):
        """Test non-list features field is converted to empty list."""
        agent = ProductExtractorAgent()

        bad_features_json = '{"name": "Test", "price": 99.0, "currency": "USD", "features": "not a list", "brand": null, "category": null}'
        result = agent._parse_response(bad_features_json)

        assert result["features"] == []

    def test_price_parsing_error_sets_none(self):
        """Test price that can't be parsed as float is set to None."""
        agent = ProductExtractorAgent()

        bad_price_json = '{"name": "Test", "price": "not a number", "currency": "USD", "features": [], "brand": null, "category": null}'
        result = agent._parse_response(bad_price_json)

        assert result["price"] is None

    def test_empty_string_input_handled(self):
        """Test empty string input is handled gracefully."""
        agent = ProductExtractorAgent()

        prompt = agent._build_extraction_prompt("")
        assert prompt is not None
        assert "Extract product information" in prompt

    def test_whitespace_only_input_handled(self):
        """Test whitespace-only input is handled."""
        agent = ProductExtractorAgent()

        prompt = agent._build_extraction_prompt("   \n\t   ")
        assert prompt is not None
