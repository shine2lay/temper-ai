"""
JSON-RPC protocol for coordination service.

Defines the message format and protocol for client-server communication.
"""

import json
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


@dataclass
class Request:
    """JSON-RPC request."""
    method: str
    params: Dict[str, Any]
    id: Optional[str] = None

    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps({
            "jsonrpc": "2.0",
            "method": self.method,
            "params": self.params,
            "id": self.id or str(uuid.uuid4())
        })

    @classmethod
    def from_json(cls, data: str) -> 'Request':
        """Deserialize from JSON."""
        obj = json.loads(data)
        return cls(
            method=obj['method'],
            params=obj.get('params', {}),
            id=obj.get('id')
        )


@dataclass
class Response:
    """JSON-RPC response."""
    id: str
    result: Optional[Any] = None
    error: Optional[Dict] = None

    def to_json(self) -> str:
        """Serialize to JSON."""
        obj = {
            "jsonrpc": "2.0",
            "id": self.id
        }
        if self.error:
            obj["error"] = self.error
        else:
            obj["result"] = self.result
        return json.dumps(obj)

    @classmethod
    def from_json(cls, data: str) -> 'Response':
        """Deserialize from JSON."""
        obj = json.loads(data)
        return cls(
            id=obj['id'],
            result=obj.get('result'),
            error=obj.get('error')
        )

    @classmethod
    def success(cls, request_id: str, result: Any) -> 'Response':
        """Create success response."""
        return cls(id=request_id, result=result)

    @classmethod
    def create_error(cls, request_id: str, code: str, message: str, data: Dict = None) -> 'Response':
        """Create error response."""
        error_dict = {
            "code": code,
            "message": message
        }
        if data:
            error_dict["data"] = data
        return cls(id=request_id, error=error_dict)


class ProtocolError(Exception):
    """Base class for protocol errors."""
    pass


class ParseError(ProtocolError):
    """Invalid JSON received."""
    pass


class InvalidRequest(ProtocolError):
    """Invalid request structure."""
    pass


class MethodNotFound(ProtocolError):
    """Unknown method."""
    pass


class InvalidParams(ProtocolError):
    """Invalid method parameters."""
    pass
