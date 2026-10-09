"""Mealie vendor extractor (SDK-SOURCE-INGEST-R006.13).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.mealie``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
recipes/meal-plans/shopping-lists become ``Recipe``/``MealPlan``/
``ShoppingList`` entities instead of agent-utilities' ``GraphNode``, with an
``INCLUDES`` relationship from a meal plan entry to its recipe. The client is
injected through ``config`` and this module performs no I/O of its own; it is
tolerant of Mealie's ``{"items": [...]}`` pagination shape (and bare lists /
``results``).
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "mealie"


def _get(config: Any, key: str) -> Any:
    return config.get(key) if isinstance(config, dict) else getattr(config, key, None)


def _rows(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, dict):
        result = result.get("items", result.get("results", result.get("data", [])))
    return (
        [row for row in result if isinstance(row, dict)]
        if isinstance(result, list)
        else []
    )


def _call(client: Any, name: str) -> Any:
    method = getattr(client, name, None)
    try:
        return method() if callable(method) else None
    except Exception:
        return None


def _recipe_entities(client: Any) -> list[Entity]:
    entities: list[Entity] = []
    for recipe in _rows(_call(client, "get_recipes")):
        recipe_id = recipe.get("id") or recipe.get("slug")
        if not recipe_id:
            continue
        entities.append(
            Entity(
                id=f"mealie:recipe:{recipe_id}",
                node_type="Recipe",
                properties={
                    key: value
                    for key, value in {
                        "name": recipe.get("name"),
                        "slug": recipe.get("slug"),
                        "description": recipe.get("description"),
                        "externalToolId": str(recipe_id),
                        "domain": CATEGORY,
                    }.items()
                    if value is not None
                },
            )
        )
    return entities


def _mealplan_entity(meal_plan: dict[str, Any], meal_plan_id: Any) -> Entity:
    return Entity(
        id=f"mealie:mealplan:{meal_plan_id}",
        node_type="MealPlan",
        properties={
            key: value
            for key, value in {
                "date": meal_plan.get("date"),
                "entry_type": meal_plan.get("entryType"),
                "title": meal_plan.get("title"),
                "externalToolId": str(meal_plan_id),
                "domain": CATEGORY,
            }.items()
            if value is not None
        },
    )


def _mealplan_relationship(
    meal_plan: dict[str, Any], node_id: str
) -> Relationship | None:
    recipe_ref = meal_plan.get("recipeId") or (meal_plan.get("recipe") or {}).get("id")
    if not recipe_ref:
        return None
    return Relationship(
        source=node_id,
        target=f"mealie:recipe:{recipe_ref}",
        relationship="INCLUDES",
    )


def _mealplan_entities_and_relationships(
    client: Any,
) -> tuple[list[Entity], list[Relationship]]:
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for meal_plan in _rows(_call(client, "get_households_mealplans")):
        meal_plan_id = meal_plan.get("id")
        if meal_plan_id is None:
            continue
        node_id = f"mealie:mealplan:{meal_plan_id}"
        entities.append(_mealplan_entity(meal_plan, meal_plan_id))
        relationship = _mealplan_relationship(meal_plan, node_id)
        if relationship is not None:
            relationships.append(relationship)
    return entities, relationships


def _shopping_list_entities(client: Any) -> list[Entity]:
    entities: list[Entity] = []
    for shopping_list in _rows(_call(client, "get_households_shopping_lists")):
        list_id = shopping_list.get("id")
        if list_id is None:
            continue
        entities.append(
            Entity(
                id=f"mealie:shoplist:{list_id}",
                node_type="ShoppingList",
                properties={
                    key: value
                    for key, value in {
                        "name": shopping_list.get("name"),
                        "externalToolId": str(list_id),
                        "domain": CATEGORY,
                    }.items()
                    if value is not None
                },
            )
        )
    return entities


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []

    entities.extend(_recipe_entities(client))

    mealplan_entities, mealplan_relationships = _mealplan_entities_and_relationships(
        client
    )
    entities.extend(mealplan_entities)
    relationships.extend(mealplan_relationships)

    entities.extend(_shopping_list_entities(client))

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Mealie (recipes/meal-plans/shopping) -> KG entities",
)
