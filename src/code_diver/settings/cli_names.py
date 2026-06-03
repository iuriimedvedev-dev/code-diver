from __future__ import annotations

from enum import StrEnum


class CommandName(StrEnum):
    ASK = "ask"
    CHAT = "chat"
    EVALUATE = "evaluate"
    EVALUATE_INDEXING = "evaluate-indexing"
    EVALUATE_SEARCH_TOOLS = "evaluate-search-tools"
    EXPERIMENT = "experiment"
    GREP = "grep"
    INDEX = "index"
    INDEX_SELECTED = "index-selected"
    MONITOR = "monitor"
    OPEN = "open"
    READ = "read"
    RG = "rg"
    SEARCH = "search"
    SYMBOLS = "symbols"
    TREE = "tree"


class OptionName(StrEnum):
    BENCHMARK = "--benchmark"
    CONFIG = "--config"
    DATASET = "--dataset"
    DETAILS = "--details"
    EXTENSION = "--extension"
    HELP_ALL = "--help-all"
    HYPOTHESIS = "--hypothesis"
    JSON = "--json"
    LIMIT = "--limit"
    MODEL = "--model"
    PATH = "--path"
    PRINT = "-p"
    PROMPT_TEMPLATE = "--prompt-template"
    PROVIDER = "--provider"
    RANK = "--rank"
    REINDEX = "--reindex"
    ROOT = "--root"
    START_LINE = "--start-line"
    TOOLSET = "--toolset"
    TOOLS = "--tools"
    LINES = "--lines"
    YES = "--yes"
