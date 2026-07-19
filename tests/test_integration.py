"""Integration tests for conversation-based prompt architecture."""

from storyloom.core.context_manager import ContextManager
from storyloom.core.prompt_builder import PromptBuilder


SAMPLE_STORY = {
    "genre": "赛博朋克冒险",
    "tier": "medium",
    "label": "霓虹深渊",
    "setting": "2087年新东京地下城",
    "protagonist_name": "林焰",
    "protagonist_identity": "前荒坂安全顾问",
    "protagonist_traits": "冷静、道德灰色",
    "tone": "黑暗冷峻",
    "conflict": "一枚神秘芯片正在寻找宿主",
    "characters": "耗子（情报贩子）、美智子（安全主管）",
    "variables": [
        {"name": "体力", "type": "number", "initial": 80},
        {"name": "信任度", "type": "number", "initial": 10},
    ],
}

SAMPLE_OUTLINE = """ch1_bar [active] — 霓虹深渊
  → ch2_confrontation [pending]
ch2_confrontation [pending] — 地下交易
  ├→ ch3_ally [pending]
  └→ ch3_betrayal [pending]
ch3_ally [pending] — 盟友之路
ch3_betrayal [pending] — 背叛之路
ch4_safehouse [pending] — 安全屋"""

ROUND1_OUTPUT = """<story>
<seg>霓虹灯在潮湿的巷道地面上投下破碎的倒影。</seg>
<seg>耗子的酒吧藏在第三层地下通道的尽头。</seg>
<seg>林焰: 芯片在哪儿？</seg>
<choice id="approach">
  <opt key="A" branch="direct">直接问价</opt>
  <opt key="B" branch="careful">先探口风</opt>
</choice>
<set var="信任度" op="+" val="5" if="approach==1"/>
<set var="信任度" op="-" val="5" if="approach==2"/>
<checkpoint node="ch2_confrontation" summary="在霓虹深渊酒吧与耗子接头，选择了接触策略。">
  <route if="approach==1" target="ch3_ally"/>
  <route if="approach==2" target="ch3_betrayal"/>
</checkpoint>
<bridge/>
<branch name="direct">
<seg>你把信用棒拍在吧台上。</seg>
<seg>耗子: 痛快。不过我得提醒你——荒坂的人在找你。</seg>
</branch>
<branch name="careful">
<seg>你先要了杯酒，耗子在你身边坐下。</seg>
<seg>耗子: 最近生意不好做啊。</seg>
</branch>
</story>"""

ROUND2_OUTPUT = """<story>
<seg>耗子领着你穿过酒吧后厨，推开一扇标着"员工通道"的门。</seg>
<seg>门后是一条狭窄的走廊，荧光灯管嗡嗡作响。</seg>
<seg>耗子: 芯片在安全屋里。不过去之前——我们得谈谈价。</seg>
<choice id="negotiation">
  <opt key="A" branch="pay">按原价支付</opt>
  <opt key="B" branch="haggle">讨价还价</opt>
</choice>
<set var="信任度" op="+" val="5" if="negotiation==1"/>
<set var="体力" op="-" val="10" if="negotiation==2"/>
<checkpoint node="ch3_ally" summary="与耗子前往安全屋，途中谈判交易价格。">
</checkpoint>
<bridge/>
<branch name="pay">
<seg>你点头同意，耗子咧嘴一笑。</seg>
</branch>
<branch name="haggle">
<seg>你皱起眉头，耗子的义眼红光闪烁了一下。</seg>
</branch>
</story>"""


class TestIntegration:
    def test_full_5_round_conversation_flow(self):
        """Simulate 5 rounds and verify message structure at each step."""
        from storyloom.parser.streaming_parser import StreamingXmlParser

        pb = PromptBuilder()
        cm = ContextManager()

        # Round 1
        r1_prompt = pb.build_round1(
            SAMPLE_STORY, SAMPLE_OUTLINE, "ch2_confrontation", "与耗子完成交易",
            {"体力": 80, "信任度": 10},
        )
        sp1 = StreamingXmlParser()
        for line in ROUND1_OUTPUT.split("\n"):
            sp1.feed_line(line)
        cm.set_round1(r1_prompt, ROUND1_OUTPUT,
                      bridge_text=sp1.get_bridge_text())
        msgs = cm.get_messages()
        assert len(msgs) == 2
        assert cm.round_count == 1
        assert cm.get_compressed_rounds() == []

        # Round 2
        bridge1 = cm.get_last_bridge_text()
        assert len(bridge1) > 0
        r2_prompt = pb.build_round_n(
            outline_text=SAMPLE_OUTLINE,
            current_node="ch3_ally",
            goal="与耗子前往安全屋",
            state_vars={"体力": 80, "信任度": 15},
            variables=SAMPLE_STORY["variables"],
            bridge_text=bridge1,
        )
        sp2 = StreamingXmlParser()
        for line in ROUND2_OUTPUT.split("\n"):
            sp2.feed_line(line)
        cm.add_round(r2_prompt, ROUND2_OUTPUT,
                     bridge_text=sp2.get_bridge_text())
        assert cm.round_count == 2
        assert cm.get_compressed_rounds() == []

        # Round 3
        sp3 = StreamingXmlParser()
        for line in ROUND2_OUTPUT.split("\n"):
            sp3.feed_line(line)
        cm.add_round("r3 context", ROUND2_OUTPUT,
                     bridge_text=sp3.get_bridge_text())
        assert cm.round_count == 3

        # Round 4
        sp4 = StreamingXmlParser()
        for line in ROUND2_OUTPUT.split("\n"):
            sp4.feed_line(line)
        cm.add_round("r4 context", ROUND2_OUTPUT,
                     bridge_text=sp4.get_bridge_text())
        assert cm.round_count == 4
        assert cm.get_compressed_rounds() == []

        # Round 5 — triggers compression
        sp5 = StreamingXmlParser()
        for line in ROUND2_OUTPUT.split("\n"):
            sp5.feed_line(line)
        cm.add_round("r5 context", ROUND2_OUTPUT,
                     bridge_text=sp5.get_bridge_text())
        assert cm.round_count == 5
        compressed = cm.get_compressed_rounds()
        assert len(compressed) >= 1

        msgs = cm.get_messages()
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_context_manager_preserves_round1(self):
        """Round 1 messages should never be removed."""
        pb = PromptBuilder()
        cm = ContextManager()

        r1 = pb.build_round1(
            SAMPLE_STORY, SAMPLE_OUTLINE, "ch2_confrontation", "与耗子交易",
            {"体力": 80, "信任度": 10},
        )
        cm.set_round1(r1, ROUND1_OUTPUT)

        for i in range(2, 10):
            cm.add_round(f"r{i}", ROUND2_OUTPUT)

        msgs = cm.get_messages()
        assert msgs[0]["content"] == r1
        assert "narrative engine" in msgs[0]["content"]
        assert "<story>" in msgs[0]["content"]

    def test_bridge_text_flows_between_rounds(self):
        """Bridge text extracted from round N feeds into round N+1 context."""
        from storyloom.parser.streaming_parser import StreamingXmlParser

        pb = PromptBuilder()
        cm = ContextManager()

        sp = StreamingXmlParser()
        for line in ROUND1_OUTPUT.split("\n"):
            sp.feed_line(line)
        cm.set_round1(
            pb.build_round1(SAMPLE_STORY, SAMPLE_OUTLINE, "ch2", "交易", {"体力": 80, "信任度": 10}),
            ROUND1_OUTPUT,
            bridge_text=sp.get_bridge_text(),
        )

        bridge1 = cm.get_last_bridge_text()
        r2 = pb.build_round_n(
            outline_text=SAMPLE_OUTLINE,
            current_node="ch3",
            goal="前往安全屋",
            state_vars={"体力": 80, "信任度": 15},
            variables=SAMPLE_STORY["variables"],
            bridge_text=bridge1,
        )
        assert "信用棒" in r2 or "耗子" in r2

    def test_compression_format(self):
        """Compressed messages use the correct format."""
        from storyloom.parser.streaming_parser import StreamingXmlParser

        pb = PromptBuilder()
        cm = ContextManager()

        sp = StreamingXmlParser()
        for line in ROUND1_OUTPUT.split("\n"):
            sp.feed_line(line)
        cm.set_round1(
            pb.build_round1(SAMPLE_STORY, SAMPLE_OUTLINE, "ch2", "交易", {"体力": 80, "信任度": 10}),
            ROUND1_OUTPUT,
            bridge_text=sp.get_bridge_text(),
        )

        for i in range(2, 6):
            sp_n = StreamingXmlParser()
            for line in ROUND2_OUTPUT.split("\n"):
                sp_n.feed_line(line)
            cm.add_round(f"r{i}", ROUND2_OUTPUT,
                         bridge_text=sp_n.get_bridge_text())

        msgs = cm.get_messages()
        contents = [m["content"] for m in msgs]
        has_summary = any("Key events so far" in c for c in contents)
        assert has_summary or cm.round_count < 5
