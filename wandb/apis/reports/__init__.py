# flake8: noqa
from inspect import cleandoc

from ... import termlog
from . import blocks, panels, helpers
from .helpers import LineKey, PCColumn
from .blocks import *
from .panels import *
from .reports import Report
from .runset import Runset

termlog(
    cleandoc(
        """
        Thanks for trying out the Report API!
          ∟ see panels:          \033[92m`wr.panels.<tab>`
          ∟ see blocks:          \033[92m`wr.blocks.<tab>`
          ∟ see everything else: \033[92m`wr.<tab>`
        
        If you have issues, please make a ticket on JIRA.
        """
    )
)
