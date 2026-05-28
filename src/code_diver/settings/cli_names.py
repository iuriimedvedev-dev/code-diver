from __future__ import annotations

from enum import StrEnum


class CommandName(StrEnum):
    ASK = "ask"
    CHAT = "chat"
    EVALUATE = "evaluate"
    INDEX = "index"
    OPEN = "open"
    SEARCH = "search"


class OptionName(StrEnum):
    CONFIG = "--config"
    DATASET = "--dataset"
    DETAILS = "--details"
    EXTENSION = "--extension"
    JSON = "--json"
    LIMIT = "--limit"
    MODEL = "--model"
    PRINT = "-p"
    PROMPT_TEMPLATE = "--prompt-template"
    PROVIDER = "--provider"
    RANK = "--rank"
    REINDEX = "--reindex"
    TOOLS = "--tools"
