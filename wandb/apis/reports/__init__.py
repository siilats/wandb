from inspect import cleandoc
from colorama import Fore

from ... import termlog
from . import blocks, helpers, panels
from .blocks import *
from .helpers import LineKey, PCColumn
from .panels import *
from .report import Report
from .runset import Runset

termlog(
    cleandoc(
        f"""
        Thanks for trying out the Report API!  Try out tab completion to see what's available.
          ∟ everything:   {Fore.GREEN}`wr.<tab>`
              ∟ panels:   {Fore.GREEN}`wr.panels.<tab>`
              ∟ blocks:   {Fore.GREEN}`wr.blocks.<tab>`
              ∟ helpers:  {Fore.GREEN}`wr.helpers.<tab>`
        
        If you have issues, please make a ticket on JIRA.
        """
    )
)
