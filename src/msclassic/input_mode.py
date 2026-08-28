from __future__ import annotations

import configparser
import io
from xml.etree import ElementTree


class InputModeError(ValueError):
    pass


def _transform_openbox(source: bytes) -> bytes:
    try:
        root = ElementTree.fromstring(source)
    except ElementTree.ParseError as exc:
        raise InputModeError("Openbox keyboard configuration is malformed") from exc
    try:
        keyboard = next(
            node for node in root.iter() if _local_name(node.tag) == "keyboard"
        )
    except StopIteration as exc:
        raise InputModeError("Openbox keyboard configuration is malformed") from exc
    for binding in list(keyboard):
        if (
            _local_name(binding.tag) == "keybind"
            and binding.get("key") not in {"A-Tab", "A-S-Tab"}
        ):
            keyboard.remove(binding)
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _transform_lxqt(source: bytes) -> bytes:
    parser = configparser.RawConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        parser.read_string(source.decode("utf-8"))
    except (UnicodeDecodeError, configparser.Error) as exc:
        raise InputModeError("LXQt shortcut configuration is malformed") from exc
    for section in parser.sections():
        if section != "General" and not section.startswith("XF86"):
            parser.set(section, "Enabled", "false")
    stream = io.StringIO()
    parser.write(stream, space_around_delimiters=False)
    return stream.getvalue().encode("utf-8")
