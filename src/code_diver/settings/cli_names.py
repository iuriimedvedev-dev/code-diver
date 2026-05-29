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
    OPEN = "open"
    READ = "read"
    RG = "rg"
    SEARCH = "search"
    SYMBOLS = "symbols"
    TREE = "tree"


class OptionName(StrEnum):
    CONFIG = "--config"
    DATASET = "--dataset"
    DETAILS = "--details"
    EXTENSION = "--extension"
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
    START_LINE = "--start-line"
    TOOLSET = "--toolset"
    TOOLS = "--tools"
    LINES = "--lines"
