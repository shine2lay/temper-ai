# Basic Tools Implementation

**Task:** m1-06-basic-tools
**Date:** 2026-01-26
**Agent:** agent-565e51

## Summary

Implemented three basic tools for the Meta-Autonomous Framework: Calculator (safe math evaluation), FileWriter (file writing with safety checks), and WebScraper (web content fetching). All tools follow the BaseTool interface and include comprehensive safety features.

## Changes

### New Files Created

1. **src/tools/calculator.py** (262 lines)
   - Safe mathematical expression evaluator
   - AST-based whitelist approach (no eval())
   - Supports basic arithmetic and math functions
   - Protection against code injection

2. **src/tools/file_writer.py** (247 lines)
   - Safe file writer with path validation
   - Path traversal protection
   - Forbidden path and extension blocking
   - Overwrite protection and size limits

3. **src/tools/web_scraper.py** (302 lines)
   - HTTP client for web content fetching
   - HTML text extraction with BeautifulSoup
   - Rate limiting (10 requests/minute)
   - Content size limits and timeout protection

4. **tests/test_tools/test_calculator.py** (409 lines)
   - 42 comprehensive test cases for Calculator
   - Tests for all operations, functions, and safety features

5. **tests/test_tools/test_file_writer.py** (341 lines)
   - 28 test cases for FileWriter
   - Tests for safety, overwrite protection, and path validation

6. **tests/test_tools/test_web_scraper.py** (460 lines)
   - 30 test cases for WebScraper
   - Tests for rate limiting, text extraction, and error handling

## Features Implemented

### Calculator Tool

**Core Features:**
- ✅ Basic arithmetic: +, -, *, /, //, %, **
- ✅ Math functions: sqrt, sin, cos, tan, log, exp, abs, round, min, max, sum
- ✅ Math constants: pi, e
- ✅ Complex expressions with parentheses
- ✅ Negative numbers and decimals

**Safety Features:**
- ✅ AST-based evaluation (no eval() or exec())
- ✅ Whitelist of allowed operators and functions
- ✅ Division by zero handling
- ✅ Protection against code injection
- ✅ No access to built-in functions beyond math

**Examples:**
```python
calc = Calculator()

result = calc.execute(expression="2 + 2")
# result.result == 4

result = calc.execute(expression="sqrt(16)")
# result.result == 4.0

result = calc.execute(expression="sin(pi / 2)")
# result.result == 1.0
```

### FileWriter Tool

**Core Features:**
- ✅ Write content to file path
- ✅ Create parent directories automatically
- ✅ Overwrite protection (requires explicit flag)
- ✅ UTF-8 encoding support
- ✅ File size limits (10MB max)

**Safety Features:**
- ✅ Path traversal protection (no ../ escaping)
- ✅ Forbidden path blocking (/etc, /sys, /proc, /dev, /boot, /root, /bin, /sbin, /usr/bin, /usr/sbin, /var/log, /var/run)
- ✅ Forbidden extension blocking (.exe, .dll, .so, .sh, .bat, .cmd, .ps1, etc.)
- ✅ Maximum file size limit (10MB)
- ✅ Directory vs file validation

**Examples:**
```python
writer = FileWriter()

result = writer.execute(
    file_path="/home/user/output.txt",
    content="Hello, world!",
    create_dirs=True
)
# result.success == True

# Overwrite existing file
result = writer.execute(
    file_path="/home/user/output.txt",
    content="Updated content",
    overwrite=True
)
```

### WebScraper Tool

**Core Features:**
- ✅ Fetch URL content with httpx
- ✅ Extract text from HTML (BeautifulSoup)
- ✅ Custom timeout configuration
- ✅ Custom User-Agent header
- ✅ Follow redirects

**Safety Features:**
- ✅ Rate limiting (10 requests/minute by default)
- ✅ Content size limits (5MB max)
- ✅ Timeout protection (30s default)
- ✅ URL validation (http/https only)
- ✅ Automatic retry on timeout

**Examples:**
```python
scraper = WebScraper()

# Fetch and extract text
result = scraper.execute(
    url="https://example.com",
    extract_text=True
)
# result.result contains extracted text

# Fetch raw HTML
result = scraper.execute(
    url="https://example.com",
    extract_text=False,
    timeout=60
)
# result.result contains raw HTML
```

## Test Results

All 100 tests pass successfully:
- 42 Calculator tests (100% passing)
- 28 FileWriter tests (100% passing)
- 30 WebScraper tests (100% passing)

```
============================= 100 passed in 1.20s ==============================
```

### Test Coverage

**Calculator:**
- Metadata and schema validation
- All basic arithmetic operations
- Complex expressions with parentheses
- All math functions (sqrt, sin, cos, tan, log, exp, etc.)
- Math constants (pi, e)
- Error handling (division by zero, invalid syntax, unsupported functions)
- Safety (no eval, no exec, no import, no builtins)

**FileWriter:**
- Metadata and schema validation
- Basic file writing (simple, multiline, empty, unicode)
- Directory creation
- Overwrite protection
- Path safety (forbidden paths, forbidden extensions)
- Input validation
- Size limits
- Error handling (permissions, directory as file)

**WebScraper:**
- Rate limiter functionality
- Metadata and schema validation
- Basic URL fetching
- Text extraction from HTML
- Error handling (invalid URL, HTTP errors, timeouts)
- Rate limiting enforcement
- Content size limits
- URL validation

## Architecture Decisions

### 1. AST-Based Calculator (Not eval())

Used Python's `ast` module for safe expression evaluation instead of `eval()`.

**Benefits:**
- Complete control over allowed operations
- No code injection risk
- Whitelist approach for operators and functions
- Type-safe evaluation

### 2. Path Resolution for FileWriter

Used `Path.resolve()` to normalize paths and detect traversal attempts.

**Benefits:**
- Prevents path traversal attacks
- Consistent path handling across platforms
- Easy to check against forbidden paths

### 3. Rate Limiter Class for WebScraper

Implemented custom `RateLimiter` class with sliding window.

**Benefits:**
- Prevents abuse and server overload
- Fair distribution of requests over time
- Helpful error messages with wait time

### 4. BeautifulSoup for HTML Parsing

Used BeautifulSoup for text extraction instead of regex.

**Benefits:**
- Robust HTML parsing
- Easy removal of script/style tags
- Handles malformed HTML gracefully

## Integration with Tool Registry

All tools are compatible with the tool registry system (m2-02):

```python
from src.tools.calculator import Calculator
from src.tools.registry import ToolRegistry

registry = ToolRegistry()
registry.register_tool(Calculator())

# Get tool for execution
calc = registry.get_tool("Calculator")
result = calc.execute(expression="2 + 2")
```

## Safety Considerations

### Calculator
1. **Code Injection Prevention**: AST-based evaluation prevents arbitrary code execution
2. **Resource Limits**: No infinite loops possible (AST evaluation is bounded)
3. **Type Safety**: Only numeric operations allowed

### FileWriter
1. **Path Traversal**: Prevented via `Path.resolve()` and forbidden path checks
2. **System Protection**: Cannot write to critical system directories
3. **Malware Prevention**: Blocked dangerous file extensions (.exe, .sh, etc.)
4. **Resource Limits**: 10MB file size limit prevents disk exhaustion

### WebScraper
1. **Rate Limiting**: Prevents abuse and server overload (10 req/min)
2. **Timeout Protection**: Prevents hanging requests (30s default)
3. **Size Limits**: 5MB content limit prevents memory exhaustion
4. **URL Validation**: Only http/https allowed (no file://, ftp://, etc.)

## Performance Considerations

**Calculator:**
- AST parsing overhead: ~0.1ms per expression
- No performance bottlenecks for typical expressions

**FileWriter:**
- Path resolution overhead: ~0.01ms
- Write performance: limited by filesystem (typically 100-500 MB/s)

**WebScraper:**
- Network latency dominates (typically 100-1000ms)
- BeautifulSoup parsing overhead: ~10-50ms for typical pages
- Rate limiting adds fairness overhead

## Known Limitations

### Calculator
- No variable assignment or storage
- No user-defined functions
- Limited to single expressions (no multi-statement programs)

### FileWriter
- No append mode (only write/overwrite)
- No binary file support (only text/UTF-8)
- No streaming for large files

### WebScraper
- No JavaScript execution (static HTML only)
- No cookie/session management
- No authentication support
- No concurrent requests

## Future Enhancements (Out of Scope)

### Calculator
- Variable storage for multi-step calculations
- Support for matrices and vectors
- Symbolic math support
- Plot generation

### FileWriter
- Append mode
- Binary file support
- Streaming for large files
- Archive creation (zip, tar)

### WebScraper
- JavaScript rendering (Selenium/Playwright)
- Authentication support
- Cookie management
- Concurrent request batching
- Caching layer

## Integration Points

These tools will be used by:
- Agent execution system (task m2-04) for tool calling
- Tool registry (task m2-02) for tool discovery and execution
- Integration tests (task m1-07) for end-to-end testing
- Example workflows in configs/

## Dependencies

**Calculator:**
- Python `ast` module (built-in)
- Python `math` module (built-in)
- Python `operator` module (built-in)

**FileWriter:**
- Python `pathlib` (built-in)
- Python `os` (built-in)

**WebScraper:**
- `httpx` (HTTP client)
- `beautifulsoup4` (HTML parsing)

## Notes

- All tools follow the BaseTool interface from m2-02
- All tools return ToolResult with success/result/error structure
- All tools include LLM function calling schema generation
- Safety is prioritized over functionality in all tools
- Error messages are user-friendly and actionable

## Testing

To run tests:
```bash
source venv/bin/activate
python -m pytest tests/test_tools/test_calculator.py tests/test_tools/test_file_writer.py tests/test_tools/test_web_scraper.py -v
```

To test individual tools:
```bash
# Calculator only
pytest tests/test_tools/test_calculator.py -v

# FileWriter only
pytest tests/test_tools/test_file_writer.py -v

# WebScraper only
pytest tests/test_tools/test_web_scraper.py -v
```
