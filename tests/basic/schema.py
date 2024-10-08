from __future__ import annotations

from dataclasses import dataclass

from balloons import Balloon, balloon


@balloon
class Animal(Balloon):
    size: Size

    @dataclass(frozen=True)
    class Size(Balloon):
        height: int
        weight: int


@balloon
class Cat(Animal):
    purr_type: str | None


@balloon
class Dog(Animal):
    obedience: float


@balloon
class Owner(Balloon):
    pet_nicknames: dict[Animal, str]
