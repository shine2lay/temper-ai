# Integration Guide

Guide to integrating the Temper AI with external systems, APIs, databases, and services.

---

## Table of Contents

1. [Overview](#overview)
2. [API Integration](#api-integration)
3. [Database Integration](#database-integration)
4. [Web Framework Integration](#web-framework-integration)
5. [Message Queue Integration](#message-queue-integration)
6. [External Tool Integration](#external-tool-integration)
7. [LLM Provider Integration](#llm-provider-integration)
8. [Authentication & Security](#authentication--security)
9. [Monitoring Integration](#monitoring-integration)
10. [Examples](#examples)

---

## Overview

The framework provides multiple integration points:

- **API Layer:** REST/GraphQL endpoints for workflow execution
- **Database:** Observability data storage
- **Message Queues:** Async workflow triggering
- **Webhooks:** Event-driven workflows
- **Custom Tools:** Integrate external services
- **LLM Providers:** Add custom providers
- **Execution Engines:** Alternative workflow engines

---

## API Integration

### Flask Integration

**Create API server:**

```python
# api/server.py
from flask import Flask, request, jsonify
from temper_ai.compiler.engine_registry import EngineRegistry
from temper_ai.compiler.config_loader import ConfigLoader

app = Flask(__name__)

@app.route('/api/workflows/<workflow_name>/execute', methods=['POST'])
def execute_workflow(workflow_name):
    """Execute a workflow via API."""
    # Load workflow
    loader = ConfigLoader()
    config = loader.load_workflow(workflow_name)

    # Get input from request
    input_data = request.json

    # Execute workflow
    registry = EngineRegistry()
    engine = registry.get_engine_from_config(config)
    compiled = engine.compile(config)
    result = engine.execute(compiled, input_data)

    # Return result
    return jsonify({
        "status": "success",
        "output": result.get("output"),
        "metadata": result.get("metadata")
    })

@app.route('/api/workflows', methods=['GET'])
def list_workflows():
    """List available workflows."""
    loader = ConfigLoader()
    workflows = loader.list_workflows()
    return jsonify({"workflows": workflows})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

**Run server:**
```bash
python api/server.py
```

**Call API:**
```bash
curl -X POST http://localhost:5000/api/workflows/simple_research/execute \
  -H "Content-Type: application/json" \
  -d '{"topic": "Python typing"}'
```

### FastAPI Integration

**Create async API:**

```python
# api/server.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from temper_ai.compiler.engine_registry import EngineRegistry
from temper_ai.compiler.config_loader import ConfigLoader

app = FastAPI(title="Agent Framework API")

class WorkflowInput(BaseModel):
    workflow_name: str
    input_data: dict

class WorkflowOutput(BaseModel):
    status: str
    output: dict
    metadata: dict

@app.post("/api/workflows/execute", response_model=WorkflowOutput)
async def execute_workflow(request: WorkflowInput):
    """Execute workflow asynchronously."""
    try:
        # Load workflow
        loader = ConfigLoader()
        config = loader.load_workflow(request.workflow_name)

        # Execute
        registry = EngineRegistry()
        engine = registry.get_engine_from_config(config)
        compiled = engine.compile(config)
        result = engine.execute(compiled, request.input_data)

        return WorkflowOutput(
            status="success",
            output=result.get("output", {}),
            metadata=result.get("metadata", {})
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}
```

**Run with uvicorn:**
```bash
uvicorn api.server:app --reload --port 8000
```

### GraphQL Integration

**Using Strawberry:**

```python
# api/graphql_server.py
import strawberry
from strawberry.fastapi import GraphQLRouter
from fastapi import FastAPI

@strawberry.type
class WorkflowResult:
    output: str
    metadata: dict

@strawberry.type
class Query:
    @strawberry.field
    def list_workflows(self) -> list[str]:
        loader = ConfigLoader()
        return loader.list_workflows()

@strawberry.type
class Mutation:
    @strawberry.mutation
    def execute_workflow(
        self,
        workflow_name: str,
        input_data: dict
    ) -> WorkflowResult:
        # Execute workflow
        loader = ConfigLoader()
        config = loader.load_workflow(workflow_name)

        registry = EngineRegistry()
        engine = registry.get_engine_from_config(config)
        compiled = engine.compile(config)
        result = engine.execute(compiled, input_data)

        return WorkflowResult(
            output=result.get("output"),
            metadata=result.get("metadata", {})
        )

schema = strawberry.Schema(query=Query, mutation=Mutation)
graphql_app = GraphQLRouter(schema)

app = FastAPI()
app.include_router(graphql_app, prefix="/graphql")
```

---

## Database Integration

### PostgreSQL for Observability

**Setup:**

```python
# config/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from temper_ai.storage.database.manager import Base

DATABASE_URL = "postgresql://user:password@localhost:5432/agents"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# Create tables
Base.metadata.create_all(bind=engine)
```

**Configure in workflow:**

```yaml
observability:
  enabled: true
  database_url: postgresql://user:password@localhost:5432/agents
  track_llm_calls: true
  track_tool_calls: true
```

### Redis for Caching

**Setup Redis cache:**

```python
# integration/redis_cache.py
import redis
from temper_ai.cache.llm_cache import LLMCache

# Create Redis-backed cache
cache = LLMCache(
    backend="redis",
    redis_host="localhost",
    redis_port=6379,
    redis_db=0,
    ttl=3600
)

# Use in agent
from temper_ai.agents.llm_providers import OpenAILLM

llm = OpenAILLM(
    model="gpt-4",
    api_key="...",
    enable_cache=True,
    cache_backend=cache
)
```

### MongoDB for Document Storage

**Store execution logs:**

```python
# integration/mongodb_storage.py
from pymongo import MongoClient
from datetime import datetime

class MongoStorage:
    def __init__(self, connection_string):
        self.client = MongoClient(connection_string)
        self.db = self.client.agent_framework

    def store_execution(self, workflow_name, input_data, result):
        """Store workflow execution."""
        self.db.executions.insert_one({
            "workflow_name": workflow_name,
            "input": input_data,
            "output": result,
            "timestamp": datetime.utcnow(),
            "status": "completed"
        })

    def get_recent_executions(self, workflow_name, limit=10):
        """Get recent executions for workflow."""
        return list(
            self.db.executions
            .find({"workflow_name": workflow_name})
            .sort("timestamp", -1)
            .limit(limit)
        )
```

---

## Web Framework Integration

### Django Integration

**Create Django app:**

```python
# myapp/views.py
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from temper_ai.compiler.engine_registry import EngineRegistry
from temper_ai.compiler.config_loader import ConfigLoader
import json

@csrf_exempt
def execute_workflow_view(request, workflow_name):
    """Django view to execute workflow."""
    if request.method == 'POST':
        input_data = json.loads(request.body)

        # Execute workflow
        loader = ConfigLoader()
        config = loader.load_workflow(workflow_name)

        registry = EngineRegistry()
        engine = registry.get_engine_from_config(config)
        compiled = engine.compile(config)
        result = engine.execute(compiled, input_data)

        return JsonResponse({
            "status": "success",
            "output": result.get("output"),
            "metadata": result.get("metadata")
        })

    return JsonResponse({"error": "Only POST allowed"}, status=405)
```

**URLs:**

```python
# myapp/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('api/workflows/<str:workflow_name>/execute',
         views.execute_workflow_view,
         name='execute_workflow'),
]
```

### Express.js Integration

**Create Node.js API:**

```javascript
// server.js
const express = require('express');
const { spawn } = require('child_process');

const app = express();
app.use(express.json());

app.post('/api/workflows/:workflowName/execute', async (req, res) => {
  const { workflowName } = req.params;
  const inputData = req.body;

  // Call Python script
  const python = spawn('python', [
    'execute_workflow.py',
    workflowName,
    JSON.stringify(inputData)
  ]);

  let result = '';
  python.stdout.on('data', (data) => {
    result += data.toString();
  });

  python.on('close', (code) => {
    if (code === 0) {
      res.json(JSON.parse(result));
    } else {
      res.status(500).json({ error: 'Execution failed' });
    }
  });
});

app.listen(3000, () => {
  console.log('Server running on port 3000');
});
```

---

## Message Queue Integration

### Celery Integration

**Setup Celery tasks:**

```python
# tasks.py
from celery import Celery
from temper_ai.compiler.engine_registry import EngineRegistry
from temper_ai.compiler.config_loader import ConfigLoader

app = Celery('agent_tasks', broker='redis://localhost:6379/0')

@app.task
def execute_workflow_async(workflow_name, input_data):
    """Execute workflow asynchronously via Celery."""
    loader = ConfigLoader()
    config = loader.load_workflow(workflow_name)

    registry = EngineRegistry()
    engine = registry.get_engine_from_config(config)
    compiled = engine.compile(config)
    result = engine.execute(compiled, input_data)

    return result

# Trigger from API
from tasks import execute_workflow_async

@app.route('/api/workflows/<workflow_name>/execute-async', methods=['POST'])
def execute_async(workflow_name):
    input_data = request.json
    task = execute_workflow_async.delay(workflow_name, input_data)
    return jsonify({"task_id": task.id})

@app.route('/api/tasks/<task_id>', methods=['GET'])
def get_task_result(task_id):
    task = execute_workflow_async.AsyncResult(task_id)
    if task.ready():
        return jsonify({"status": "completed", "result": task.result})
    return jsonify({"status": "pending"})
```

### RabbitMQ Integration

**Publish/Subscribe pattern:**

```python
# integration/rabbitmq.py
import pika
import json

class WorkflowPublisher:
    def __init__(self, host='localhost'):
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters(host)
        )
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue='workflows')

    def publish_workflow(self, workflow_name, input_data):
        """Publish workflow execution request."""
        message = {
            "workflow": workflow_name,
            "input": input_data
        }
        self.channel.basic_publish(
            exchange='',
            routing_key='workflows',
            body=json.dumps(message)
        )

class WorkflowConsumer:
    def __init__(self, host='localhost'):
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters(host)
        )
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue='workflows')

    def callback(self, ch, method, properties, body):
        """Process workflow from queue."""
        message = json.loads(body)
        workflow_name = message['workflow']
        input_data = message['input']

        # Execute workflow
        loader = ConfigLoader()
        config = loader.load_workflow(workflow_name)
        # ... execute ...

        ch.basic_ack(delivery_tag=method.delivery_tag)

    def start_consuming(self):
        """Start consuming messages."""
        self.channel.basic_consume(
            queue='workflows',
            on_message_callback=self.callback
        )
        self.channel.start_consuming()
```

---

## External Tool Integration

### Create Custom Tool

**Example: Slack Integration**

```python
# tools/slack_tool.py
from temper_ai.tools.base import BaseTool, ToolResult, ToolMetadata
from slack_sdk import WebClient
import os

class SlackTool(BaseTool):
    """Send messages to Slack."""

    def __init__(self):
        self.client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))
        super().__init__()

    @property
    def name(self) -> str:
        return "SlackTool"

    @property
    def description(self) -> str:
        return "Send messages to Slack channels"

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            version="1.0.0",
            requires_network=True,
            requires_credentials=True
        )

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Channel name (e.g., #general)"
                },
                "message": {
                    "type": "string",
                    "description": "Message to send"
                }
            },
            "required": ["channel", "message"]
        }

    def execute(self, channel: str, message: str) -> ToolResult:
        """Send message to Slack channel."""
        try:
            response = self.client.chat_postMessage(
                channel=channel,
                text=message
            )

            return ToolResult(
                success=True,
                result=f"Message sent to {channel}"
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Failed to send message: {str(e)}"
            )
```

**Register tool:**

```yaml
# configs/agents/slack_agent.yaml
agent:
  name: slack_agent
  tools:
    - SlackTool
```

### GitHub API Integration

**Example: Create issues**

```python
# tools/github_tool.py
from temper_ai.tools.base import BaseTool, ToolResult, ToolMetadata
from github import Github
import os

class GitHubTool(BaseTool):
    """Interact with GitHub API."""

    def __init__(self):
        self.client = Github(os.getenv("GITHUB_TOKEN"))
        super().__init__()

    @property
    def name(self) -> str:
        return "GitHubTool"

    @property
    def description(self) -> str:
        return "Create issues, PRs, and interact with GitHub"

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create_issue", "list_issues"]
                },
                "repo": {
                    "type": "string",
                    "description": "Repository (owner/repo)"
                },
                "title": {"type": "string"},
                "body": {"type": "string"}
            },
            "required": ["action", "repo"]
        }

    def execute(self, action: str, repo: str, **kwargs) -> ToolResult:
        """Execute GitHub action."""
        try:
            repository = self.client.get_repo(repo)

            if action == "create_issue":
                issue = repository.create_issue(
                    title=kwargs.get("title"),
                    body=kwargs.get("body")
                )
                return ToolResult(
                    success=True,
                    result=f"Created issue #{issue.number}"
                )

            elif action == "list_issues":
                issues = repository.get_issues(state="open")
                issue_list = [f"#{i.number}: {i.title}" for i in issues[:10]]
                return ToolResult(
                    success=True,
                    result="\n".join(issue_list)
                )

        except Exception as e:
            return ToolResult(success=False, error=str(e))
```

---

## LLM Provider Integration

### Add Custom LLM Provider

**Example: Hugging Face Integration**

```python
# agents/huggingface_provider.py
from temper_ai.agents.llm_providers import BaseLLM, LLMResponse, LLMProvider
from transformers import pipeline

class HuggingFaceLLM(BaseLLM):
    """Hugging Face LLM provider."""

    def __init__(self, model: str, **kwargs):
        super().__init__(model=model, **kwargs)
        self.pipeline = pipeline("text-generation", model=model)

    def complete(self, prompt: str) -> LLMResponse:
        """Generate completion."""
        try:
            result = self.pipeline(
                prompt,
                max_length=self.max_tokens,
                temperature=self.temperature,
                num_return_sequences=1
            )

            content = result[0]['generated_text']

            return LLMResponse(
                content=content,
                model=self.model,
                provider="huggingface",
                total_tokens=len(content.split())
            )

        except Exception as e:
            raise LLMError(f"HuggingFace error: {str(e)}")
```

**Register provider:**

```python
# Update LLMProvider enum
class LLMProvider(str, Enum):
    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    VLLM = "vllm"
    HUGGINGFACE = "huggingface"  # Add this
```

---

## Authentication & Security

### API Key Authentication

**Flask example:**

```python
from flask import Flask, request, jsonify
from functools import wraps

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key or api_key != os.getenv('API_KEY'):
            return jsonify({"error": "Invalid API key"}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/api/workflows/<workflow_name>/execute', methods=['POST'])
@require_api_key
def execute_workflow(workflow_name):
    # Protected endpoint
    pass
```

### JWT Authentication

**FastAPI example:**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

security = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify JWT token."""
    try:
        payload = jwt.decode(
            credentials.credentials,
            os.getenv("JWT_SECRET"),
            algorithms=["HS256"]
        )
        return payload
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

@app.post("/api/workflows/execute")
async def execute_workflow(
    request: WorkflowInput,
    user: dict = Depends(verify_token)
):
    # Protected endpoint
    # user contains JWT payload
    pass
```

---

## Monitoring Integration

### Prometheus Metrics

**Export metrics:**

```python
# monitoring/prometheus.py
from prometheus_client import Counter, Histogram, generate_latest
from flask import Response

# Define metrics
workflow_executions = Counter(
    'workflow_executions_total',
    'Total workflow executions',
    ['workflow_name', 'status']
)

workflow_duration = Histogram(
    'workflow_duration_seconds',
    'Workflow execution duration',
    ['workflow_name']
)

@app.route('/metrics')
def metrics():
    """Prometheus metrics endpoint."""
    return Response(generate_latest(), mimetype='text/plain')

# Record metrics
workflow_executions.labels(
    workflow_name="simple_research",
    status="success"
).inc()

with workflow_duration.labels(workflow_name="simple_research").time():
    # Execute workflow
    pass
```

### Datadog Integration

**Send metrics to Datadog:**

```python
# monitoring/datadog.py
from datadog import initialize, statsd

initialize(api_key=os.getenv('DATADOG_API_KEY'))

def track_workflow_execution(workflow_name, duration, status):
    """Track workflow execution metrics."""
    statsd.increment(
        'workflow.executions',
        tags=[f'workflow:{workflow_name}', f'status:{status}']
    )
    statsd.histogram(
        'workflow.duration',
        duration,
        tags=[f'workflow:{workflow_name}']
    )
```

---

## Examples

### Complete API Server

**Full FastAPI server with authentication:**

```python
# server.py
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from temper_ai.compiler.engine_registry import EngineRegistry
from temper_ai.compiler.config_loader import ConfigLoader
import jwt
import os

app = FastAPI(title="Agent Framework API")
security = HTTPBearer()

class WorkflowInput(BaseModel):
    workflow_name: str
    input_data: dict

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        jwt.decode(credentials.credentials, os.getenv("JWT_SECRET"), algorithms=["HS256"])
        return True
    except:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.post("/api/workflows/execute")
async def execute_workflow(
    request: WorkflowInput,
    authenticated: bool = Depends(verify_token)
):
    loader = ConfigLoader()
    config = loader.load_workflow(request.workflow_name)

    registry = EngineRegistry()
    engine = registry.get_engine_from_config(config)
    compiled = engine.compile(config)
    result = engine.execute(compiled, request.input_data)

    return {"status": "success", "output": result}

@app.get("/health")
async def health():
    return {"status": "healthy"}
```

---

## Summary

- **API Integration:** Flask, FastAPI, GraphQL
- **Database:** PostgreSQL, Redis, MongoDB
- **Web Frameworks:** Django, Express.js
- **Message Queues:** Celery, RabbitMQ
- **Custom Tools:** Slack, GitHub, custom APIs
- **LLM Providers:** Custom provider integration
- **Auth:** API keys, JWT
- **Monitoring:** Prometheus, Datadog

For more details, see specific integration examples in `/examples/integrations/`.

Happy integrating! 🔌
