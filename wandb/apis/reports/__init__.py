# flake8: noqa
from inspect import cleandoc

from ... import termlog
from ._blocks import (
    H1,
    H2,
    H3,
    BlockQuote,
    CalloutBlock,
    CheckedList,
    CodeBlock,
    Gallery,
    HorizontalRule,
    Image,
    InlineCode,
    InlineLaTeX,
    LaTeXBlock,
    MarkdownBlock,
    OrderedList,
    P,
    PanelGrid,
    SoundCloud,
    Spotify,
    TableOfContents,
    Twitter,
    UnorderedList,
    Video,
    WeaveTableBlock,
)
from .helpers import LineKey, PCColumn
from ._panels import (
    BarPlot,
    CodeComparer,
    CustomChart,
    LinePlot,
    MarkdownPanel,
    MediaBrowser,
    ParallelCoordinatesPlot,
    ParameterImportancePlot,
    RunComparer,
    ScalarChart,
    ScatterPlot,
    WeaveTablePanel,
)
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
