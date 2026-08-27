from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, unquote_plus, urlsplit


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class LaunchRequest:
    game_code: str
    obd_tag: str | None
    arguments: tuple[str, ...]


_ASCII_WHITESPACE = re.compile(r"[\t\n\v\f\r ]+")
_MAX_URI_BYTES = 65_536
_MAX_TOKENS = 128
_MAX_TOKEN_BYTES = 4_096
_INVALID_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")
_NGM_FIELD_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


def parse_launch_uri(uri: str) -> LaunchRequest:
    if not isinstance(uri, str) or len(uri.encode("utf-8")) > _MAX_URI_BYTES:
        raise ProtocolError("invalid authenticated launch URI size")
    try:
        scheme = urlsplit(uri).scheme.lower()
    except ValueError as exc:
        raise ProtocolError("invalid authenticated launch URI") from exc
    if scheme == "nexonplug":
        return parse_nexonplug_uri(uri)
    if scheme == "ngm":
        return parse_ngm_uri(uri)
    raise ProtocolError("unsupported authenticated launch URI")


def parse_nexonplug_uri(uri: str) -> LaunchRequest:
    if not isinstance(uri, str) or len(uri.encode("utf-8")) > _MAX_URI_BYTES:
        raise ProtocolError("invalid NexonPlug URI size")
    parsed = urlsplit(uri)
    if parsed.scheme.lower() != "nexonplug" or parsed.fragment:
        raise ProtocolError("invalid NexonPlug URI")

    values: dict[str, list[str]] = {}
    for raw_pair in parsed.query.split("&"):
        if not raw_pair:
            continue
        raw_name, separator, raw_value = raw_pair.partition("=")
        name = unquote_plus(raw_name)
        value = unquote_plus(raw_value if separator else "")
        values.setdefault(name, []).append(value)

    game_values = values.get("game", [])
    passarg_values = values.get("passarg", [])
    if len(game_values) != 1 or len(passarg_values) != 1:
        raise ProtocolError("NexonPlug URI requires one game and one passarg")

    game = game_values[0]
    game_code, at, obd_tag = game.partition("@")
    if game_code != "2982":
        raise ProtocolError("unsupported NexonPlug game")
    normalized_tag = obd_tag if at and obd_tag else None

    return _build_request(game, passarg_values[0], "NexonPlug")


def parse_ngm_uri(uri: str) -> LaunchRequest:
    if not isinstance(uri, str) or len(uri.encode("utf-8")) > _MAX_URI_BYTES:
        raise ProtocolError("invalid NGM URI size")
    try:
        parsed = urlsplit(uri)
    except ValueError as exc:
        raise ProtocolError("invalid NGM URI") from exc
    if (
        parsed.scheme.lower() != "ngm"
        or parsed.netloc.lower() != "launch"
        or parsed.query
        or parsed.fragment
        or _INVALID_PERCENT.search(parsed.path)
    ):
        raise ProtocolError("invalid NGM URI")
    try:
        path = unquote(parsed.path, errors="strict")
    except UnicodeDecodeError as exc:
        raise ProtocolError("invalid NGM URI encoding") from exc
    if not path.startswith("/ "):
        raise ProtocolError("invalid NGM launch path")
    fields = _parse_ngm_fields(path[2:])
    if fields.get("mode") != "launch":
        raise ProtocolError("unsupported NGM mode")
    try:
        game = fields["game"]
        passarg = fields["passarg"]
    except KeyError as exc:
        raise ProtocolError("NGM URI is missing a required field") from exc
    return _build_request(game, passarg, "NGM")


def _parse_ngm_fields(argument: str) -> dict[str, str]:
    if not argument or "\x00" in argument:
        raise ProtocolError("invalid NGM argument")
    required = {"mode", "game", "passarg"}
    captured: dict[str, str] = {}
    index = 0
    field_count = 0
    while index < len(argument):
        if field_count:
            if argument[index] != " ":
                raise ProtocolError("invalid NGM field separator")
            while index < len(argument) and argument[index] == " ":
                index += 1
        if index >= len(argument) or argument[index] != "-":
            raise ProtocolError("invalid NGM field")
        index += 1
        match = _NGM_FIELD_NAME.match(argument, index)
        if match is None or match.end() >= len(argument) or argument[match.end()] != ":":
            raise ProtocolError("invalid NGM field name")
        name = match.group(0).lower()
        index = match.end() + 1
        if index < len(argument) and argument[index] == "'":
            end = argument.find("'", index + 1)
            if end < 0:
                raise ProtocolError("unterminated NGM field")
            value = argument[index + 1 : end]
            index = end + 1
        else:
            end = argument.find(" ", index)
            if end < 0:
                end = len(argument)
            value = argument[index:end]
            index = end
        if not value or (index < len(argument) and argument[index] != " "):
            raise ProtocolError("invalid NGM field value")
        if name in required:
            if name in captured:
                raise ProtocolError("duplicate NGM field")
            captured[name] = value
        field_count += 1
        if field_count > 64:
            raise ProtocolError("too many NGM fields")
    return captured


def _build_request(game: str, passarg: str, protocol: str) -> LaunchRequest:
    game_code, at, obd_tag = game.partition("@")
    if game_code != "2982":
        raise ProtocolError(f"unsupported {protocol} game")
    normalized_tag = obd_tag if at and obd_tag else None
    if "\x00" in passarg:
        raise ProtocolError(f"{protocol} passarg contains NUL")
    arguments = tuple(value for value in _ASCII_WHITESPACE.split(passarg) if value)
    if not arguments or len(arguments) > _MAX_TOKENS:
        raise ProtocolError(f"invalid {protocol} argument count")
    if any(len(value.encode("utf-8")) > _MAX_TOKEN_BYTES for value in arguments):
        raise ProtocolError(f"{protocol} argument is too large")
    return LaunchRequest(game_code, normalized_tag, arguments)
