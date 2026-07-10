"""XML output parser package."""

from storyloom.parser.xml_parser import (
    ParsedOutput,
    ParseError,
    Segment,
    SetOperation,
    XmlParser,
)
from storyloom.parser.streaming_parser import (
    EventType,
    LineBuffer,
    ParseEvent,
    StreamingXmlParser,
)

__all__ = [
    "EventType",
    "ParseError",
    "ParseEvent",
    "ParsedOutput",
    "Segment",
    "SetOperation",
    "StreamingXmlParser",
    "XmlParser",
    "LineBuffer",
]
