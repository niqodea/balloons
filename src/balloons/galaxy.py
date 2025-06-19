from dataclasses import dataclass
from pathlib import Path
from typing import (
    Self,
)

from balloons.core import (
    Balloon,
    BalloonCache,
    BalloonWorld,
    ClosedBalloonWorld,
    DefaultDynamicTypeProvider,
    Deflator,
    DynamicTypeCache,
    DynamicTypeProvider,
    DynamicTypeTracker,
    EmptyDynamicTypeProvider,
    EmptySpecializedBalloonProvider,
    Inflator,
    NamedBalloon,
    OpenBalloonWorld,
    SpecializedBalloonProvider,
    SpecializedBalloonTracker,
)


class BalloonGalaxy:
    """
    A galaxy of balloon worlds.
    """

    @dataclass
    class WorldState:
        balloon_caches: dict[type[Balloon], BalloonCache[NamedBalloon]]
        dynamic_type_provider: DynamicTypeProvider

    def __init__(
        self,
        schema: BalloonWorld.Schema,
    ) -> None:
        """
        :param schema: Schema of the worlds in the galaxy.
        """
        self._schema = schema
        self._states: dict[BalloonWorld.Id, BalloonGalaxy.WorldState] = {}
        self._paths: dict[BalloonWorld.Id, Path] = {}
        self._baselines: dict[BalloonWorld.Id, BalloonWorld.Id] = {}

    def get(self, world_path: Path) -> BalloonWorld:
        raise NotImplementedError

    def get_open(self, world_path: Path) -> OpenBalloonWorld:
        raise NotImplementedError

    def populate(self, world_path: Path) -> Self:
        """
        Populate this world with balloons from a new world.

        :param world_path: Path to the new world.
        :return: The populated world.
        """
        specialized_providers: dict[
            type[Balloon], SpecializedBalloonProvider[NamedBalloon]
        ] = {}

        inflator = Inflator(
            types_={t.__qualname__: t for t in self._schema.types_},
            providers=specialized_providers,
        )
        deflator = Deflator(
            providers=specialized_providers,
        )

        for type_, specialized_provider in self._specialized_providers.items():
            jsons_path = world_path / type_.__qualname__
            jsons_path.mkdir(exist_ok=True)
            names = {p.stem for p in jsons_path.iterdir()}

            specialized_providers[type_] = SpecializedBalloonProvider(
                type_=type_.Named,
                jsons_path=jsons_path,
                cache=BalloonCache(type_=type_.Named, names=names),
                baseline_provider=specialized_provider,
                inflator=inflator,
            )

        dynamic_type_cache = DynamicTypeCache()
        for type_, specialized_provider in specialized_providers.items():
            for name in specialized_provider.get_names():
                dynamic_type_cache.track(name, type_)

        dynamic_type_provider = DefaultDynamicTypeProvider(
            namespace_types=self._schema.namespace_types,
            cache=dynamic_type_cache,
            baseline_provider=self._dynamic_type_provider,
        )

        return ClosedBalloonWorld(
            schema=self._schema,
            specialized_providers=specialized_providers,
            dynamic_type_provider=dynamic_type_provider,
            inflator=inflator,
            deflator=deflator,
        )

    def to_open(self, world_path: Path) -> OpenBalloonWorld:
        """
        Convert the world to an open world.

        :param world_path: Path to the world where new balloons are tracked.
        :return: The open world.
        """
        specialized_providers: dict[
            type[Balloon], SpecializedBalloonProvider[NamedBalloon]
        ] = {}
        specialized_trackers: dict[
            type[Balloon], SpecializedBalloonTracker[NamedBalloon]
        ] = {}

        inflator = Inflator(
            types_={t.__qualname__: t for t in self._schema.types_},
            providers=specialized_providers,
        )
        deflator = Deflator(
            providers=specialized_providers,
        )

        for type_, specialized_provider in self._specialized_providers.items():
            jsons_path = world_path / type_.__qualname__
            jsons_path.mkdir(exist_ok=True)
            names = {p.stem for p in jsons_path.iterdir()}
            cache = BalloonCache(type_=type_.Named, names=names)

            specialized_providers[type_] = SpecializedBalloonProvider(
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

        dynamic_type_cache = DynamicTypeCache()
        for type_, specialized_provider in specialized_providers.items():
            for name in specialized_provider.get_names():
                dynamic_type_cache.track(name, type_)

        dynamic_type_provider = DefaultDynamicTypeProvider(
            namespace_types=self._schema.namespace_types,
            cache=dynamic_type_cache,
            baseline_provider=self._dynamic_type_provider,
        )

        dynamic_type_tracker = DynamicTypeTracker(
            namespace_types=self._schema.namespace_types,
            cache=dynamic_type_cache,
            baseline_provider=self._dynamic_type_provider,
        )

        return OpenBalloonWorld(
            schema=self._schema,
            specialized_providers=specialized_providers,
            specialized_trackers=specialized_trackers,
            dynamic_type_provider=dynamic_type_provider,
            dynamic_type_tracker=dynamic_type_tracker,
            inflator=inflator,
            deflator=deflator,
        )

    # TODO: Give the possibility to extend namespaces and schema types
    # def extend(self, namespace_types, types): ...

    @staticmethod
    def create(
        namespace_types: set[type[Balloon]] | None = None,
        top_types: set[type[Balloon]] | None = None,
        top_nameable_types: set[type[Balloon]] | None = None,
    ) -> ClosedBalloonWorld:
        """
        Create an empty world of balloons.

        :param namespace_types: Balloon types representing a namespace.
        :param top_nameable_types: Top balloon types with named instances.
        :param top_types: Top balloon types.
        """
        if namespace_types is None:
            namespace_types = {Balloon}

        if top_types is None:
            top_types = {Balloon}

        if top_nameable_types is None:
            top_nameable_types = {Balloon}

        types_ = ClosedBalloonWorld._get_dependency_closure(top_types)
        nameable_types = ClosedBalloonWorld._get_subtype_closure(top_nameable_types)

        if not namespace_types <= types_:
            raise ValueError("Namespace types must be a subset of all types")

        if not nameable_types <= types_:
            raise ValueError("Nameable types must be a subset of all types")

        for nameable_type in nameable_types:
            if all(not issubclass(nameable_type, t) for t in namespace_types):
                raise ValueError(
                    f"Nameable type must reside in a namespace: {nameable_type}"
                )

        for namespace_type in namespace_types:
            if all(not issubclass(t, namespace_type) for t in nameable_types):
                raise ValueError(
                    f"Namespace type must contain nameable types: {namespace_type}"
                )

        empty_specialized_providers: dict[
            type[Balloon], SpecializedBalloonProvider[NamedBalloon]
        ] = {t: EmptySpecializedBalloonProvider() for t in nameable_types}

        return ClosedBalloonWorld(
            schema=BalloonWorld.Schema(
                types_=types_,
                namespace_types=namespace_types,
                nameable_types=nameable_types,
            ),
            specialized_providers=empty_specialized_providers,
            dynamic_type_provider=EmptyDynamicTypeProvider(),
            inflator=Inflator(
                types_={t.__qualname__: t for t in types_},
                providers=empty_specialized_providers,
            ),
            deflator=Deflator(
                providers=empty_specialized_providers,
            ),
        )
