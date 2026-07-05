# Test 01

- **Time**: 59.7s
- **Model**: deepseek-v4-pro
- **Finish**: stop
- **TTFT**: 48.8s
- **FirstSegment**: N/A
- **Tokens**: prompt=3327, completion=3899, total=7226
- **Timestamp**: 2026-07-04T14:37:00.555929+00:00

---
<story>
<seg n="1">耗子的手指在内袋里摸索了片刻。</seg>
<seg n="2">金属碰撞的细微声响在潮湿的空气中格外清晰。</seg>
<seg n="3">他掏出来的不是武器，而是一个巴掌大的钛合金盒。</seg>
<seg n="4">盒盖弹开，蓝色冷光从缝隙中泄出。</seg>
<seg n="5">里面的生物芯片静静地躺着，像一片凝固的闪电。</seg>
<seg n="6">耗子: 你要的东西。</seg>
<seg n="7">他把盒子推到两人之间摇摇欲坠的塑料板条箱上。</seg>
<seg n="8">但他的手没有离开盒子边缘。</seg>
<seg n="9">耗子的义眼扫过你的神经接口。</seg>
<seg n="10">耗子: 不过，我得加价。</seg>
<seg n="11">远处传来废弃通风管道里老鼠的窸窣声。</seg>
<seg n="12">你的指尖触到了腰间的脉冲手枪。</seg>
<seg n="13">林焰: 说。</seg>
<seg n="14">耗子舔了舔干裂的嘴唇。</seg>
<seg n="15">耗子: 除了尾款，我还要你帮我抹掉荒坂数据库里的一条记录。</seg>
<seg n="16">他眨了眨那只完好的右眼。</seg>
<seg n="17">耗子: 你以前的权限应该还能用……对吧？</seg>
<seg n="18">站台尽头传来列车隧道里的风声，像是某种警告。</seg>
<seg n="19">你的神经接口隐隐发烫。</seg>
<seg n="20">这条额外的要求，可能会让整个交易变成陷阱。</seg>
<seg n="21">但你太需要这枚芯片了。</seg>
<choice id="deal">
  <opt key="A" branch="trust">答应耗子，但留个心眼</opt>
  <opt key="B" branch="seize">拒绝加价，准备硬抢</opt>
</choice>
<set var="信任度" op="+" val="15" if="deal==1"/>
<set var="信任度" op="-" val="20" if="deal==2"/>
<set var="理智值" op="-" val="5" if="deal==2"/>
<checkpoint node="ch2_confrontation" summary="在废弃站台与耗子交易芯片，选择答应额外要求或准备抢夺。">
  <route if="deal==1" target="ch3_ally"/>
  <route if="deal==2" target="ch3_betrayal"/>
</checkpoint>
<bridge/>
<branch name="trust">
<seg n="22">你松开按在枪柄上的手指。</seg>
<seg n="23">林焰: 成交。</seg>
<seg n="24">耗子紧绷的肩膀放松了一寸。</seg>
<seg n="25">他把盒子朝你推近了些。</seg>
<seg n="26">耗子: 先付一半。剩下的，等记录抹掉再说。</seg>
<seg n="27">你从内衬口袋取出三张信用水晶片。</seg>
<seg n="28">在昏暗的冷光下，它们折射出霓虹般的微光。</seg>
<seg n="29">耗子接过水晶片，用拇指逐一划过表面。</seg>
<seg n="30">数据流在他的义眼上跳动。</seg>
<seg n="31">耗子: 数目对。</seg>
<seg n="32">他把盒子完全推到你面前。</seg>
<seg n="33">当你正要伸手拿起芯片时，通风管道里突然响起急促的警报声。</seg>
<seg n="34">红色的应急灯开始闪烁。</seg>
<seg n="35">耗子: 荒坂的巡逻队！</seg>
<seg n="36">他飞快地收起水晶片，同时拔出了腰间的等离子匕首。</seg>
<seg n="37">耗子: 跟我来，我知道一条他们没监控的路。</seg>
<seg n="38">你迅速将芯片盒塞进胸口的防干扰袋。</seg>
<seg n="39">两人压低身体，朝废弃的维修通道跑去。</seg>
<seg n="40">身后传来装甲靴踩踏铁梯的沉重回声。</seg>
<seg n="41">通道里霉味刺鼻，墙上涂鸦在红光下仿佛活了过来。</seg>
</branch>
<branch name="seize">
<seg n="42">你的手指在枪柄上收紧。</seg>
<seg n="43">林焰: 没得商量。</seg>
<seg n="44">耗子的义眼红光骤亮。</seg>
<seg n="45">他猛地将盒子往回一抽。</seg>
<seg n="46">但你已经更快——左掌按在盒子上，右手抽枪。</seg>
<seg n="47">耗子: 你他妈——</seg>
<seg n="48">脉冲手枪抵住了他的下巴。</seg>
<seg n="49">盒子在你手中冰凉而沉重。</seg>
<seg n="50">耗子的喉咙里发出低沉的咕噜声。</seg>
<seg n="51">他用左手悄悄按下了腕带上的某个开关。</seg>
<seg n="52">你的神经接口立刻捕捉到一阵高频干扰波。</seg>
<seg n="53">他呼叫了增援。</seg>
<seg n="54">站台尽头传来金属碰撞的声音。</seg>
<seg n="55">至少三名全副武装的佣兵从阴影中现身。</seg>
<seg n="56">耗子: 放下枪，或许还能活着离开。</seg>
<seg n="57">你扣在扳机上的食指没有一丝颤抖。</seg>
<seg n="58">林焰: 试试看。</seg>
<seg n="59">隧道里响起第一声枪响。</seg>
</branch>
</story>