"""Navigation model for the interactive menu.

A pure state machine, so the menu's logic is testable without a terminal:
the curses layer only renders the current Screen and feeds key presses into
these transitions. All real work (resolving, plucking) stays in the other
core modules; an Item's `action` is an opaque token the caller executes.
"""

from dataclasses import dataclass


@dataclass
class Item:
    """A menu row: a submenu (``children``) or a leaf that carries an action."""

    label: str
    children: list["Item"] | None = None
    action: object | None = None


@dataclass
class Screen:
    title: str
    items: list["Item"]
    cursor: int = 0


class Browser:
    """A stack of screens with cursor movement, drill-in, and back."""

    def __init__(self, root: Screen) -> None:
        self.stack: list[Screen] = [root]

    @property
    def screen(self) -> Screen:
        return self.stack[-1]

    def move(self, delta: int) -> None:
        """Move the cursor, wrapping at both ends (empty screens no-op)."""
        count = len(self.screen.items)
        if count:
            self.screen.cursor = (self.screen.cursor + delta) % count

    def back(self) -> bool:
        """Pop to the parent screen; False if already at the root."""
        if len(self.stack) > 1:
            self.stack.pop()
            return True
        return False

    def enter(self) -> object | None:
        """Open the selected submenu (returns None), or return a leaf's action."""
        if not self.screen.items:
            return None
        item = self.screen.items[self.screen.cursor]
        if item.children is not None:
            self.stack.append(Screen(item.label, item.children))
            return None
        return item.action


def search_items(items: list[Item], query: str) -> list[Item]:
    """Flatten matching leaves while preserving their original actions."""
    needle = query.casefold().strip()
    if not needle:
        return []
    matches: list[Item] = []

    def visit(rows: list[Item], trail: tuple[str, ...]) -> None:
        for item in rows:
            if item.children is not None:
                visit(item.children, (*trail, item.label))
            elif needle in item.label.casefold() or any(
                needle in segment.casefold() for segment in trail
            ):
                context = " / ".join(trail)
                label = f"{item.label}  [{context}]" if context else item.label
                matches.append(Item(label, action=item.action))

    visit(items, ())
    return matches
