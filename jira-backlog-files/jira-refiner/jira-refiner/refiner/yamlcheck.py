"""Shared plumbing for reading a YAML settings file and reporting problems in plain words.

Used by the rules file (rules.py) and the hints file (context.py). Every problem names the
line it is on and says what to fix. ALL problems are collected, not just the first.
"""
from __future__ import annotations

import difflib
import re

import yaml


class SettingsError(Exception):
    """A settings file has problems. `.problems` holds one plain sentence per problem."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


def load_yaml(text, source):
    """Parse YAML text. Returns (data, line_numbers). Raises SettingsError if the YAML is broken."""
    try:
        root = yaml.compose(text)
        data = yaml.safe_load(text)
    except yaml.YAMLError as err:
        mark = getattr(err, "problem_mark", None)
        line = f"line {mark.line + 1}" if mark else "an unknown line"
        reason = getattr(err, "problem", None) or "the layout is wrong"
        raise SettingsError([f"{source}, {line}: the file is not valid YAML ({reason}). Check the colons and the spaces at the start of the line."])
    if not isinstance(data, dict):
        raise SettingsError([f"{source}: the file should be a list of settings, one per line, like 'rules_version: 1'."])
    return data, line_index(root)


def line_index(node, path=(), found=None):
    """Map each setting's path, like ('fields', 'summary', 'min_chars'), to its line number."""
    if found is None:
        found = {}
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            where = path + (key_node.value,)
            found[where] = key_node.start_mark.line + 1
            line_index(value_node, where, found)
    elif isinstance(node, yaml.SequenceNode):
        for number, item in enumerate(node.value):
            where = path + (number,)
            found[where] = item.start_mark.line + 1
            line_index(item, where, found)
    return found


def dotted(path):
    """['sizing', 'work_patterns', 1, 'words'] -> sizing.work_patterns[2].words (people count from 1)."""
    name = ""
    for part in path:
        if isinstance(part, int):
            name += f"[{part + 1}]"
        else:
            name += ("." if name else "") + str(part)
    return name


class Reader:
    """Reads settings out of loaded YAML and records a plain-word problem for each bad one."""

    def __init__(self, data, lines, source):
        self.data = data
        self.lines = lines
        self.source = source
        self.problems = []

    # -- problems ---------------------------------------------------------
    def bad(self, path, message):
        name = dotted(path) or "the top of the file"
        self.problems.append(f"{self.source}, {self._where(path)}: '{name}' {message}")

    def _where(self, path):
        # A missing setting has no line of its own, so use the nearest section that does.
        for size in range(len(path), 0, -1):
            line = self.lines.get(tuple(path[:size]))
            if line:
                return f"line {line}"
        return "near the top"

    # -- finding values ---------------------------------------------------
    def find(self, path):
        current = self.data
        for part in path:
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and isinstance(part, int) and 0 <= part < len(current):
                current = current[part]
            else:
                return False, None
        return True, current

    def mapping(self, path, allowed):
        """Check that `path` is a group of settings and that it holds no unknown names."""
        found, value = self.find(path)
        if not found:
            if path:
                self.bad(path, "is missing. Add this section back.")
            return {}
        if not isinstance(value, dict):
            self.bad(path, "should be a group of settings, one per line, indented under its name.")
            return {}
        for key in value:
            if key not in allowed:
                close = difflib.get_close_matches(str(key), [str(a) for a in allowed], n=1)
                tip = f" Did you mean '{close[0]}'?" if close else ""
                self.bad(path + [key], f"is not a setting this tool knows.{tip}")
        return value

    def _required(self, path):
        found, value = self.find(path)
        if not found:
            self.bad(path, "is missing. Add it back.")
        return found, value

    # -- typed getters ----------------------------------------------------
    def flag(self, path):
        found, value = self._required(path)
        if found and not isinstance(value, bool):
            self.bad(path, f"must be true or false (found {value!r}).")
            return False
        return value if found else False

    def whole(self, path, minimum=0):
        found, value = self._required(path)
        if not found:
            return minimum
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            self.bad(path, f"must be a whole number, {minimum} or more (found {value!r}).")
            return minimum
        return value

    def number(self, path, minimum=0, maximum=None, allow_equal=True):
        found, value = self._required(path)
        if not found:
            return float(minimum) + 1
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        if ok:
            ok = value >= minimum if allow_equal else value > minimum
        if ok and maximum is not None:
            ok = value <= maximum
        if not ok:
            rule = f"more than {minimum}" if not allow_equal else f"{minimum} or more"
            if maximum is not None:
                rule += f" and no more than {maximum}"
            self.bad(path, f"must be a number, {rule} (found {value!r}).")
            return float(minimum) + 1
        return float(value)

    def text_list(self, path, non_empty=False, options=None):
        """A list of words. A missing list counts as empty (so optional lists can be left out)."""
        found, value = self.find(path)
        if not found:
            if non_empty:
                self.bad(path, "is missing. Add it back.")
            return []
        if not isinstance(value, list) or not all(isinstance(x, (str, int, float)) and not isinstance(x, bool) for x in value):
            self.bad(path, "must be a list, for example [a, b, c].")
            return []
        items = [str(x).strip() for x in value]
        if non_empty and not items:
            self.bad(path, "must have at least one entry.")
        if options:
            for item in items:
                if item not in options:
                    self.bad(path, f"has '{item}', which is not allowed. Use only: {', '.join(options)}.")
        return items

    def choice(self, path, options):
        found, value = self._required(path)
        if not found:
            return options[0]
        if value not in options:
            self.bad(path, f"must be one of {', '.join(options)} (found {value!r}).")
            return options[0]
        return value

    def pattern(self, path):
        found, value = self._required(path)
        if not found:
            return ""
        if not isinstance(value, str) or not value.strip():
            self.bad(path, "must be some text in quotes.")
            return ""
        try:
            re.compile(value, re.IGNORECASE | re.DOTALL)
        except re.error as err:
            self.bad(path, f"is not a valid pattern ({err}).")
        return value

    def color(self, path):
        found, value = self._required(path)
        if not found:
            return "FFFFFF"
        if not isinstance(value, str) or not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
            self.bad(path, f'must be a 6-digit color code in quotes, like "FFD966" (found {value!r}).')
            return "FFFFFF"
        return value.upper()

    def text(self, path):
        found, value = self._required(path)
        if not found:
            return ""
        if not isinstance(value, str) or not value.strip():
            self.bad(path, "must be some text.")
            return ""
        return value.strip()

    def optional_text(self, path):
        """Text that may be left out. Returns '' when missing."""
        found, value = self.find(path)
        if not found or value is None:
            return ""
        if not isinstance(value, str):
            self.bad(path, "must be some text in quotes.")
            return ""
        return value.strip()
