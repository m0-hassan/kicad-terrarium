import re

_TABLE_NAME_PATTERN = re.compile(r'\(name "([^"]+)"\)')


def registered_libraries(table_text: str) -> set[str]:
    """Library names declared in a sym-lib-table."""
    return set(_TABLE_NAME_PATTERN.findall(table_text))


def external_libraries(used: set[str], registered: set[str]) -> set[str]:
    """
    Libraries the project USES but has NOT registered locally.

    An empty result means every library the design references is available
    inside the project itself - i.e. it's self-contained

    Example: external_libraries({"terrarium", "Device"}, {"terrarium"}) -> {"Device"}
    """
    return used - registered
