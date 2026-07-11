"""Parse LLM XML output into structured data.

.. deprecated::
    Use ``StreamingXmlParser`` instead.  This module is retained for
    backwards compatibility during the migration period.  Data types
    (``ParsedOutput``, ``Segment``, etc.) are owned by
    ``streaming_parser``.
"""

import re
from xml.etree import ElementTree as ET

from storyloom.parser.streaming_parser import (
    ParsedOutput,
    ParseError,
    RouteTarget,
    Segment,
    SetOperation,
)


class XmlParser:
    """Parse LLM XML narrative output."""

    PROHIBITED_POST_BRIDGE = {"choice", "set", "checkpoint"}

    @staticmethod
    def parse(text: str) -> ParsedOutput:
        """Parse LLM output text into ParsedOutput.

        Args:
            text: Raw LLM output, may contain markdown fences.

        Returns:
            ParsedOutput with structured data.

        Raises:
            ParseError: If XML is malformed or violates rules.
        """
        xml_str = XmlParser._extract_xml(text)
        if xml_str is None:
            raise ParseError("Missing <story>")

        root = XmlParser._parse_xml(xml_str)
        children = list(root)

        # Find bridge
        bridge_idx = XmlParser._find_bridge(children)

        pre_children = children[:bridge_idx]
        post_children = children[bridge_idx + 1:]

        result = ParsedOutput()
        result.bridge_found = True

        # Check post-bridge prohibited
        prohibited = []
        for el in post_children:
            if el.tag in XmlParser.PROHIBITED_POST_BRIDGE:
                prohibited.append(el.tag)
        if prohibited:
            raise ParseError(
                f"Prohibited elements after bridge: {', '.join(prohibited)}"
            )

        # Collect segments
        XmlParser._collect_segments(pre_children, "pre", result)
        XmlParser._collect_segments(post_children, "post", result)
        result.total_segments = len(result.segments)
        result.pre_segments = sum(1 for s in result.segments if s.position == "pre")
        result.post_segments = sum(
            1 for s in result.segments if s.position == "post"
        )

        # Extract choice
        XmlParser._extract_choice(pre_children, result)

        # Extract sets
        XmlParser._extract_sets(root, result)

        # Extract checkpoint
        XmlParser._extract_checkpoint(pre_children, result)

        # Extract bridge text (all post-bridge text, stripped of XML)
        result.bridge_text = XmlParser._extract_bridge_text(post_children)

        return result

    @staticmethod
    def _extract_xml(text: str) -> str | None:
        """Extract XML from LLM output, removing markdown fences."""
        parts = text.split("\n---\n", 1)
        llm_out = parts[1] if len(parts) > 1 else text

        llm_out = re.sub(r"^```(?:xml)?\s*\n", "", llm_out, flags=re.MULTILINE)
        llm_out = re.sub(r"\n```\s*$", "", llm_out)

        story_start = llm_out.find("<story>")
        story_end = llm_out.rfind("</story>")

        if story_start < 0:
            return None
        if story_end < 0:
            story_end = len(llm_out)
        else:
            story_end += len("</story>")

        xml_str = llm_out[story_start:story_end].strip()
        if not xml_str:
            return None

        # Strip line number prefixes (NNN| ) — they are not part of the XML
        xml_str = re.sub(r'^\d{3}\| ', '', xml_str, flags=re.MULTILINE)

        xml_str = re.sub(
            r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)",
            "&amp;",
            xml_str,
        )
        return xml_str

    @staticmethod
    def _parse_xml(xml_str: str) -> ET.Element:
        """Parse XML string into ElementTree."""
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError as e:
            raise ParseError(f"XML parse error: {e}")

        if root.tag != "story":
            raise ParseError(
                f"Root is <{root.tag}>, expected <story>"
            )

        if not list(root):
            raise ParseError("Empty <story>")
        return root

    @staticmethod
    def _find_bridge(children: list[ET.Element]) -> int:
        """Find bridge index, raise on 0 or 2+."""
        bridge_indices = [
            i
            for i, el in enumerate(children)
            if el.tag == "bridge"
        ]
        if len(bridge_indices) == 0:
            raise ParseError("No <bridge/> found")
        if len(bridge_indices) > 1:
            raise ParseError("Multiple <bridge/> elements")
        return bridge_indices[0]

    @staticmethod
    def _collect_segments(
        children: list[ET.Element],
        position: str,
        result: ParsedOutput,
    ) -> None:
        """Collect <seg> elements from children, including nested in <branch>."""
        for el in children:
            if el.tag == "seg":
                try:
                    n = int(el.get("n", 0))
                except (ValueError, TypeError):
                    n = 0
                result.segments.append(
                    Segment(
                        n=n, text=(el.text or "").strip(), position=position
                    )
                )
            elif el.tag == "branch":
                branch_name = el.get("name", "")
                if position == "pre":
                    result.pre_branches.append(branch_name)
                else:
                    result.post_branches.append(branch_name)
                for seg_el in el.findall("seg"):
                    try:
                        n = int(seg_el.get("n", 0))
                    except ValueError:
                        raise ParseError(
                            f"Non-integer seg n value: {seg_el.get('n')}"
                        )
                    result.segments.append(
                        Segment(
                            n=n,
                            text=(seg_el.text or "").strip(),
                            position=position,
                            branch=branch_name,
                        )
                    )

    @staticmethod
    def _extract_choice(
        pre_children: list[ET.Element],
        result: ParsedOutput,
    ) -> None:
        """Extract all <choice> elements from pre-bridge children."""
        for el in pre_children:
            if el.tag == "choice":
                cid = el.get("id")
                opts = list(el.findall("opt"))
                branches = [o.get("branch", "") for o in opts]
                labels = [(o.text or "").strip() for o in opts]
                conditions = {
                    o.get("branch", ""): o.get("if")
                    for o in opts if o.get("if")
                }
                result.choices.append({
                    "id": cid,
                    "branches": branches,
                    "labels": labels,
                    "conditions": conditions,
                })
        # Backwards compat
        if result.choices:
            result.choice_id = result.choices[-1]["id"]
            result.opt_branches = result.choices[-1]["branches"]

    @staticmethod
    def _extract_sets(root: ET.Element, result: ParsedOutput) -> None:
        """Extract all <set> elements."""
        for el in root.iter("set"):
            result.sets.append(
                SetOperation(
                    var=el.get("var", ""),
                    op=el.get("op", ""),
                    val=el.get("val", ""),
                    condition=el.get("if"),
                )
            )

    @staticmethod
    def _extract_checkpoint(
        pre_children: list[ET.Element],
        result: ParsedOutput,
    ) -> None:
        """Extract <checkpoint> from pre-bridge children."""
        for el in pre_children:
            if el.tag == "checkpoint":
                if result.checkpoint_node is not None:
                    raise ParseError("Multiple <checkpoint> elements")
                result.checkpoint_node = el.get("node")
                result.checkpoint_summary = el.get("summary")
                for route_el in el.findall("route"):
                    result.routes.append(
                        RouteTarget(
                            condition=route_el.get("if"),
                            target=route_el.get("target", ""),
                        )
                    )

    @staticmethod
    def _extract_bridge_text(
        post_children: list[ET.Element],
        current_branch: str | None = None,
    ) -> str:
        """Extract plain text from post-bridge elements.

        Extraction logic:
        - current_branch=None: extract all text (backwards compat).
        - current_branch=\"\": extract bare <seg> only (explicit main).
        - current_branch=\"name\": extract from matching <branch> AND
          bare <seg> elements.  Bare segs are the implicit \"main\"
          branch, which matches regardless of current_branch per the
          default-branch rule (see block-separators.md).
        """
        texts = []
        for el in post_children:
            if el.tag == "seg":
                # Bare segs: include when (a) no filter, (b) explicit
                # main, or (c) named branch — main always matches.
                if current_branch is None or current_branch == "" or current_branch:
                    if el.text:
                        texts.append(el.text.strip())
            elif el.tag == "branch":
                if current_branch is None or el.get("name") == current_branch:
                    for seg_el in el.findall("seg"):
                        if seg_el.text:
                            texts.append(seg_el.text.strip())
        return "\n".join(texts)

    @staticmethod
    def extract_bridge_text_for_branch(xml_str: str, branch_name: str) -> str:
        """Extract bridge text filtered to a specific branch.

        Re-parses the XML and returns only the post-bridge text from
        the matching <branch name="..."> (or bare <seg> elements when
        branch_name is empty).

        Args:
            xml_str: Raw LLM output (may contain line numbers).
            branch_name: Branch name to match, or "" for the default
                         single-path (bare segs, no branch wrapper).

        Returns:
            Filtered bridge text string.
        """
        clean = XmlParser._extract_xml(xml_str)
        if clean is None:
            return ""
        root = XmlParser._parse_xml(clean)
        children = list(root)
        bridge_idx = XmlParser._find_bridge(children)
        post_children = children[bridge_idx + 1:]
        return XmlParser._extract_bridge_text(post_children, current_branch=branch_name)
