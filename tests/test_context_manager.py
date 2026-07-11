"""Tests for context_manager module."""

import pytest
from storyloom.core.context_manager import ContextManager
from storyloom.config import WINDOW_SIZE, FIRST_COMPRESSION_AT


class TestContextManagerInit:
    def test_initial_state_has_no_messages(self):
        cm = ContextManager()
        assert cm.round_count == 0
        assert len(cm.get_messages()) == 0

    def test_initial_state_has_no_compressed_rounds(self):
        cm = ContextManager()
        assert cm.get_compressed_rounds() == []

    def test_initial_state_window_is_empty(self):
        cm = ContextManager()
        assert cm.get_window_rounds() == []


class TestRound1Setup:
    def test_set_round1_stores_messages(self):
        cm = ContextManager()
        cm.set_round1(
            user_content="你是叙事引擎...",
            assistant_content="<story>...</story>",
        )
        assert cm.round_count == 1
        msgs = cm.get_messages()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_set_round1_raises_if_already_set(self):
        cm = ContextManager()
        cm.set_round1("prompt", "output")
        with pytest.raises(RuntimeError, match="Round 1 already set"):
            cm.set_round1("prompt2", "output2")

    def test_round1_messages_are_never_compressed(self):
        cm = ContextManager()
        cm.set_round1("prompt", "output")
        for _ in range(10):
            cm.add_round("ctx", "<story><bridge/><seg n='1'>t</seg></story>")
        msgs = cm.get_messages()
        assert msgs[0]["content"] == "prompt"
        assert msgs[1]["content"] == "output"


class TestAddRound:
    def test_add_round_increments_count(self):
        cm = ContextManager()
        cm.set_round1("prompt", "output")
        cm.add_round("Round 2 context", "<story><bridge/><seg n='1'>t</seg></story>")
        assert cm.round_count == 2

    def test_add_round_appends_user_message(self):
        cm = ContextManager()
        cm.set_round1("prompt", "output")
        cm.add_round("Round 2 context", "<story><bridge/><seg n='1'>t</seg></story>")
        msgs = cm.get_messages()
        user_messages = [m for m in msgs if m["role"] == "user"]
        assert any("Round 2 context" in m["content"] for m in user_messages)

    def test_add_round_raises_without_round1(self):
        cm = ContextManager()
        with pytest.raises(RuntimeError, match="Round 1 not set"):
            cm.add_round("ctx", "<story><bridge/><seg n='1'>t</seg></story>")


class TestSlidingWindow:
    def test_no_compression_before_threshold(self):
        cm = ContextManager()
        cm.set_round1("p", "o")
        cm.add_round("r2", "<story><bridge/><seg n='1'>t</seg></story>")
        cm.add_round("r3", "<story><bridge/><seg n='1'>t</seg></story>")
        cm.add_round("r4", "<story><bridge/><seg n='1'>t</seg></story>")
        assert cm.get_compressed_rounds() == []

    def test_compression_starts_at_round_5(self):
        cm = ContextManager()
        cm.set_round1("p", "o")
        cm.add_round("r2", '<story><checkpoint node="ch2" summary="接头"/><bridge/><seg n="1">t</seg></story>')
        cm.add_round("r3", '<story><checkpoint node="ch3" summary="交易"/><bridge/><seg n="1">t</seg></story>')
        cm.add_round("r4", '<story><bridge/><seg n="1">t</seg></story>')
        cm.add_round("r5", '<story><bridge/><seg n="1">t</seg></story>')
        compressed = cm.get_compressed_rounds()
        assert len(compressed) >= 1


class TestWindowRounds:
    def test_window_contains_last_n_rounds(self):
        cm = ContextManager()
        cm.set_round1("p", "o")
        for i in range(2, 8):
            cm.add_round(f"r{i}", "<story><bridge/><seg n='1'>t</seg></story>")
        window = cm.get_window_rounds()
        assert len(window) <= WINDOW_SIZE


class TestCheckpointExtraction:
    def test_extract_checkpoint_summaries_from_output(self):
        cm = ContextManager()
        xml = (
            '<story>'
            '<checkpoint node="ch2" summary="在旅店接头。"/>'
            '<bridge/>'
            '<seg n="1">tail text</seg>'
            '</story>'
        )
        summaries = cm._extract_checkpoint_summaries(xml)
        assert "在旅店接头" in summaries

    def test_extract_returns_empty_for_no_checkpoint(self):
        cm = ContextManager()
        xml = '<story><bridge/><seg n="1">t</seg></story>'
        summaries = cm._extract_checkpoint_summaries(xml)
        assert summaries == ""


class TestCompressionFormat:
    def test_build_compression_message(self):
        cm = ContextManager()
        summaries = ["在旅店接头", "完成芯片交易", "选择信任耗子"]
        user_msg, asst_msg = cm._build_compression_messages(summaries)
        assert "Key events so far" in user_msg
        assert "在旅店接头" in user_msg
        assert "完成芯片交易" in user_msg
        assert asst_msg == "(Summary of previous events. The story continues.)"


class TestGetMessagesForRound:
    def test_returns_messages_array_for_api_call(self):
        cm = ContextManager()
        cm.set_round1("Round 1 prompt", "<story>...</story>")
        cm.add_round("r2 ctx", '<story><checkpoint node="c2" summary="接头"/><bridge/><seg n="1">t</seg></story>')
        msgs = cm.get_messages()
        assert len(msgs) >= 2
        assert msgs[0]["role"] == "user"


class TestBridgeText:
    def test_bridge_text_is_stored_for_next_round(self):
        cm = ContextManager()
        cm.set_round1("p", "o")
        xml = (
            '<story>\n'
            '<bridge/>\n'
            '<seg>你对耗子点了点头。</seg>\n'
            '<seg>耗子: 跟我来。</seg>\n'
            '</story>'
        )
        cm.add_round("r2 context", xml)
        bridge = cm.get_last_bridge_text()
        assert "你对耗子点了点头" in bridge
        assert "耗子: 跟我来" in bridge
