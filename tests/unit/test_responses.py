"""without_empty: empty properties are left out of the API's answers."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from api.responses import prune, without_empty

pytestmark = pytest.mark.unit


def test_empty_properties_go_at_any_depth_but_zero_and_false_stay():
    value = {
        "name": "",
        "none": None,
        "count": 0,
        "flag": False,
        "tags": [],
        "meta": {"a": None, "b": {}},
        "items": [{"id": "1", "caption": None}, {}],
    }

    assert prune(value) == {"count": 0, "flag": False, "items": [{"id": "1"}, {}]}


class _Item(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    item_id: str = Field(alias="itemId")
    caption: str | None = None


class _Result(BaseModel):
    items: list[_Item] = []
    error_code: str | None = Field(default=None, alias="errorCode")


def test_a_model_is_answered_by_alias_without_its_empty_properties():
    app = FastAPI()

    @app.get("/x", response_model=_Result)
    @without_empty
    async def endpoint(n: int = 1) -> _Result:
        return _Result(items=[_Item(item_id=str(i)) for i in range(n)])

    with TestClient(app) as client:
        assert client.get("/x", params={"n": 2}).json() == {
            "items": [{"itemId": "0"}, {"itemId": "1"}]
        }
        assert client.get("/x", params={"n": 0}).json() == {}
        # The route keeps its parameters and documented response.
        assert client.get("/x", params={"n": "two"}).status_code == 422
        assert "_Result" in str(client.get("/openapi.json").json())
