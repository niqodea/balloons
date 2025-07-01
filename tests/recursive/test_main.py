from __future__ import annotations

from pathlib import Path

from balloons import (
    Balloon,
    EmptyClosedBalloonWorld,
    StructuredBalloonWorld,
)
from tests.recursive.objects import (
    APPLE,
    BANANA,
    CARROT,
    DATE,
    FRUIT_AND_VEGETABLE_SALAD,
    FRUIT_SALAD,
    VEGETABLE_SALAD,
)
from tests.recursive.schema import CompositeFood, Food, SimpleFood

DATABASE_PATH = Path(__file__).parent / "database"

EMPTY_WORLD = EmptyClosedBalloonWorld()

# TODO: Automate the construction of the schema again
SCHEMA = StructuredBalloonWorld.Schema(
    namespace_types={Balloon},
    types_={Food, SimpleFood, CompositeFood},
    nameable_types={Food, SimpleFood, CompositeFood},
)


def test_inflation(tmp_path: Path) -> None:
    world = EMPTY_WORLD.populate(SCHEMA, DATABASE_PATH)
    food_balloonist = world.get_balloonist(Food)

    # Simple
    apple = food_balloonist.get(APPLE.as_named().name)
    banana = food_balloonist.get(BANANA.as_named().name)
    carrot = food_balloonist.get(CARROT.as_named().name)
    date = food_balloonist.get(DATE.as_named().name)
    assert apple == APPLE
    assert banana == BANANA
    assert carrot == CARROT
    assert date == DATE
    # Composite
    fruit_salad = food_balloonist.get(FRUIT_SALAD.as_named().name)
    vegetable_salad = food_balloonist.get(VEGETABLE_SALAD.as_named().name)
    fruit_and_vegetable_salad = food_balloonist.get(
        FRUIT_AND_VEGETABLE_SALAD.as_named().name
    )
    assert fruit_salad == FRUIT_SALAD
    assert vegetable_salad == VEGETABLE_SALAD
    assert fruit_and_vegetable_salad == FRUIT_AND_VEGETABLE_SALAD


def test_consistency(tmp_path: Path) -> None:
    world = EMPTY_WORLD.populate(SCHEMA, tmp_path).to_open()

    # Simple
    world.track(APPLE)
    world.track(BANANA)
    world.track(CARROT)
    world.track(DATE)
    # Composite
    world.track(FRUIT_SALAD)
    world.track(VEGETABLE_SALAD)
    world.track(FRUIT_AND_VEGETABLE_SALAD)

    # Simulate a new Python session by creating the objects again

    other_world = EMPTY_WORLD.populate(SCHEMA, DATABASE_PATH)
    food_balloonist = other_world.get_balloonist(Food)

    # Simple
    apple = food_balloonist.get(APPLE.as_named().name)
    banana = food_balloonist.get(BANANA.as_named().name)
    carrot = food_balloonist.get(CARROT.as_named().name)
    date = food_balloonist.get(DATE.as_named().name)
    assert apple == APPLE
    assert banana == BANANA
    assert carrot == CARROT
    assert date == DATE
    # Composite
    fruit_salad = food_balloonist.get(FRUIT_SALAD.as_named().name)
    vegetable_salad = food_balloonist.get(VEGETABLE_SALAD.as_named().name)
    fruit_and_vegetable_salad = food_balloonist.get(
        FRUIT_AND_VEGETABLE_SALAD.as_named().name
    )
    assert fruit_salad == FRUIT_SALAD
    assert vegetable_salad == VEGETABLE_SALAD
    assert fruit_and_vegetable_salad == FRUIT_AND_VEGETABLE_SALAD
