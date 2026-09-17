"""POST /api/runs accepts the field name the API itself returns.

Every run in a list response carries ``workflow_name``; posting that back
used to fail with a 422 naming a field the caller had never seen.
"""

import pytest
from pydantic import ValidationError

from temper_ai.api.routes import RunRequest


def test_accepts_workflow():
    assert RunRequest(workflow="demo").workflow == "demo"


def test_accepts_workflow_name_the_api_returns():
    assert RunRequest.model_validate({"workflow_name": "demo"}).workflow == "demo"


def test_still_requires_one_of_them():
    with pytest.raises(ValidationError):
        RunRequest.model_validate({"inputs": {}})
