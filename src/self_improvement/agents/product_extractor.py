"""
ProductExtractorAgent for M5 Self-Improvement System.

This agent extracts structured product information from unstructured text using
Ollama models. It's used as a test workload for M5's model selection experiments.

Example:
    Input: "iPhone 15 Pro - $999, 256GB storage, A17 Pro chip"
    Output: {
        "name": "iPhone 15 Pro",
        "price": 999.0,
        "features": ["256GB storage", "A17 Pro chip"]
    }
"""
import json
import logging
from typing import Any, Dict, Optional

from src.self_improvement.ollama_client import OllamaClient

# Configure logging
logger = logging.getLogger(__name__)

# Extraction quality constants
DEFAULT_EXTRACTION_TEMPERATURE = 0.3  # Low temperature for deterministic structured output
DEFAULT_EXTRACTION_TIMEOUT_SECONDS = 30  # Request timeout
MAX_PRODUCT_PRICE_USD = 1000000  # Reasonable maximum price for product validation
LOG_TEXT_PREVIEW_LENGTH = 100  # Length of text to log in error messages

# Security limits
MAX_INPUT_LENGTH = 2000  # Maximum chars in input text
MAX_RESPONSE_SIZE = 10000  # Maximum response size (10KB)
MAX_JSON_DEPTH = 10  # Maximum JSON nesting depth
MAX_JSON_SIZE = 10000  # Maximum JSON string size


class ProductExtractorAgent:
    """
    Agent that extracts structured product information using Ollama.

    This agent is designed as a benchmark workload for M5's model selection
    experiments. It tests the ability of different Ollama models to extract
    structured data from unstructured text.

    Quality Metrics:
    - Extraction completeness (all fields extracted)
    - Price accuracy (correct parsing)
    - Feature identification (captures all features)

    Usage:
        # Basic usage
        agent = ProductExtractorAgent(model="llama3.1:8b")
        result = agent.extract("iPhone 15 - $799")
        print(result)  # {"name": "iPhone 15", "price": 799.0, ...}

        # Used in M5 experiments
        experiment = {
            "control": ProductExtractorAgent("llama3.1:8b"),
            "variant_a": ProductExtractorAgent("phi3:mini"),
            "variant_b": ProductExtractorAgent("qwen2.5:32b"),
        }
    """

    def __init__(
        self,
        model: str = "llama3.1:8b",
        temperature: float = DEFAULT_EXTRACTION_TEMPERATURE,
        max_tokens: int = 512,
        timeout: int = DEFAULT_EXTRACTION_TIMEOUT_SECONDS,
    ):
        """
        Initialize ProductExtractorAgent.

        Args:
            model: Ollama model to use (e.g., "llama3.1:8b", "qwen2.5:32b")
            temperature: Lower = more deterministic (default: DEFAULT_EXTRACTION_TEMPERATURE for structured output)
            max_tokens: Maximum tokens to generate (default: 512)
            timeout: Request timeout in seconds (default: DEFAULT_EXTRACTION_TIMEOUT_SECONDS)

        Raises:
            ValueError: If parameters are invalid
        """
        # Validate parameters
        if not model or not model.strip():
            raise ValueError("model cannot be empty")

        if not 0.0 <= temperature <= 1.0:
            raise ValueError(f"temperature must be 0.0-1.0, got: {temperature}")

        if max_tokens < 1:
            raise ValueError(f"max_tokens must be positive, got: {max_tokens}")

        if timeout < 1:
            raise ValueError(f"timeout must be positive, got: {timeout}")

        self.model = model
        self.timeout = timeout
        self.client = OllamaClient(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    def extract(self, text: str) -> Dict[str, Any]:
        """
        Extract structured product information from text.

        Args:
            text: Unstructured product description

        Returns:
            Dictionary with extracted product data:
            {
                "name": str or None,           # Product name
                "price": float or None,        # Price in USD (None if not found)
                "currency": str,               # Currency symbol (default: "USD")
                "features": [str],             # List of product features
                "brand": str or None,          # Brand name if identified
                "category": str or None,       # Product category if identified
                "error": str or None,          # Error message if extraction failed
                "raw_text": str or None,       # Original input if extraction failed
            }

        Raises:
            TypeError: If text is not a string
            ValueError: If text exceeds maximum length
            LLMTimeoutError: If generation exceeds timeout
            LLMError: If generation fails (unexpected errors)

        Example:
            >>> agent = ProductExtractorAgent()
            >>> agent.extract("MacBook Pro M3 - $1999, 16GB RAM, 512GB SSD")
            {
                "name": "MacBook Pro M3",
                "price": 1999.0,
                "currency": "USD",
                "features": ["16GB RAM", "512GB SSD"],
                "brand": "Apple",
                "category": "Laptop"
            }
        """
        # Build extraction prompt (validates input)
        prompt = self._build_extraction_prompt(text)

        # Call Ollama model
        try:
            response = self.client.generate(prompt)

            # Parse JSON response (validates response)
            product_data = self._parse_response(response)

            return product_data

        except (ValueError, json.JSONDecodeError) as e:
            # Expected parsing errors - log and return fallback
            logger.warning(
                "Product extraction failed for text: %s, error: %s",
                text[:LOG_TEXT_PREVIEW_LENGTH],  # Log preview only
                str(e),
                exc_info=True
            )
            return {
                "name": None,
                "price": None,
                "currency": "USD",
                "features": [],
                "brand": None,
                "category": None,
                "error": str(e),
                "raw_text": text,
            }

        except Exception as e:
            # Unexpected errors - log and re-raise
            logger.error(
                "Unexpected error in product extraction: %s",
                str(e),
                exc_info=True
            )
            raise  # Don't swallow unexpected errors

    def _build_extraction_prompt(self, text: str) -> str:
        """
        Build structured extraction prompt for Ollama.

        Args:
            text: Input text to extract from

        Returns:
            Formatted prompt string

        Raises:
            TypeError: If text is not a string
            ValueError: If text exceeds maximum length
        """
        # Validate input type
        if not isinstance(text, str):
            raise TypeError(f"text must be string, got: {type(text)}")

        # Validate input length
        if len(text) > MAX_INPUT_LENGTH:
            raise ValueError(
                f"Input text too long: {len(text)} chars (max: {MAX_INPUT_LENGTH})"
            )

        # Sanitize: remove control characters that could break prompt
        sanitized_text = text.strip()
        sanitized_text = ''.join(c for c in sanitized_text if c.isprintable() or c.isspace())

        return f"""Extract product information from the following text and return ONLY valid JSON.

Text: {sanitized_text}

Return a JSON object with these fields:
- name: product name (string)
- price: price as a number (float, null if not found)
- currency: currency code (string, default "USD")
- features: list of product features (array of strings)
- brand: brand name if identifiable (string or null)
- category: product category if identifiable (string or null)

Example output format:
{{"name": "iPhone 15", "price": 799.0, "currency": "USD", "features": ["128GB", "5G"], "brand": "Apple", "category": "Smartphone"}}

JSON output:"""

    def _validate_json_safety(self, json_str: str) -> None:
        """
        Validate JSON string is safe to parse (prevents DoS attacks).

        Args:
            json_str: JSON string to validate

        Raises:
            ValueError: If JSON is unsafe (too large or deeply nested)
        """
        if len(json_str) > MAX_JSON_SIZE:
            raise ValueError(f"JSON too large: {len(json_str)} bytes (max: {MAX_JSON_SIZE})")

        # Simple depth check: count maximum nesting level
        depth = 0
        max_depth = 0
        for char in json_str:
            if char in '{[':
                depth += 1
                max_depth = max(max_depth, depth)
                if max_depth > MAX_JSON_DEPTH:
                    raise ValueError(f"JSON nesting too deep: >{MAX_JSON_DEPTH}")
            elif char in '}]':
                depth -= 1

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """
        Parse LLM response into structured data.

        Handles various response formats:
        1. Clean JSON
        2. JSON wrapped in markdown code blocks
        3. JSON with extra text around it

        Args:
            response: Raw response from Ollama

        Returns:
            Parsed product data dictionary

        Raises:
            ValueError: If response cannot be parsed as JSON or is unsafe
        """
        # Validate response size
        if len(response) > MAX_RESPONSE_SIZE:
            raise ValueError(
                f"Response too large: {len(response)} bytes (max: {MAX_RESPONSE_SIZE})"
            )

        # Extract JSON string from response
        json_str = self._extract_json_from_response(response)

        # Validate JSON safety before parsing
        self._validate_json_safety(json_str)

        # Parse and validate JSON
        try:
            data = json.loads(json_str)
            return self._extract_product_fields(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON response: {e}\nResponse: {json_str[:200]}")  # noqa: Preview length

    def _extract_json_from_response(self, response: str) -> str:
        """Extract JSON string from response, handling markdown code blocks."""
        response = response.strip()

        # Remove markdown code blocks if present
        if response.startswith("```"):
            lines = response.split('\n')
            json_lines = []
            in_code_block = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    continue
                if in_code_block:
                    json_lines.append(line)
            if json_lines:
                response = '\n'.join(json_lines)

        # Extract JSON object from response
        first_brace = response.find('{')
        last_brace = response.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            response = response[first_brace:last_brace + 1]

        return response

    def _extract_product_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and validate product fields from parsed JSON."""
        product_data = {
            "name": data.get("name"),
            "price": data.get("price"),
            "currency": data.get("currency", "USD"),
            "features": data.get("features", []),
            "brand": data.get("brand"),
            "category": data.get("category"),
        }

        # Validate and normalize price
        product_data["price"] = self._validate_price(product_data["price"])

        # Ensure features is a list
        if not isinstance(product_data["features"], list):
            product_data["features"] = []

        return product_data

    def _validate_price(self, price: Any) -> Optional[float]:
        """Validate and normalize price value."""
        if price is None:
            return None

        try:
            price_float = float(price)

            # Check for invalid values
            if price_float < 0:
                logger.warning("Negative price detected: %s, setting to None", price_float)
                return None
            if not (0 <= price_float <= MAX_PRODUCT_PRICE_USD):
                logger.warning("Price out of range: %s, setting to None", price_float)
                return None
            if price_float != price_float:  # NaN check
                logger.warning("Invalid price (NaN), setting to None")
                return None
            if price_float in (float('inf'), float('-inf')):
                logger.warning("Invalid price (infinity), setting to None")
                return None

            return price_float

        except (ValueError, TypeError) as e:
            logger.debug("Price parsing failed: %s", e)
            return None

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"ProductExtractorAgent(model='{self.model}')"
