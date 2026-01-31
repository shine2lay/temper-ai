"""
Comprehensive tests for JSON-RPC protocol.

Coverage:
- Request/response serialization
- Error handling
- Invalid JSON
- Missing fields
- Edge cases
"""

import json
import pytest

from coord_service.protocol import Request, Response


class TestRequestSerialization:
    """Test request serialization/deserialization."""

    def test_request_to_json(self):
        """Request should serialize to JSON."""
        req = Request(method='test_method', params={'key': 'value'}, id='req-123')

        json_str = req.to_json()
        obj = json.loads(json_str)

        assert obj['jsonrpc'] == '2.0'
        assert obj['method'] == 'test_method'
        assert obj['params'] == {'key': 'value'}
        assert obj['id'] == 'req-123'

    def test_request_from_json(self):
        """Request should deserialize from JSON."""
        json_str = json.dumps({
            'jsonrpc': '2.0',
            'method': 'test_method',
            'params': {'key': 'value'},
            'id': 'req-123'
        })

        req = Request.from_json(json_str)

        assert req.method == 'test_method'
        assert req.params == {'key': 'value'}
        assert req.id == 'req-123'

    def test_request_without_id(self):
        """Request without ID should generate one."""
        req = Request(method='test_method', params={})

        json_str = req.to_json()
        obj = json.loads(json_str)

        assert 'id' in obj
        assert obj['id'] is not None

    def test_request_without_params(self):
        """Request without params should default to empty dict."""
        json_str = json.dumps({
            'jsonrpc': '2.0',
            'method': 'test_method',
            'id': 'req-123'
        })

        req = Request.from_json(json_str)

        assert req.params == {}

    def test_request_roundtrip(self):
        """Request should roundtrip through JSON."""
        original = Request(
            method='test_method',
            params={'key': 'value', 'nested': {'data': [1, 2, 3]}},
            id='req-123'
        )

        json_str = original.to_json()
        restored = Request.from_json(json_str)

        assert restored.method == original.method
        assert restored.params == original.params
        assert restored.id == original.id


class TestResponseSerialization:
    """Test response serialization/deserialization."""

    def test_success_response_to_json(self):
        """Success response should serialize to JSON."""
        resp = Response.success('req-123', {'result': 'data'})

        json_str = resp.to_json()
        obj = json.loads(json_str)

        assert obj['jsonrpc'] == '2.0'
        assert obj['id'] == 'req-123'
        assert obj['result'] == {'result': 'data'}
        assert 'error' not in obj

    def test_error_response_to_json(self):
        """Error response should serialize to JSON."""
        resp = Response.error('req-123', 'ERROR_CODE', 'Error message')

        json_str = resp.to_json()
        obj = json.loads(json_str)

        assert obj['jsonrpc'] == '2.0'
        assert obj['id'] == 'req-123'
        assert obj['error']['code'] == 'ERROR_CODE'
        assert obj['error']['message'] == 'Error message'
        assert 'result' not in obj

    def test_error_response_with_data(self):
        """Error response with data should include it."""
        resp = Response.error(
            'req-123',
            'ERROR_CODE',
            'Error message',
            data={'details': 'more info'}
        )

        json_str = resp.to_json()
        obj = json.loads(json_str)

        assert obj['error']['data'] == {'details': 'more info'}

    def test_response_from_json(self):
        """Response should deserialize from JSON."""
        json_str = json.dumps({
            'jsonrpc': '2.0',
            'id': 'req-123',
            'result': {'data': 'value'}
        })

        resp = Response.from_json(json_str)

        assert resp.id == 'req-123'
        assert resp.result == {'data': 'value'}
        assert resp.error is None

    def test_response_roundtrip_success(self):
        """Success response should roundtrip through JSON."""
        original = Response.success('req-123', {'complex': {'nested': [1, 2, 3]}})

        json_str = original.to_json()
        restored = Response.from_json(json_str)

        assert restored.id == original.id
        assert restored.result == original.result
        assert restored.error == original.error

    def test_response_roundtrip_error(self):
        """Error response should roundtrip through JSON."""
        original = Response.error(
            'req-123',
            'ERROR_CODE',
            'Error message',
            data={'key': 'value'}
        )

        json_str = original.to_json()
        restored = Response.from_json(json_str)

        assert restored.id == original.id
        assert restored.error == original.error
        assert restored.result == original.result


class TestInvalidJSON:
    """Test handling of invalid JSON."""

    def test_request_invalid_json(self):
        """Invalid JSON should raise error."""
        with pytest.raises(json.JSONDecodeError):
            Request.from_json('not valid json{{{')

    def test_request_missing_method(self):
        """Request missing method should raise error."""
        with pytest.raises(KeyError):
            Request.from_json(json.dumps({
                'jsonrpc': '2.0',
                'params': {},
                'id': 'req-123'
            }))

    def test_response_invalid_json(self):
        """Invalid JSON should raise error."""
        with pytest.raises(json.JSONDecodeError):
            Response.from_json('not valid json{{{')

    def test_response_missing_id(self):
        """Response missing ID should raise error."""
        with pytest.raises(KeyError):
            Response.from_json(json.dumps({
                'jsonrpc': '2.0',
                'result': {}
            }))


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_params(self):
        """Empty params should work."""
        req = Request(method='test', params={})
        json_str = req.to_json()
        restored = Request.from_json(json_str)

        assert restored.params == {}

    def test_null_result(self):
        """Null result should work."""
        resp = Response.success('req-123', None)
        json_str = resp.to_json()
        obj = json.loads(json_str)

        assert obj['result'] is None

    def test_very_long_method_name(self):
        """Very long method name should work."""
        long_method = 'method_' * 1000
        req = Request(method=long_method, params={})

        json_str = req.to_json()
        restored = Request.from_json(json_str)

        assert restored.method == long_method

    def test_unicode_in_params(self):
        """Unicode in params should work."""
        req = Request(
            method='test',
            params={'unicode': '测试 📝', 'emoji': '🎉'}
        )

        json_str = req.to_json()
        restored = Request.from_json(json_str)

        assert restored.params['unicode'] == '测试 📝'
        assert restored.params['emoji'] == '🎉'

    def test_nested_complex_params(self):
        """Deeply nested complex params should work."""
        complex_params = {
            'level1': {
                'level2': {
                    'level3': {
                        'list': [1, 2, 3],
                        'dict': {'a': 'b'},
                        'null': None,
                        'bool': True
                    }
                }
            }
        }

        req = Request(method='test', params=complex_params)
        json_str = req.to_json()
        restored = Request.from_json(json_str)

        assert restored.params == complex_params

    def test_very_large_payload(self):
        """Very large payload should work."""
        large_params = {
            'data': 'x' * 1000000  # 1MB
        }

        req = Request(method='test', params=large_params)
        json_str = req.to_json()

        # Should serialize
        assert len(json_str) > 1000000

        restored = Request.from_json(json_str)
        assert len(restored.params['data']) == 1000000

    def test_special_characters_in_error_message(self):
        """Special characters in error message should work."""
        special_msg = 'Error: <script>alert("xss")</script> & "quotes" & \'quotes\''

        resp = Response.error('req-123', 'ERROR', special_msg)
        json_str = resp.to_json()
        restored = Response.from_json(json_str)

        assert restored.error['message'] == special_msg
