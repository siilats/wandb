import inspect
import json
import re
import urllib
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Dict
from typing import List as LList
from typing import Optional, Union

import wandb

from .runset import Runset
from .util import (
    Attr,
    Base,
    Block,
    Panel,
    coalesce,
    fix_collisions,
    generate_name,
    nested_get,
    nested_set,
)


class LineKey:
    def __init__(self, key: str) -> None:
        self.key = key

    def __hash__(self) -> int:
        return hash(self.key)

    def __repr__(self) -> str:
        return f'LineKey(key="{self.key}")'

    @classmethod
    def from_run(cls, run: "wandb.apis.public.Run", metric: str) -> "LineKey":
        key = f"{run.id}:{metric}"
        return cls(key)

    @classmethod
    def from_panel_agg(cls, runset: "Runset", panel: "Panel", metric: str) -> "LineKey":
        key = f"{runset.id}-config:group:{panel.groupby}:null:{metric}"
        return cls(key)

    @classmethod
    def from_runset_agg(cls, runset: "Runset", metric: str) -> "LineKey":
        groupby = runset.groupby
        if runset.groupby is None:
            groupby = "null"

        key = f"{runset.id}-run:group:{groupby}:{metric}"
        return cls(key)


class PCColumn(Base):
    metric: str = Attr(json_path="spec.accessor")
    name: Optional[str] = Attr(json_path="spec.displayName")
    ascending: Optional[bool] = Attr(json_path="spec.inverted")
    log_scale: Optional[bool] = Attr(json_path="spec.log")

    def __init__(
        self, metric, name=None, ascending=None, log_scale=None, *args, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.metric = metric
        self.name = name
        self.ascending = ascending
        self.log_scale = log_scale

    @classmethod
    def from_json(cls, spec):
        obj = cls(metric=spec["accessor"])
        obj._spec = spec
        return obj
