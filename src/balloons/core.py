from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, make_dataclass
from enum import Enum
from pathlib import Path
from types import NoneType, UnionType
from typing import (
    ClassVar,
    Generic,
    Mapping,
    NoReturn,
    Protocol,
    Self,
    TypeAlias,
    TypeVar,
    get_args,
    get_origin,
    get_type_hints,
)

from typing_extensions import dataclass_transform


@dataclass(frozen=True)
class Balloon:
    """
    The top class for balloons.
    """

    def to_named(self, name: str) -> Self:
        """
        Promote the balloon to a named balloon.

        :param name: The name of the balloon.
        :return: The named balloon.
        """
        if isinstance(self, NamedBalloon):
            raise ValueError(f"Balloon is already named: {self}")
        named_type = type(self).Named
        return named_type(name=name, **self.__dict__)  # type: ignore[return-value]

    def as_named(self) -> NamedBalloon:
        """
        Treat the balloon as a named balloon.
        """
        assert isinstance(self, NamedBalloon)
        return self

    Named: ClassVar[type[NamedBalloon]]
    """
    The named type of the balloon class.
    """


# Ref: https://stackoverflow.com/questions/53990296
@dataclass(frozen=True, eq=False)
class NamedBalloon(Balloon):
    """
    The marker class for named balloons.
    """

    name: str
    """
    The name of the balloon.
    """

    def __hash__(self) -> int:
        return hash(f"{type(self).Base.__qualname__}:{self.name}")

    Base: ClassVar[type[Balloon]]
    """
    The base type of the named balloon class.
    """


@dataclass_transform(frozen_default=True)
def balloon(cls: type[Balloon]) -> type[Balloon]:
    """
    Decorator required to correctly setup balloon classes.
    """

    # TODO: Evaluate whehter having kw_only=True is a good idea here
    # It enables default values, but also disables positional arguments
    cls = dataclass(frozen=True)(cls)

    if issubclass(cls, NamedBalloon):
        # It makes sense to define some classes as only having named instances
        # It also enables safe usage of instances as dictionary keys
        named_cls = cls
    else:
        named_cls = make_dataclass(
            cls_name=f"{cls.__name__}.Named",
            fields=[],
            bases=(NamedBalloon, cls),
            frozen=True,
            eq=False,
        )

    cls.Named = named_cls
    named_cls.Base = cls

    return cls


Atomic = int | float | str | bool
"""
The type alias for atomic types.
"""

B = TypeVar("B", bound=Balloon)
BN = TypeVar("BN", bound=NamedBalloon)
E = TypeVar("E", bound=Enum)
A = TypeVar("A", bound=Atomic)

VI = TypeVar("VI", bound="InflatedValue")
InflatedValue: TypeAlias = (
    None
    | dict[BN, VI]
    | dict[E, VI]
    | dict[str, VI]
    | set[BN]
    | set[E]
    | set[str]
    | tuple[VI, ...]
    | B
    | E
    | A
)
"""
Value that can be deflated.
"""

VD = TypeVar("VD", bound="DeflatedValue")
DeflatedValue: TypeAlias = dict[str, VD] | list[VD] | A | None
"""
Value that can be inflated or dumped to JSON.
"""


class Inflator:
    """
    Inflates values from their JSON representations.
    """

    def __init__(
        self,
        types_: dict[str, type[Balloon]],
        providers: Mapping[type[Balloon], SpecializedBalloonProvider[NamedBalloon]],
    ) -> None:
        """
        :param types: The balloon types, indexed by their name.
        :param providers: The providers of named balloons.
        """
        self._types = types_
        self._providers = providers

    def inflate(self, deflated_value: DeflatedValue, static_type: type[VI]) -> VI:
        """
        Inflate a deflated value.

        :param value: The deflated value.
        :param static_type: The static type of the value.
        :return: The inflated value.
        """
        type_origin = get_origin(static_type)
        type_args = get_args(static_type)

        if type_origin is dict:
            assert isinstance(deflated_value, dict)
            key_type, value_type = type_args
            return {
                self.inflate(key, key_type): self.inflate(value, value_type)
                for key, value in deflated_value.items()
            }  # type: ignore[return-value]

        if type_origin is tuple:
            assert isinstance(deflated_value, list)
            (item_type,) = type_args
            return tuple(self.inflate(item, item_type) for item in deflated_value)  # type: ignore[return-value]

        if type_origin is set:
            assert isinstance(deflated_value, list)
            (item_type,) = type_args
            return {self.inflate(item, item_type) for item in deflated_value}  # type: ignore[return-value]

        if type_origin is UnionType:
            # NOTE: Arbitrary union types not implemented for now
            # They would either require a try/except logic or inspecting the deflated
            # value to determine the type
            optional_type, none_type = type_args
            assert none_type is NoneType

            if deflated_value is None:
                return None  # type: ignore[return-value]

            return self.inflate(deflated_value, optional_type)

        if issubclass(static_type, Balloon):
            if isinstance(deflated_value, str):
                # it is a named balloon
                type_name, _, name = deflated_value.partition(":")
                type_ = self._types[type_name]
                assert issubclass(type_, static_type)
                provider = self._providers[type_]
                return provider.get(name)  # type: ignore[return-value]
            if isinstance(deflated_value, dict):
                type_name = deflated_value["type"]
                type_ = self._types[type_name]
                assert issubclass(type_, static_type)
                deflated_fields = deflated_value["fields"]
                field_types = get_type_hints(type_)
                inflated_fields = {
                    field_name: self.inflate(
                        deflated_field,
                        field_types[field_name],
                    )
                    for field_name, deflated_field in deflated_fields.items()
                }
                return type_(**inflated_fields)  # type: ignore[return-value]
            raise ValueError(f"Unsupported balloon value: {deflated_value}")

        if issubclass(static_type, Enum):
            assert isinstance(deflated_value, str)
            return static_type[deflated_value]  # type: ignore[return-value]

        if issubclass(static_type, Atomic):  # type: ignore[arg-type,misc]
            assert isinstance(deflated_value, static_type)
            return deflated_value  # type: ignore[return-value]

        raise ValueError(f"Unsupported type: {static_type}")


class Deflator:
    """
    Deflates values to their JSON representations.
    """

    def __init__(
        self,
        providers: Mapping[type[Balloon], SpecializedBalloonProvider[NamedBalloon]],
    ) -> None:
        """
        :param providers: Providers of named balloons.
        """
        self._providers = providers

    def deflate(self, inflated_value: InflatedValue) -> DeflatedValue:
        """
        Deflate a value.

        :param value: The value to deflate.
        :return: The deflated representation of the value.
        """
        if isinstance(inflated_value, NamedBalloon):
            type_ = type(inflated_value).Base
            provider = self._providers[type_]

            if inflated_value.name not in provider.get_names():
                raise ValueError(
                    f"Could not find balloon with name: {inflated_value.name}"
                )

            tracked_balloon = provider.get(inflated_value.name)
            if inflated_value is not tracked_balloon:
                raise ValueError(
                    f"Found two balloons with same name and type\n"
                    f"Type: {type_}\n"
                    f"Name: {inflated_value.name}"
                )

            return f"{type_.__qualname__}:{inflated_value.name}"

        if isinstance(inflated_value, Balloon):
            type_ = type(inflated_value)
            deflated_fields = {
                field_name: self.deflate(inflated_field)
                for field_name, inflated_field in inflated_value.__dict__.items()
            }
            return {
                "type": type_.__qualname__,
                "fields": deflated_fields,
            }

        if isinstance(inflated_value, dict):
            return {
                self.deflate(key): self.deflate(value)
                for key, value in inflated_value.items()
            }

        if isinstance(inflated_value, (set, tuple)):
            return [self.deflate(item) for item in inflated_value]

        if isinstance(inflated_value, Enum):
            return inflated_value.name

        if isinstance(inflated_value, Atomic):  # type: ignore[arg-type,misc]
            return inflated_value

        if inflated_value is None:
            return None

        raise ValueError(f"Unsupported type: {type(inflated_value)}")


# NOTE: Ignoring mypy misc below as it otherwise complains that BLN must be covariant


class BalloonDatabaseCache(Generic[BN]):
    """
    Caches database information about balloons of a certain type.
    """

    def __init__(self, type_: type[BN], names: set[str]) -> None:
        """
        :param type_: The type of the managed balloons.
        :param names: The names of the balloons in the database.
        """
        self._type = type_
        self._names = names  # this is in fact another type of cache

        self._balloons: dict[str, BN] = {}

    def get_cached_names(self) -> set[str]:
        """
        Get the names of the cached balloons.
        """
        return set(self._balloons.keys())

    def get_all_names(self) -> set[str]:
        """
        Get the names of all balloons in the database.
        """
        return self._names

    def get(self, name: str) -> BN:
        """
        Get a balloon by name.

        :param name: The name of the balloon.
        """
        if name not in self._names:
            raise ValueError(f"Could not find balloon with name: {name}")

        return self._balloons[name]

    def track(self, balloon: BN) -> None:
        """
        Track a balloon in the stand.

        :param balloon: The balloon to put.
        """
        if type(balloon) is not self._type:
            raise ValueError(f"Could not handle type: {type(balloon)}")

        if balloon.name in self._balloons:
            raise ValueError(f"Balloon already in cache: {balloon.name}")

        if balloon.name not in self._names:
            self._names.add(balloon.name)

        self._balloons[balloon.name] = balloon


class SpecializedBalloonProvider(Protocol[BN]):  # type: ignore[misc]
    """
    Provides named balloons of a certain type, not including subtypes.
    """

    def get(self, name: str) -> BN:
        """
        Provide a named balloon.

        :param name: The name of the balloon.
        :return: The balloon.
        """

    def get_names(self) -> set[str]:
        """
        Provide the names of the balloons.

        :return: The names of the balloons.
        """

    def get_type(self) -> type[BN]:
        """
        Provide the type of the balloons.

        :return: The type of the balloons.
        """


class EmptySpecializedBalloonProvider(SpecializedBalloonProvider[BN]):
    """
    The specialized balloon provider with no balloons.
    """

    def get(self, name: str) -> NoReturn:
        raise ValueError(f"Could not find balloon with name: {name}")

    def get_names(self) -> set[str]:
        return set()

    def get_type(self) -> type[NoReturn]:
        return NoReturn  # type: ignore[return-value]


class StandardSpecializedBalloonProvider(SpecializedBalloonProvider[BN]):
    """
    The standard specialized balloon provider.
    """

    def __init__(
        self,
        type_: type[BN],
        jsons_path: Path,
        cache: BalloonDatabaseCache[BN],
        baseline_provider: SpecializedBalloonProvider[BN],
        inflator: Inflator,
    ) -> None:
        """
        :param type_: Type of the managed balloons.
        :param jsons_path: Directory with the JSONs of the balloons.
        :param cache: Cache of the balloons.
        :param baseline_provider: Provider of balloons to fall back to.
        :param inflator: Inflator of deflated values.
        """
        self._type = type_
        self._jsons_path = jsons_path
        self._cache = cache
        self._baseline_provider = baseline_provider
        self._inflator = inflator

    def get(self, name: str) -> BN:
        if name in self._baseline_provider.get_names():
            return self._baseline_provider.get(name)

        if name in self._cache.get_cached_names():
            return self._cache.get(name)

        if name not in self._cache.get_all_names():
            raise ValueError(f"Could not find balloon with name: {name}")

        json_path = self._jsons_path / f"{name}.json"
        json_ = json.loads(json_path.read_text())

        field_types = get_type_hints(self._type)
        init_kwargs = {"name": name} | {
            field_name: self._inflator.inflate(
                deflated_value=deflated_field,
                static_type=field_types[field_name],
            )
            for field_name, deflated_field in json_.items()
        }

        balloon = self._type(**init_kwargs)
        self._cache.track(balloon)
        return balloon

    def get_names(self) -> set[str]:
        return self._cache.get_all_names() | set(self._baseline_provider.get_names())

    def get_type(self) -> type[BN]:
        return self._type


class SpecializedBalloonTracker(Generic[BN]):
    """
    Tracks named balloons of a certain type, not including subtypes.
    """

    def __init__(
        self,
        type_: type[BN],
        jsons_path: Path,
        trackers: dict[type[Balloon], SpecializedBalloonTracker[NamedBalloon]],
        cache: BalloonDatabaseCache[BN],
        baseline_provider: SpecializedBalloonProvider[BN],
        inflator: Inflator,
        deflator: Deflator,
    ) -> None:
        """
        :param type_: Type of the managed balloons.
        :param jsons_path: Directory with the JSONs of the balloons.
        :param trackers: Trackers of the balloons.
        :param cache: Cache of the balloons.
        :param baseline_provider: Provider of balloons to fall back to.
        :param inflator: Inflator of deflated values.
        :param deflator: Deflator of inflated values.
        """
        self._type = type_
        self._jsons_path = jsons_path
        self._trackers = trackers
        self._cache = cache
        self._baseline_provider = baseline_provider
        self._inflator = inflator
        self._deflator = deflator

    def track(self, balloon: BN) -> None:
        """
        Track a named balloon.

        :param balloon: The balloon to track.
        """
        if type(balloon) is not self._type:
            raise ValueError(f"Could not handle type: {type(balloon)}")

        # NOTE: We check with `is`, but we could also check with `==` to be less strict
        if balloon.name in self._baseline_provider.get_names():
            baseline_balloon = self._baseline_provider.get(balloon.name)
            if balloon is baseline_balloon:
                return
            raise ValueError(
                "Found two balloons in memory with same type and name\n"
                f"Type: {self._type}\n"
                f"Name: {balloon.name}"
            )

        if balloon.name in self._cache.get_cached_names():
            cached_balloon = self._cache.get(balloon.name)
            if balloon is cached_balloon:
                return
            raise ValueError(
                "Found two balloons in memory with same type and name\n"
                f"Type: {self._type}\n"
                f"Name: {balloon.name}"
            )

        json_path = self._jsons_path / f"{balloon.name}.json"

        if balloon.name in self._cache.get_all_names():
            json_ = json.loads(json_path.read_text())
            field_types = get_type_hints(self._type)
            init_kwargs = {"name": balloon.name} | {
                field_name: self._inflator.inflate(
                    deflated_value=deflated_field,
                    static_type=field_types[field_name],
                )
                for field_name, deflated_field in json_.items()
            }
            stored_balloon = self._type(**init_kwargs)

            if balloon == stored_balloon:
                self._cache.track(balloon)
                return

            raise ValueError(
                f"Found conflict between in-memory and stored balloons.\n"
                f"In-memory balloon: {balloon}\n"
                f"Stored balloon:    {stored_balloon}"
            )

        fields = {n: v for n, v in balloon.__dict__.items()}
        fields.pop("name")
        for field in fields:
            self._track_field(field)

        json_ = {
            field_name: self._deflator.deflate(field)
            for field_name, field in fields.items()
        }
        json_path.write_text(json.dumps(json_, indent=2))

        self._cache.track(balloon)

    def _track_field(self, field: InflatedValue) -> None:
        if isinstance(field, NamedBalloon):
            named_type = type(field)
            tracker = self._trackers[named_type]
            tracker.track(field)
        elif isinstance(field, Balloon):
            for subfield in field.__dict__.values():
                self._track_field(subfield)
        elif isinstance(field, dict):
            for key, value in field.items():
                self._track_field(key)
                self._track_field(value)
        elif isinstance(field, (set, tuple)):
            for item in field:
                self._track_field(item)
        elif isinstance(field, (Enum, Atomic, None)):  # type: ignore[arg-type]
            pass
        else:
            raise ValueError(f"Unsupported type: {type(field)}")


class DynamicTypeProvider(Protocol):
    """
    Efficiently provides the dynamic type of a balloon by name and static type.
    """

    def get(self, name: str, static_type: type[B]) -> type[B] | None:
        """
        Provide the type of the balloon with a given name and static type.

        :param name: Name of the balloon.
        :param static_type: Static type of the balloon.
        :return: Dynamic type of the balloon, if any.
        """


class DynamicTypeTracker(Protocol):
    """
    Efficiently tracks the dynamic type of a balloon.
    """

    def track(self, name: str, dynamic_type: type[B]) -> None:
        """
        Track the dynamic type of a balloon.

        :param name: Name of the balloon.
        :param dynamic_type: Dynamic type of the balloon.

        :raises ValueError: If a namespace conflict is detected.
        """


class EmptyDynamicTypeProvider(DynamicTypeProvider):
    """
    The dynamic type provider with no balloons.
    """

    def get(self, name: str, dynamic_type: type[B]) -> None:
        return None


class DynamicTypeManager(DynamicTypeProvider, DynamicTypeTracker):
    """
    Efficiently manages the dynamic types of balloons.
    """

    def __init__(
        self,
        namespace_types: set[type[Balloon]],
        baseline_provider: DynamicTypeProvider,
    ) -> None:
        """
        :param namespace_types: Balloon types that define a namespace.
        :param baseline_provider: Base provider of dynamic types.
        """
        self._namespace_types = namespace_types
        self._baseline_provider = baseline_provider

        self._name_to_dynamic_types: dict[str, set[type[Balloon]]] = defaultdict(set)

    def get(self, name: str, static_type: type[B]) -> type[B] | None:
        if all(not issubclass(static_type, t) for t in self._namespace_types):
            raise ValueError(f"Unsupported namespace type: {static_type}")

        dynamic_types = self._name_to_dynamic_types[name]

        candidate_dynamic_types = {
            t for t in dynamic_types if issubclass(t, static_type)
        }

        if len(candidate_dynamic_types) == 0:
            return self._baseline_provider.get(name, static_type)

        if len(candidate_dynamic_types) > 1:
            raise ValueError(f"Found multiple balloons with name: {name}")

        dynamic_type = candidate_dynamic_types.pop()
        return dynamic_type

    def track(self, name: str, dynamic_type: type[Balloon]) -> None:
        if self.get(name, dynamic_type) is dynamic_type:
            return

        for namespace_type in self._namespace_types:
            if not issubclass(dynamic_type, namespace_type):
                continue

            if (existing_dynamic_type := self.get(name, namespace_type)) is not None:
                raise ValueError(
                    "Found balloon type conflict in a namespace.\n"
                    f"Namespace type: {namespace_type}\n"
                    f"Name: {name}\n"
                    f"Existing type: {existing_dynamic_type}\n"
                    f"New type: {dynamic_type}"
                )

        self._name_to_dynamic_types[name].add(dynamic_type)


class BalloonProvider(Protocol[B]):  # type: ignore[misc]
    """
    Provides named balloons of a balloon type, including subtypes.
    """

    def get(self, name: str) -> B:
        """
        Provide the balloon with the given name, possibly inflating it from the JSON
        database if missing from memory.

        :param name: Balloon name.
        :return: Balloon with the given name.
        """

    def get_names(self) -> set[str]:
        """
        Provide the names of the balloons.

        :return: Names of the balloons.
        """


class BalloonTracker(Protocol[B]):  # type: ignore[misc]
    """
    Tracks named balloons of a balloon type, including subtypes.
    """

    def track(self, balloon: B) -> None:
        """
        Track a balloon, possibly deflating it to the JSON database if missing from
        disk.

        :param balloon: Balloon to track.
        """


class StandardBalloonProvider(BalloonProvider[B]):
    """
    Provides named balloons of a balloon type, including subtypes.
    """

    def __init__(
        self,
        type_: type[B],
        specialized_providers: dict[
            type[Balloon], SpecializedBalloonProvider[NamedBalloon]
        ],
        dynamic_type_provider: DynamicTypeProvider,
    ) -> None:
        """
        :param type_: Type of the managed balloons.
        :param specialized_providers: Specialized providers for each type of balloon.
        :param dynamic_type_manager: Manager of dynamic types of balloons.
        """
        self._type = type_
        self._dynamic_type_provider = dynamic_type_provider
        self._specialized_providers = specialized_providers

    def get(self, name: str) -> B:
        type_ = self._dynamic_type_provider.get(name, self._type)
        if type_ is None:
            raise ValueError(f"Could not find balloon with name: {name}")

        return self._specialized_providers[type_].get(name)  # type: ignore[return-value]

    def get_names(self) -> set[str]:
        return {n for p in self._specialized_providers.values() for n in p.get_names()}


class StandardBalloonTracker(BalloonTracker[B]):
    def __init__(
        self,
        type_: type[B],
        specialized_trackers: dict[
            type[Balloon], SpecializedBalloonTracker[NamedBalloon]
        ],
        dynamic_type_tracker: DynamicTypeManager,
    ) -> None:
        """
        :param type_: Type of the managed balloons.
        :param specialized_trackers: Specialized trackers for each type of balloon.
        :param dynamic_type_tracker: Tracker of dynamic types of balloons.
        """
        self._type = type_
        self._specialized_trackers = specialized_trackers
        self._dynamic_type_tracker = dynamic_type_tracker

    def track(self, balloon: B) -> None:
        if not isinstance(balloon, NamedBalloon):
            raise ValueError(f"Balloon is not named: {balloon}")

        named_type = type(balloon)
        type_ = named_type.Base

        # Idempotent, makes sure the types match
        self._dynamic_type_tracker.track(balloon.name, type_)
        # Idempotent, makes sure the values match
        self._specialized_trackers[type_].track(balloon)


class BalloonManager(BalloonProvider[B], BalloonTracker[B]):
    """
    Manages named balloons of a balloon type, including subtypes.
    """

    def __init__(
        self,
        type_: type[B],
        provider: BalloonProvider[B],
        tracker: BalloonTracker[B],
    ) -> None:
        """
        :param type_: Type of the managed balloons.
        :param provider: Provider of the balloons.
        :param tracker: Tracker of the balloons.
        """
        self._type = type_
        self._provider = provider
        self._tracker = tracker

    def get(self, name: str) -> B:
        return self._provider.get(name)

    def get_names(self) -> set[str]:
        return self._provider.get_names()

    def track(self, balloon: B) -> None:
        self._tracker.track(balloon)


class Balloonist(Generic[B]):
    """
    Inflates and deflates balloons of a certain type, including subtypes.
    """

    def __init__(
        self,
        type_: type[B],
        inflator: Inflator,
        deflator: Deflator,
    ) -> None:
        """
        :param type_: Type of the managed balloons.
        :param inflator: Inflator of deflated values.
        :param deflator: Deflator of inflated values.
        """
        self._type = type_
        self._inflator = inflator
        self._deflator = deflator

    def inflate(self, deflated_balloon: DeflatedValue) -> B:
        """
        Inflate a balloon.

        :param deflated_balloon: Deflated balloon.
        :return: The inflated balloon.
        """
        return self._inflator.inflate(deflated_balloon, self._type)

    def deflate(self, inflated_balloon: B) -> DeflatedValue:
        """
        Deflate a balloon.

        :param inflated_balloon: Inflated balloon.
        :return: The deflated balloon.
        """
        if not isinstance(inflated_balloon, self._type):
            raise ValueError(f"Could not handle type: {type(inflated_balloon)}")

        return self._deflator.deflate(inflated_balloon)


class ClosedBalloonWorld:
    """
    A world of where the set of existing balloons is fixed.
    """

    def __init__(
        self,
        namespace_types: set[type[Balloon]],
        specialized_providers: dict[
            type[Balloon], SpecializedBalloonProvider[NamedBalloon]
        ],
        dynamic_type_provider: DynamicTypeProvider,
        inflator: Inflator,
        deflator: Deflator,
    ) -> None:
        """
        :param namespace_types: Balloon types representing a namespace.
        :param specialized_providers: Specialized providers for each type of balloon.
        :param dynamic_type_manager: Manager of dynamic types of balloons.
        :param inflator: Inflator of deflated values.
        :param deflator: Deflator of inflated values.
        """
        self._namespace_types = namespace_types
        self._specialized_providers = specialized_providers
        self._dynamic_type_provider = dynamic_type_provider
        self._inflator = inflator
        self._deflator = deflator

    def get_provider(self, type_: type[B]) -> BalloonProvider[B]:
        """
        Instantiate a balloon provider for a given type.

        :param type_: Balloon type.
        :return: The balloon provider for the type.
        """
        if all(not issubclass(type_, t) for t in self._namespace_types):
            raise ValueError(f"Unsupported balloon type: {type_}")

        specialized_providers: dict[
            type[Balloon], SpecializedBalloonProvider[NamedBalloon]
        ] = {
            t: bs
            for t, bs in self._specialized_providers.items()
            if issubclass(t, type_)
        }

        return StandardBalloonProvider(
            type_=type_,
            specialized_providers=specialized_providers,
            dynamic_type_provider=self._dynamic_type_provider,
        )

    def get_balloonist(self, type_: type[B]) -> Balloonist[B]:
        return Balloonist(
            type_=type_,
            inflator=self._inflator,
            deflator=self._deflator,
        )

    # ---------------------------------------------------------------------------------

    def populate(self, database_path: Path) -> ClosedBalloonWorld:
        """
        Populate the world with balloons from a database.

        :param database_path: Path to the database.
        :return: The populated world.
        """
        specialized_providers: dict[
            type[Balloon], SpecializedBalloonProvider[NamedBalloon]
        ] = {}

        inflator = Inflator(
            types_={t.__qualname__: t for t in self._specialized_providers},
            providers=specialized_providers,
        )
        deflator = Deflator(
            providers=specialized_providers,
        )

        for type_, specialized_provider in self._specialized_providers.items():
            jsons_path = database_path / type_.__qualname__
            jsons_path.mkdir(exist_ok=True)
            names = {p.stem for p in jsons_path.iterdir()}

            specialized_providers[type_] = StandardSpecializedBalloonProvider(
                type_=type_.Named,
                jsons_path=jsons_path,
                cache=BalloonDatabaseCache(type_=type_.Named, names=names),
                baseline_provider=specialized_provider,
                inflator=inflator,
            )

        dynamic_type_manager = DynamicTypeManager(
            namespace_types=self._namespace_types,
            baseline_provider=self._dynamic_type_provider,
        )
        for type_, specialized_provider in specialized_providers.items():
            for name in specialized_provider.get_names():
                dynamic_type_manager.track(name, type_)

        return ClosedBalloonWorld(
            namespace_types=self._namespace_types,
            specialized_providers=specialized_providers,
            dynamic_type_provider=dynamic_type_manager,
            inflator=inflator,
            deflator=deflator,
        )

    def to_open(self, database_path: Path) -> OpenBalloonWorld:
        """
        Convert the world to an open world.

        :param database_path: Path to the database where new balloons are stored.
        :return: The open world.
        """
        specialized_providers: dict[
            type[Balloon], SpecializedBalloonProvider[NamedBalloon]
        ] = {}
        specialized_trackers: dict[
            type[Balloon], SpecializedBalloonTracker[NamedBalloon]
        ] = {}

        inflator = Inflator(
            types_={t.__qualname__: t for t in self._specialized_providers},
            providers=specialized_providers,
        )
        deflator = Deflator(
            providers=specialized_providers,
        )

        for type_, specialized_provider in self._specialized_providers.items():
            jsons_path = database_path / type_.__qualname__
            jsons_path.mkdir(exist_ok=True)
            names = {p.stem for p in jsons_path.iterdir()}
            cache = BalloonDatabaseCache(type_=type_.Named, names=names)

            specialized_providers[type_] = StandardSpecializedBalloonProvider(
                type_=type_.Named,
                jsons_path=jsons_path,
                cache=cache,
                baseline_provider=specialized_provider,
                inflator=inflator,
            )
            specialized_trackers[type_] = SpecializedBalloonTracker(
                type_=type_.Named,
                jsons_path=jsons_path,
                trackers=specialized_trackers,
                cache=cache,
                baseline_provider=specialized_provider,
                inflator=inflator,
                deflator=deflator,
            )

        dynamic_type_manager = DynamicTypeManager(
            namespace_types=self._namespace_types,
            baseline_provider=self._dynamic_type_provider,
        )
        for type_, specialized_provider in specialized_providers.items():
            for name in specialized_provider.get_names():
                dynamic_type_manager.track(name, type_)

        return OpenBalloonWorld(
            namespace_types=self._namespace_types,
            specialized_providers=specialized_providers,
            specialized_trackers=specialized_trackers,
            dynamic_type_manager=dynamic_type_manager,
            inflator=inflator,
            deflator=deflator,
        )

    # TODO: Give the possibility to extend namespaces and schema types
    # def extend(self, namespace_types, types): ...

    @staticmethod
    def create(
        namespace_types: set[type[Balloon]],
        types_: set[type[Balloon]],
    ) -> ClosedBalloonWorld:
        """
        Create an empty world of balloons with a given schema.

        :param namespace_types: Balloon types representing a namespace.
        :param types: Balloon types to manage.
        """
        empty_specialized_providers: dict[
            type[Balloon], SpecializedBalloonProvider[NamedBalloon]
        ] = {t: EmptySpecializedBalloonProvider() for t in types_}

        return ClosedBalloonWorld(
            namespace_types=namespace_types,
            specialized_providers=empty_specialized_providers,
            dynamic_type_provider=EmptyDynamicTypeProvider(),
            inflator=Inflator(
                types_={t.__qualname__: t for t in empty_specialized_providers},
                providers=empty_specialized_providers,
            ),
            deflator=Deflator(
                providers=empty_specialized_providers,
            ),
        )


class OpenBalloonWorld:
    """
    A world where the set of existing balloons can grow.
    """

    def __init__(
        self,
        namespace_types: set[type[Balloon]],
        specialized_providers: dict[
            type[Balloon], SpecializedBalloonProvider[NamedBalloon]
        ],
        specialized_trackers: dict[
            type[Balloon], SpecializedBalloonTracker[NamedBalloon]
        ],
        dynamic_type_manager: DynamicTypeManager,
        inflator: Inflator,
        deflator: Deflator,
    ) -> None:
        """
        :param namespace_types: Balloon types representing a namespace.
        :param specialized_providers: Specialized providers for each type of balloon.
        :param specialized_trackers: Specialized trackers for each type of balloon.
        :param dynamic_type_manager: Manager of dynamic types of balloons.
        :param inflator: Inflator of deflated values.
        :param deflator: Deflator of inflated values.
        """
        self._namespace_types = namespace_types
        self._specialized_providers = specialized_providers
        self._specialized_trackers = specialized_trackers
        self._dynamic_type_manager = dynamic_type_manager
        self._inflator = inflator
        self._deflator = deflator

    def get_provider(self, type_: type[B]) -> BalloonProvider[B]:
        """
        Instantiate a balloon provider for a balloon type

        :param type_: Balloon type.
        :return: Balloon provider for the balloon type.
        """
        if all(not issubclass(type_, t) for t in self._namespace_types):
            raise ValueError(f"Unsupported balloon type: {type_}")

        specialized_providers = {
            t: specialized_provider
            for t, specialized_provider in self._specialized_providers.items()
            if issubclass(t, type_)
        }

        return StandardBalloonProvider(
            type_=type_,
            specialized_providers=specialized_providers,  # type: ignore[arg-type]
            dynamic_type_provider=self._dynamic_type_manager,
        )

    def get_tracker(self, type_: type[B]) -> BalloonTracker[B]:
        """
        Instantiate a balloon tracker for a balloon type.

        :param type_: Balloon type.
        :return: Balloon tracker for the balloon type.
        """
        if all(not issubclass(type_, t) for t in self._namespace_types):
            raise ValueError(f"Unsupported balloon type: {type_}")

        specialized_trackers = {
            t: specialized_tracker
            for t, specialized_tracker in self._specialized_trackers.items()
            if issubclass(t, type_)
        }

        return StandardBalloonTracker(
            type_=type_,
            specialized_trackers=specialized_trackers,  # type: ignore[arg-type]
            dynamic_type_tracker=self._dynamic_type_manager,
        )

    def get_manager(self, type_: type[B]) -> BalloonManager[B]:
        """
        Instantiate a manager for a balloon type.

        :param type_: Balloon type.
        :return: Balloonist for the balloon type.
        """
        provider = self.get_provider(type_)
        tracker = self.get_tracker(type_)
        return BalloonManager(type_=type_, provider=provider, tracker=tracker)
