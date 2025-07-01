from __future__ import annotations

import json
import sys
from abc import ABC, abstractmethod
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

    # Hack to return same type, even though it's not technically self
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
        if not isinstance(self, NamedBalloon):
            raise ValueError(f"Balloon is not named: {self}")
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


Balloon.Named = NamedBalloon


@dataclass_transform(frozen_default=True)
def balloon(cls: type[Balloon]) -> type[Balloon]:
    """
    Decorator required to correctly setup balloon classes.
    """

    # TODO: Evaluate whether having kw_only=True is a good idea here
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

B = TypeVar("B", bound=Balloon, covariant=True)
B_inv = TypeVar("B_inv", bound=Balloon)
BN = TypeVar("BN", bound=NamedBalloon, covariant=True)
BN_inv = TypeVar("BN_inv", bound=NamedBalloon)

E = TypeVar("E", bound=Enum, covariant=True)
A = TypeVar("A", bound=Atomic, covariant=True)

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
        balloonists: Mapping[type[Balloon], SpecializedBalloonist[NamedBalloon]],
    ) -> None:
        """
        :param types: The balloon types, indexed by their name.
        :param balloonists: The balloonists for the types.
        """
        self._types = types_
        self._balloonists = balloonists

    # NOTE: It's hard to get mypy to understand that what we return matches VI here
    # We thus ignore some complaints about return values
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
            if not isinstance(deflated_value, dict):
                raise ValueError(f"Expected dict, got: {type(deflated_value)}")
            key_type, value_type = type_args
            return {
                self.inflate(key, key_type): self.inflate(value, value_type)
                for key, value in deflated_value.items()
            }  # type: ignore[return-value]

        if type_origin is tuple:
            if len(type_args) != 2 or type_args[1] is not Ellipsis:
                raise ValueError(
                    "Expected type hint of the form 'tuple[T, ...]', received: "
                    f"{static_type}"
                )
            item_type = type_args[0]

            if not isinstance(deflated_value, list):
                raise ValueError(f"Expected list, got: {type(deflated_value)}")

            return tuple(self.inflate(item, item_type) for item in deflated_value)  # type: ignore[return-value]

        if type_origin is set:
            if not isinstance(deflated_value, list):
                raise ValueError(f"Expected list, got: {type(deflated_value)}")
            (item_type,) = type_args
            return {self.inflate(item, item_type) for item in deflated_value}  # type: ignore[return-value]

        if type_origin is UnionType:
            # NOTE: Arbitrary union types not implemented for now
            # They would either require a try/except logic or inspecting the deflated
            # value to determine the type
            if len(type_args) != 2 or type_args[1] is not NoneType:
                raise ValueError(f"Unsupported union type: {static_type}")
            optional_type, _ = type_args

            if deflated_value is None:
                return None  # type: ignore[return-value]

            return self.inflate(deflated_value, optional_type)

        if issubclass(static_type, Balloon):
            if isinstance(deflated_value, str):
                # it is a named balloon
                type_name, _, name = deflated_value.partition(":")
                type_ = self._types[type_name]
                if not issubclass(type_, static_type):
                    raise ValueError(f"Expected type: {static_type}, got: {type_}")

                if (balloonist := self._balloonists.get(type_)) is None:
                    raise ValueError(f"No balloonist for type: {type_}")
                return balloonist.get(name)  # type: ignore[return-value]

            if isinstance(deflated_value, dict):
                type_name = deflated_value["@type"]
                type_ = self._types[type_name]
                if not issubclass(type_, static_type):
                    raise ValueError(f"Expected type: {static_type}, got: {type_}")

                deflated_fields = {
                    k: v for k, v in deflated_value.items() if k[0] != "@"
                }
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
            if not isinstance(deflated_value, str):
                raise ValueError(f"Expected str, got: {type(deflated_value)}")
            return static_type[deflated_value]  # type: ignore[return-value]

        if issubclass(static_type, Atomic):
            if not isinstance(deflated_value, static_type):
                raise ValueError(f"Expected {static_type}, got: {type(deflated_value)}")
            return deflated_value  # type: ignore[return-value]

        raise ValueError(f"Unsupported type: {static_type}")


class Deflator:
    """
    Deflates values to their JSON representations.
    """

    def __init__(
        self,
        balloonists: Mapping[type[Balloon], SpecializedBalloonist[NamedBalloon]],
    ) -> None:
        """
        :param balloonists: The balloonists for the types of balloons.
        """
        self._balloonists = balloonists

    def deflate(self, inflated_value: InflatedValue) -> DeflatedValue:
        """
        Deflate a value.

        :param value: The value to deflate.
        :return: The deflated representation of the value.
        """
        if isinstance(inflated_value, NamedBalloon):
            type_ = type(inflated_value).Base
            balloonist = self._balloonists[type_]

            if inflated_value.name not in balloonist.get_names():
                raise ValueError(
                    f"Could not find balloon with name: {inflated_value.name}"
                )

            tracked_balloon = balloonist.get(inflated_value.name)
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
            return {"@type": type_.__qualname__} | deflated_fields

        if isinstance(inflated_value, dict):
            return {
                self.deflate(key): self.deflate(value)
                for key, value in inflated_value.items()
            }

        if isinstance(inflated_value, set | tuple):
            return [self.deflate(item) for item in inflated_value]

        if isinstance(inflated_value, Enum):
            return inflated_value.name

        if isinstance(inflated_value, Atomic):
            return inflated_value

        if inflated_value is None:
            return None

        raise ValueError(f"Unsupported type: {type(inflated_value)}")


class BalloonCache(Generic[BN]):
    """
    Caches information about balloons of a certain type.
    """

    def __init__(self, type_: type[BN], names: set[str]) -> None:
        """
        :param type_: Type of the managed balloons.
        :param names: Names of all the managed balloons.
        """
        self._type = type_
        self._names = names  # this is in fact another type of cache

        self._balloons: dict[str, BN] = {}

    def get_live_names(self) -> set[str]:
        """
        Get the names of the balloons residing in memory.
        """
        return set(self._balloons.keys())

    def get_all_names(self) -> set[str]:
        """
        Get the names of all balloons managed by this cache.
        """
        return self._names

    def get(self, name: str) -> BN:
        """
        Get a balloon residing in memory.

        :param name: The name of the balloon.
        """
        if name not in self._names:
            raise ValueError(f"Could not find balloon with name: {name}")

        return self._balloons[name]

    def track(self, balloon: BN_inv) -> None:
        """
        Track a balloon as in memory.

        :param balloon: The balloon to put.
        """
        if type(balloon) is not self._type:
            raise ValueError(f"Could not handle type: {type(balloon)}")

        if balloon.name in self._balloons:
            raise ValueError(f"Balloon already in cache: {balloon.name}")

        if balloon.name not in self._names:
            self._names.add(balloon.name)

        self._balloons[balloon.name] = balloon


class SpecializedBalloonist(Protocol[BN]):
    """
    Provides named balloons of a certain type, not including subtypes.
    """

    def get(self, name: str) -> BN:
        """
        Provide the balloon with the given name, possibly inflating it from JSON if
        missing from memory.

        :param name: Balloon name.
        :return: Balloon with the given name.
        """

    def get_names(self) -> set[str]:
        """
        Provide the names of the balloons.

        :return: Names of the balloons.
        """


# TODO: Settle on Default vs Structured as opposed to Empty
class DefaultSpecializedBalloonist(SpecializedBalloonist[BN]):
    """
    The standard specialized balloonist.
    """

    def __init__(
        self,
        type_: type[BN],
        jsons_path: Path,
        cache: BalloonCache[BN],
        baseline_balloonist: SpecializedBalloonist[BN],
        inflator: Inflator,
    ) -> None:
        """
        :param type_: Type of the managed balloons.
        :param jsons_path: Directory with the JSONs of the balloons.
        :param cache: Cache of the balloons.
        :param baseline_balloonist: Balloonist from the immutable baseline.
        :param inflator: Inflator of deflated values.
        """
        self._type = type_
        self._jsons_path = jsons_path
        self._cache = cache
        self._baseline_balloonist = baseline_balloonist
        self._inflator = inflator

    def get(self, name: str) -> BN:
        if name in self._cache.get_live_names():
            return self._cache.get(name)

        if name in self._cache.get_all_names():
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

        if name in self._baseline_balloonist.get_names():
            return self._baseline_balloonist.get(name)

        raise ValueError(f"Could not find balloon with name: {name}")

    def get_names(self) -> set[str]:
        return self._cache.get_all_names() | {
            n for n in self._baseline_balloonist.get_names()
        }

    @property
    def jsons_path(self) -> Path:
        """
        The path to the directory with the JSONs of the balloons.
        """
        return self._jsons_path

    @property
    def cache(self) -> BalloonCache[BN]:
        """
        The cache of the balloonist.
        """
        return self._cache


class EmptySpecializedBalloonist(SpecializedBalloonist[NoReturn]):
    def get(self, name: str) -> NoReturn:
        raise RuntimeError("This balloonist has no balloons.")

    def get_names(self) -> set[str]:
        return set()


class SpecializedBalloonTracker(Generic[BN]):
    """
    Tracks named balloons of a certain type, not including subtypes.
    """

    def __init__(
        self,
        type_: type[BN],
        jsons_path: Path,
        trackers: dict[type[Balloon], SpecializedBalloonTracker[NamedBalloon]],
        cache: BalloonCache[BN],
        baseline_balloonist: SpecializedBalloonist[BN],
        inflator: Inflator,
        deflator: Deflator,
    ) -> None:
        """
        :param type_: Type of the managed balloons.
        :param jsons_path: Directory with the JSONs of the balloons.
        :param trackers: Trackers of the balloons.
        :param cache: Cache of the balloons.
        :param baseline_balloonist: Balloonist from the immutable baseline.
        :param inflator: Inflator of deflated values.
        :param deflator: Deflator of inflated values.
        """
        self._type = type_
        self._jsons_path = jsons_path
        self._trackers = trackers
        self._cache = cache
        self._baseline_balloonist = baseline_balloonist
        self._inflator = inflator
        self._deflator = deflator

    def track(self, balloon: BN_inv) -> None:
        """
        Track a named balloon.

        :param balloon: The balloon to track.
        """
        if type(balloon) is not self._type:
            raise ValueError(f"Could not handle type: {type(balloon)}")

        # NOTE: We check with `is`, but we could also check with `==` to be less strict
        if balloon.name in self._baseline_balloonist.get_names():
            baseline_balloon = self._baseline_balloonist.get(balloon.name)
            if balloon is baseline_balloon:
                return
            raise ValueError(
                "Found two balloons in memory with same type and name\n"
                f"Type: {self._type.Base}\n"
                f"Name: {balloon.name}"
            )

        if balloon.name in self._cache.get_live_names():
            tracked_balloon = self._cache.get(balloon.name)
            if balloon is tracked_balloon:
                return
            raise ValueError(
                "Found two balloons in memory with same type and name\n"
                f"Type: {self._type.Base}\n"
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
            tracked_balloon = self._type(**init_kwargs)

            if balloon == tracked_balloon:
                self._cache.track(balloon)
                return

            raise ValueError(
                f"Found conflict between in-memory and tracked balloons.\n"
                f"In-memory balloon: {balloon}\n"
                f"Tracked balloon:    {tracked_balloon}"
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
        elif isinstance(field, set | tuple):
            for item in field:
                self._track_field(item)
        elif isinstance(field, Enum | Atomic | None):
            pass
        else:
            raise ValueError(f"Unsupported type: {type(field)}")


class DynamicTypeCache:
    """
    Caches the dynamic types of balloons by name.
    """

    def __init__(self) -> None:
        self._name_to_dynamic_types: dict[str, set[type[Balloon]]] = defaultdict(set)

    def get(self, name: str, static_type: type[B]) -> set[type[B]]:
        """
        Get the dynamic types of balloons with a given name and static type.

        :param name: Name of the balloon.
        :param static_type: Static type of the balloon.
        """
        return {
            t for t in self._name_to_dynamic_types[name] if issubclass(t, static_type)
        }

    def track(self, name: str, dynamic_type: type[Balloon]) -> None:
        """
        Track the dynamic type of a balloon.
        """
        self._name_to_dynamic_types[name].add(dynamic_type)


class DynamicTypeProvider(Protocol):
    """
    Provides the dynamic type of a balloon by name and static type.
    """

    def get(self, name: str, static_type: type[B]) -> type[B] | None:
        """
        Provide the type of the balloon with a given name and static type.

        :param name: Name of the balloon.
        :param static_type: Static type of the balloon.
        :return: Dynamic type of the balloon, if any.
        """


class DefaultDynamicTypeProvider(DynamicTypeProvider):
    """
    Provides the dynamic type of a balloon by name and static type.
    """

    def __init__(
        self,
        namespace_types: set[type[Balloon]],
        cache: DynamicTypeCache,
        baseline_provider: DynamicTypeProvider,
    ) -> None:
        """
        :param namespace_types: Balloon types that define a namespace.
        :param cache: Cache of the dynamic types of balloons.
        :param baseline_provider: Provider of types from the immutable baseline.
        """
        self._namespace_types = namespace_types
        self._cache = cache
        self._baseline_provider = baseline_provider

        self._name_to_dynamic_types: dict[str, set[type[Balloon]]] = defaultdict(set)

    def get(self, name: str, static_type: type[B]) -> type[B] | None:
        """
        Provide the type of the balloon with a given name and static type.

        :param name: Name of the balloon.
        :param static_type: Static type of the balloon.
        :return: Dynamic type of the balloon, if any.
        """
        if all(not issubclass(static_type, t) for t in self._namespace_types):
            raise ValueError(f"Unsupported static type: {static_type}")

        dynamic_types = self._cache.get(name, static_type)

        if len(dynamic_types) > 1:
            sys.exit(
                "Found multiple balloons with same name in a namespaced static type.\n"
                f"Name: {name}\n"
                f"Namespaced static type: {static_type}\n"
                f"Dynamic types: {dynamic_types}"
            )

        if len(dynamic_types) == 1:
            return dynamic_types.pop()

        if (dynamic_type := self._baseline_provider.get(name, static_type)) is not None:
            return dynamic_type

        return None

    @property
    def cache(self) -> DynamicTypeCache:
        """
        The cache of the dynamic types.
        """
        return self._cache


class EmptyDynamicTypeProvider(DynamicTypeProvider):
    def get(self, name: str, static_type: type[B]) -> None:
        return None


class DynamicTypeTracker:
    """
    Tracks the dynamic type of a balloon.
    """

    def __init__(
        self,
        namespace_types: set[type[Balloon]],
        cache: DynamicTypeCache,
        baseline_provider: DynamicTypeProvider,
    ) -> None:
        """
        :param namespace_types: Balloon types that define a namespace.
        :param cache: Cache of the dynamic types of balloons.
        :param baseline_provider: Provider of types from the immutable baseline.
        """
        self._namespace_types = namespace_types
        self._cache = cache
        self._baseline_provider = baseline_provider

    def track(self, name: str, dynamic_type: type[B]) -> None:
        """
        Track the dynamic type of a balloon.

        :param name: Name of the balloon.
        :param dynamic_type: Dynamic type of the balloon.

        :raises ValueError: If a namespace conflict is detected.
        """
        for namespace_type in self._namespace_types:
            if not issubclass(dynamic_type, namespace_type):
                continue

            baseline_dynamic_type = self._baseline_provider.get(name, namespace_type)
            if baseline_dynamic_type is None:
                continue
            if dynamic_type is baseline_dynamic_type:
                continue
            raise ValueError(
                "Found balloon type conflict in a namespace.\n"
                f"Namespace type: {namespace_type}\n"
                f"Name: {name}\n"
                f"Existing type: {baseline_dynamic_type}\n"
                f"New type: {dynamic_type}"
            )

            tracked_dynamic_types = self._cache.get(name, namespace_type)

            if len(tracked_dynamic_types) > 1:
                sys.exit(
                    "Found multiple balloons with same name in a namespace.\n"
                    f"Name: {name}\n"
                    f"Namespace: {namespace_type}\n"
                    f"Dynamic types: {tracked_dynamic_types}"
                )

            if len(tracked_dynamic_types) == 0:
                continue

            tracked_dynamic_type = tracked_dynamic_types.pop()

            if dynamic_type is tracked_dynamic_type:
                continue

            raise ValueError(
                "Found balloon type conflict in a namespace.\n"
                f"Namespace type: {namespace_type}\n"
                f"Name: {name}\n"
                f"Existing type: {tracked_dynamic_type}\n"
                f"New type: {dynamic_type}"
            )

        self._cache.track(name, dynamic_type)


class Balloonist(Generic[B]):
    """
    Provides named balloons of a balloon type, including subtypes.
    """

    def __init__(
        self,
        type_: type[B],
        specialized_balloonists: Mapping[
            type[Balloon], SpecializedBalloonist[NamedBalloon]
        ],
        dynamic_type_provider: DynamicTypeProvider,
    ) -> None:
        """
        :param type_: Type of the managed balloons.
        :param specialized_balloonists: Specialized balloonists for each type.
        :param dynamic_type_provider: Provider of dynamic types of balloons.
        """
        self._type = type_
        self._dynamic_type_provider = dynamic_type_provider
        self._specialized_balloonists = specialized_balloonists

    def get(self, name: str) -> B:
        """
        Provide the balloon with the given name, possibly inflating it from JSON if
        missing from memory.

        :param name: Balloon name.
        :return: Balloon with the given name.
        """
        type_ = self._dynamic_type_provider.get(name, self._type)

        if type_ is None:
            raise ValueError(f"Could not find balloon with name: {name}")

        # Hack to bind named to unnamed balloon types
        named_type: type[NamedBalloon] = type_.Named  # type: ignore[name-defined]
        specialized_balloonist: SpecializedBalloonist[named_type] = (  # type: ignore[valid-type]
            self._specialized_balloonists[type_]
        )
        return specialized_balloonist.get(name)

    def get_names(self) -> set[str]:
        """
        Provide the names of the balloons.

        :return: Names of the balloons.
        """
        return {
            n for p in self._specialized_balloonists.values() for n in p.get_names()
        }


class BalloonWorld:
    """
    A world of balloons.
    """


class StructuredBalloonWorld(BalloonWorld, ABC):
    """
    Structured balloon world.
    """

    @dataclass
    class Schema:
        """
        Schema for a structured world of balloons.
        """

        types_: set[type[Balloon]]
        """
        All balloon types of the world.
        """

        nameable_types: set[type[Balloon]]
        """
        Balloon types that can be named.
        """

        namespace_types: set[type[Balloon]]
        """
        Balloon types representing a namespace.
        """

    @abstractmethod
    def get_schema(self) -> Schema:
        """
        Get the schema of the world.

        :return: The schema of the world.
        """

    @abstractmethod
    def get_balloonist(self, type_: type[B]) -> Balloonist[B]:
        """
        Instantiate a balloonist for a given type.

        :param type_: Balloon type.
        :return: The balloonist for the type.
        """

    @staticmethod
    def _get_balloonist(
        type_: type[B],
        schema: Schema,
        specialized_balloonists: Mapping[
            type[Balloon],
            SpecializedBalloonist[NamedBalloon],
        ],
        dynamic_type_provider: DynamicTypeProvider,
    ) -> Balloonist[B]:
        if type_ not in schema.types_:
            raise ValueError(f"Unsupported balloon type: {type_}")

        if all(not issubclass(type_, t) for t in schema.namespace_types):
            raise ValueError(f"Type does not reside in a namespace: {type_}")

        nameable_types = {t for t in schema.nameable_types if issubclass(t, type_)}

        pertinent_specialized_balloonists: Mapping[
            type[Balloon], SpecializedBalloonist[NamedBalloon]
        ] = {t: specialized_balloonists[t] for t in nameable_types}

        return Balloonist(
            type_=type_,
            specialized_balloonists=pertinent_specialized_balloonists,
            dynamic_type_provider=dynamic_type_provider,
        )


class ClosedBalloonWorld(BalloonWorld, ABC):
    """
    A world of where the set of tracked balloons is fixed.
    """

    @abstractmethod
    def populate(
        self, schema: StructuredBalloonWorld.Schema, world_path: Path
    ) -> StructuredClosedBalloonWorld:
        """
        Populate this world with balloons from a new world.

        :param world_path: Path to the new world.
        :return: The populated world.
        """

    @staticmethod
    def _populate(
        schema: StructuredBalloonWorld.Schema,
        world_path: Path,
        baseline_schema: StructuredBalloonWorld.Schema,
        baseline_specialized_balloonists: Mapping[
            type[Balloon],
            SpecializedBalloonist[NamedBalloon],
        ],
        baseline_dynamic_type_provider: DynamicTypeProvider,
    ) -> StructuredClosedBalloonWorld:
        # TODO: Check schema compatibility
        specialized_balloonists: dict[
            type[Balloon], DefaultSpecializedBalloonist[NamedBalloon]
        ] = {}

        inflator = Inflator(
            types_={t.__qualname__: t for t in baseline_schema.types_},
            balloonists=specialized_balloonists,
        )

        for (
            type_,
            baseline_specialized_balloonist,
        ) in baseline_specialized_balloonists.items():
            jsons_path = world_path / type_.__qualname__
            jsons_path.mkdir(exist_ok=True)
            names = {p.stem for p in jsons_path.iterdir()}

            specialized_balloonists[type_] = DefaultSpecializedBalloonist(
                type_=type_.Named,
                jsons_path=jsons_path,
                cache=BalloonCache(type_=type_.Named, names=names),
                baseline_balloonist=baseline_specialized_balloonist,
                inflator=inflator,
            )

        dynamic_type_cache = DynamicTypeCache()
        for type_, baseline_specialized_balloonist in specialized_balloonists.items():
            for name in baseline_specialized_balloonist.get_names():
                dynamic_type_cache.track(name, type_)

        dynamic_type_provider = DefaultDynamicTypeProvider(
            namespace_types=baseline_schema.namespace_types,
            cache=dynamic_type_cache,
            baseline_provider=baseline_dynamic_type_provider,
        )

        return StructuredClosedBalloonWorld(
            schema=baseline_schema,
            specialized_balloonists=specialized_balloonists,
            dynamic_type_provider=dynamic_type_provider,
        )


class EmptyClosedBalloonWorld(ClosedBalloonWorld):
    """
    Balloon world with no balloons.
    """

    def populate(
        self, schema: StructuredBalloonWorld.Schema, world_path: Path
    ) -> StructuredClosedBalloonWorld:
        return self._populate(
            schema=schema,
            world_path=world_path,
            baseline_schema=schema,  # Trick to avoid defining the "empty" schema
            baseline_specialized_balloonists={
                t: EmptySpecializedBalloonist() for t in schema.types_
            },
            baseline_dynamic_type_provider=EmptyDynamicTypeProvider(),
        )


class StructuredClosedBalloonWorld(ClosedBalloonWorld, StructuredBalloonWorld):
    """
    Balloon world with a fixed set of balloons, structured with a schema.
    """

    def __init__(
        self,
        schema: StructuredBalloonWorld.Schema,
        specialized_balloonists: Mapping[
            type[Balloon],
            DefaultSpecializedBalloonist[NamedBalloon],
        ],
        dynamic_type_provider: DefaultDynamicTypeProvider,
    ) -> None:
        """
        :param schema: Schema of the world.
        :param specialized_balloonists: Specialized balloonists for each type.
        :param dynamic_type_provider: Providers of dynamic types of balloons.
        """
        self._schema = schema
        self._specialized_balloonists = specialized_balloonists
        self._dynamic_type_provider = dynamic_type_provider

    def get_schema(self) -> StructuredBalloonWorld.Schema:
        return self._schema

    def get_balloonist(self, type_: type[B]) -> Balloonist[B]:
        return StructuredBalloonWorld._get_balloonist(
            type_=type_,
            schema=self._schema,
            specialized_balloonists=self._specialized_balloonists,
            dynamic_type_provider=self._dynamic_type_provider,
        )

    def populate(
        self, schema: StructuredBalloonWorld.Schema, world_path: Path
    ) -> StructuredClosedBalloonWorld:
        return ClosedBalloonWorld._populate(
            schema=schema,
            world_path=world_path,
            baseline_schema=self._schema,
            baseline_specialized_balloonists=self._specialized_balloonists,
            baseline_dynamic_type_provider=self._dynamic_type_provider,
        )

    def to_open(self) -> StructuredOpenBalloonWorld:
        """
        Convert the world to an open one.

        :return: The world as open.
        """
        specialized_trackers: dict[
            type[Balloon], SpecializedBalloonTracker[NamedBalloon]
        ] = {}

        inflator = Inflator(
            types_={t.__qualname__: t for t in self._schema.types_},
            balloonists=self._specialized_balloonists,
        )
        deflator = Deflator(
            balloonists=self._specialized_balloonists,
        )

        for type_, specialized_balloonist in self._specialized_balloonists.items():
            specialized_trackers[type_] = SpecializedBalloonTracker(
                type_=type_.Named,
                jsons_path=specialized_balloonist.jsons_path,
                trackers=specialized_trackers,
                cache=specialized_balloonist.cache,
                baseline_balloonist=specialized_balloonist,
                inflator=inflator,
                deflator=deflator,
            )

        dynamic_type_tracker = DynamicTypeTracker(
            namespace_types=self._schema.namespace_types,
            cache=self._dynamic_type_provider.cache,
            baseline_provider=self._dynamic_type_provider,
        )

        return StructuredOpenBalloonWorld(
            schema=self._schema,
            specialized_balloonists=self._specialized_balloonists,
            specialized_trackers=specialized_trackers,
            dynamic_type_provider=self._dynamic_type_provider,
            dynamic_type_tracker=dynamic_type_tracker,
        )

    # TODO: Give the possibility to extend namespaces and schema types
    # def extend(self, namespace_types, types): ...

    @staticmethod
    def _get_dependency_closure(top_types: set[type[Balloon]]) -> set[type[Balloon]]:
        closure_types = set(top_types)
        active_types = set(top_types)
        while len(active_types) > 0:
            frontier_types = set()
            for type_ in active_types:
                subtypes = set(type_.__subclasses__()) - {type_.Named}
                frontier_types.update(subtypes)
                # NOTE: This cannot be made recursive due to the infinite loops caused
                # by forward references
                for field_type in get_type_hints(type_).values():
                    type_origin = get_origin(field_type)
                    type_args = get_args(field_type)

                    if type_origin is None:
                        if issubclass(field_type, Balloon):
                            frontier_types.add(field_type)
                    elif type_origin is dict:
                        key_type, value_type = type_args
                        if issubclass(key_type, Balloon):
                            frontier_types.add(key_type)
                        if issubclass(value_type, Balloon):
                            frontier_types.add(value_type)
                    elif type_origin is set:
                        (item_type,) = type_args
                        if issubclass(item_type, Balloon):
                            frontier_types.add(item_type)
                    elif type_origin is tuple:
                        item_type, _ = type_args
                        if issubclass(item_type, Balloon):
                            frontier_types.add(item_type)
                    elif type_origin is UnionType:
                        optional_type, _ = type_args
                        if issubclass(optional_type, Balloon):
                            frontier_types.add(optional_type)
                    elif type_origin is ClassVar:
                        pass

            active_types = frontier_types - closure_types
            closure_types.update(frontier_types)

        return closure_types

    @staticmethod
    def _get_subtype_closure(top_types: set[type[Balloon]]) -> set[type[Balloon]]:
        closure_types = set(top_types)
        active_types = set(top_types)
        while len(active_types) > 0:
            frontier_types = set()
            for type_ in active_types:
                subtypes = set(type_.__subclasses__()) - {type_.Named}
                frontier_types.update(subtypes)

            active_types = frontier_types - closure_types
            closure_types.update(frontier_types)

        return closure_types


class StructuredOpenBalloonWorld(StructuredBalloonWorld):
    """
    A world where the set of tracked balloons can grow.
    """

    def __init__(
        self,
        schema: StructuredBalloonWorld.Schema,
        specialized_balloonists: Mapping[
            type[Balloon], DefaultSpecializedBalloonist[NamedBalloon]
        ],
        specialized_trackers: dict[
            type[Balloon], SpecializedBalloonTracker[NamedBalloon]
        ],
        dynamic_type_provider: DynamicTypeProvider,
        dynamic_type_tracker: DynamicTypeTracker,
    ) -> None:
        """
        :param schema: Schema of the world.
        :param specialized_balloonists: Specialized balloonists for each type.
        :param specialized_trackers: Specialized trackers for each type.
        :param dynamic_type_provider: Provider of dynamic types of balloons.
        :param dynamic_type_tracker: Tracker of dynamic types of balloons.
        """
        self._schema = schema
        self._specialized_balloonists = specialized_balloonists
        self._specialized_trackers = specialized_trackers
        self._dynamic_type_provider = dynamic_type_provider
        self._dynamic_type_tracker = dynamic_type_tracker

    def get_schema(self) -> StructuredBalloonWorld.Schema:
        return self._schema

    def get_balloonist(self, type_: type[B]) -> Balloonist[B]:
        return StructuredBalloonWorld._get_balloonist(
            type_=type_,
            schema=self._schema,
            specialized_balloonists=self._specialized_balloonists,
            dynamic_type_provider=self._dynamic_type_provider,
        )

    def track(self, balloon: Balloon) -> None:
        """
        Track a balloon, possibly deflating it to JSON if missing from the world.
        """
        if not isinstance(balloon, NamedBalloon):
            raise ValueError(f"Balloon is not named: {balloon}")

        named_type = type(balloon)
        type_ = named_type.Base

        if type_ not in self._specialized_trackers:
            raise ValueError(f"Unsupported balloon type: {type_}")

        # Idempotent, makes sure the types match
        self._dynamic_type_tracker.track(balloon.name, type_)
        # Idempotent, makes sure the values match
        self._specialized_trackers[type_].track(balloon)
