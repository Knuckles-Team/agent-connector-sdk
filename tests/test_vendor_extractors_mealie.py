"""SDK-SOURCE-INGEST-R006.13: the Mealie vendor extractor port."""

from __future__ import annotations
import pytest

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors import (
    get_vendor_extractor,
    list_vendor_extractors,
)
from agent_connector_sdk.vendor_extractors.mealie import CATEGORY, extract


class _FakeClient:
    def __init__(
        self, recipes: object, meal_plans: object, shopping_lists: object
    ) -> None:
        self._recipes = recipes
        self._meal_plans = meal_plans
        self._shopping_lists = shopping_lists

    def get_recipes(self) -> object:
        return self._recipes

    def get_households_mealplans(self) -> object:
        return self._meal_plans

    def get_households_shopping_lists(self) -> object:
        return self._shopping_lists


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.13")
def test_extract_returns_recipe_mealplan_and_shoppinglist_entities() -> None:
    config = {
        "client": _FakeClient(
            recipes={"items": [{"id": "r1", "name": "Chili", "slug": "chili"}]},
            meal_plans=[{"id": 5, "date": "2026-01-01", "recipeId": "r1"}],
            shopping_lists=[{"id": 9, "name": "Weekly"}],
        )
    }

    result = extract(config)

    assert isinstance(result, ChangeSet)
    assert len(result.entities) == 3
    recipe, meal_plan, shopping_list = result.entities
    assert isinstance(recipe, Entity)
    assert recipe.id == "mealie:recipe:r1"
    assert recipe.node_type == "Recipe"
    assert meal_plan.id == "mealie:mealplan:5"
    assert meal_plan.node_type == "MealPlan"
    assert shopping_list.id == "mealie:shoplist:9"
    assert shopping_list.node_type == "ShoppingList"
    assert len(result.relationships) == 1
    relationship = result.relationships[0]
    assert isinstance(relationship, Relationship)
    assert relationship.source == "mealie:mealplan:5"
    assert relationship.target == "mealie:recipe:r1"
    assert relationship.relationship == "INCLUDES"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.13")
def test_extract_accepts_bare_list_and_results_shaped_responses() -> None:
    config = {
        "client": _FakeClient(
            recipes=[{"id": "r2", "name": "Soup"}],
            meal_plans={"results": []},
            shopping_lists=[],
        )
    }

    result = extract(config)

    assert [entity.id for entity in result.entities] == ["mealie:recipe:r2"]


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.13")
def test_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert extract({}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.13")
def test_extract_returns_an_empty_change_set_when_get_recipes_raises() -> None:
    class _BrokenClient:
        def get_recipes(self) -> object:
            raise RuntimeError("down")

        def get_households_mealplans(self) -> object:
            return []

        def get_households_shopping_lists(self) -> object:
            return []

    assert extract({"client": _BrokenClient()}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.13")
def test_mealie_self_registers_under_the_vendor_extractor_registry() -> None:
    registered = get_vendor_extractor(CATEGORY)

    assert registered is not None
    assert registered.extract is extract
    assert CATEGORY in [vendor.category for vendor in list_vendor_extractors()]
