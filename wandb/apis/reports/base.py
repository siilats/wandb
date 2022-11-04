from typing import Any, Dict, TypeVar

from ..public import PanelMetricsHelper
from .util import Attr, ShortReprMixin, SubclassOnlyABC, coalesce, generate_name

T = TypeVar("T")


class Base(SubclassOnlyABC, ShortReprMixin):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._spec = {}

    @property
    def spec(self) -> Dict[str, Any]:
        return self._spec

    @classmethod
    def from_json(cls, spec: Dict[str, Any]) -> T:
        obj = cls()
        obj._spec = spec
        return obj

    def _get_path(self, var: str) -> str:
        return vars(type(self))[var].path_or_name


class Panel(Base, SubclassOnlyABC):
    layout: dict = Attr(json_path="spec.layout")

    def __init__(
        self, layout: Dict[str, int] = None, *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self._spec["viewType"] = self.view_type
        self._spec["__id__"] = generate_name()
        self.layout = coalesce(layout, self._default_panel_layout())
        self.panel_metrics_helper = PanelMetricsHelper()

    @property
    def view_type(self) -> str:
        return "UNKNOWN PANEL"

    @property
    def config(self) -> Dict[str, Any]:
        return self._spec["config"]

    @staticmethod
    def _default_panel_layout() -> Dict[str, int]:
        return {"x": 0, "y": 0, "w": 8, "h": 6}


class Block(Base, SubclassOnlyABC):
    pass
