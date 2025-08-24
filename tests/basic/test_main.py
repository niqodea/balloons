from __future__ import annotations

from pathlib import Path

from balloons import (
    Balloon,
    DefaultBalloonWorld,
    NullBalloonWorld,
)
from tests.basic.objects import (
    ABIGAIL,
    ALEX,
    ALICE,
    BELLA,
    BENJAMIN,
    BOB,
    CAROL,
    CHARLOTTE,
    CODY,
)
from tests.basic.schema import Animal, Cat, Dog, Owner

DATABASE_PATH = Path(__file__).parent / "database"

NULL_WORLD = NullBalloonWorld()

# TODO: Automate the construction of the schema again
SCHEMA = DefaultBalloonWorld.Schema(
    namespace_types={Balloon},
    types_={Animal, Animal.Size, Cat, Dog, Owner},
    nameable_types={Animal, Cat, Dog, Owner},
)


def test_inflation(tmp_path: Path) -> None:
    world = NULL_WORLD.populate(SCHEMA, DATABASE_PATH)
    animal_balloonist = world.get_balloonist(Animal)
    owner_balloonist = world.get_balloonist(Owner)

    # Cats
    abigail = animal_balloonist.get(ABIGAIL.as_named().name)
    benjamin = animal_balloonist.get(BENJAMIN.as_named().name)
    charlotte = animal_balloonist.get(CHARLOTTE.as_named().name)
    assert abigail == ABIGAIL
    assert benjamin == BENJAMIN
    assert charlotte == CHARLOTTE
    # Dogs
    alex = animal_balloonist.get(ALEX.as_named().name)
    bella = animal_balloonist.get(BELLA.as_named().name)
    cody = animal_balloonist.get(CODY.as_named().name)
    assert alex == ALEX
    assert bella == BELLA
    assert cody == CODY
    # Owners
    alice = owner_balloonist.get(ALICE.as_named().name)
    bob = owner_balloonist.get(BOB.as_named().name)
    carol = owner_balloonist.get(CAROL.as_named().name)
    assert alice == ALICE
    assert bob == BOB
    assert carol == CAROL


def test_consistency(tmp_path: Path) -> None:
    world = NULL_WORLD.populate(SCHEMA, tmp_path).to_open()

    # Cats
    world.track(ABIGAIL)
    world.track(BENJAMIN)
    world.track(CHARLOTTE)
    # Dogs
    world.track(ALEX)
    world.track(BELLA)
    world.track(CODY)
    # Owners
    world.track(ALICE)
    world.track(BOB)
    world.track(CAROL)

    # Simulate a new Python session by creating the objects again

    other_world = NULL_WORLD.populate(SCHEMA, tmp_path)
    animal_balloonist = other_world.get_balloonist(Animal)
    owner_balloonist = other_world.get_balloonist(Owner)

    # Cats
    abigail = animal_balloonist.get(ABIGAIL.as_named().name)
    benjamin = animal_balloonist.get(BENJAMIN.as_named().name)
    charlotte = animal_balloonist.get(CHARLOTTE.as_named().name)
    assert abigail == ABIGAIL
    assert benjamin == BENJAMIN
    assert charlotte == CHARLOTTE
    # Dogs
    alex = animal_balloonist.get(ALEX.as_named().name)
    bella = animal_balloonist.get(BELLA.as_named().name)
    cody = animal_balloonist.get(CODY.as_named().name)
    assert alex == ALEX
    assert bella == BELLA
    assert cody == CODY
    # Owners
    alice = owner_balloonist.get(ALICE.as_named().name)
    bob = owner_balloonist.get(BOB.as_named().name)
    carol = owner_balloonist.get(CAROL.as_named().name)
    assert alice == ALICE
    assert bob == BOB
    assert carol == CAROL
