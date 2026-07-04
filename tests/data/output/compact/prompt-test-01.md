# Test 01

- **Time**: 97.4s
- **Model**: deepseek-v4-pro
- **Finish**: stop
- **Tokens**: prompt=1926, completion=6109, total=8035
- **Timestamp**: 2026-07-04T07:17:04.375698+00:00

---

--- narrative:main ---
1. 耗子掏出来的是一片指甲盖大小的金属片，在霓虹灯的余光里泛着幽蓝的冷光。
2. 他把它放在吧台上，用两根手指按住。
3. 耗子: 先看货。
4. 你从内衬口袋里摸出转账芯片，同样放在台面上。
5. 林焰: 信用点，一分不少。
6. 两张芯片在吧台的裂痕间遥遥相对，中间隔着半瓶没喝完的劣质烧酒。
7. 耗子的义眼红光快速闪动，扫描着你的转账芯片。
8. 耗子: 算你识相。
9. 他松开了按住数据芯片的手指。
10. 你伸手去拿——
11. 突然，酒吧的灯光全部熄灭。
12. 只剩下地面应急灯带投出的猩红微光。
13. 耗子: 操。
14. 你本能地一把将数据芯片攥进手心，另一只手摸向腰间的脉冲手枪。
15. 黑暗中传来玻璃碎裂的脆响，紧跟着是密集而整齐的脚步声。
16. 耗子压低身子，声音里带着抑制不住的颤抖。
17. 耗子: 是荒坂的人。
18. 应急灯闪烁两下，映出门口迅速展开的三个黑色人影，臂甲上的企业标志反射着冷光。
19. 林焰: 你他妈怎么惹来的？
20. 耗子: 我他妈怎么知道！
21. 天花板角落的扬声器发出一声刺耳的电噪，然后是合成音，语调不带一丝起伏。
22. 合成音: 林焰先生，请放弃抵抗。
23. 合成音: 交出芯片，你可以活着离开。
24. 耗子咬牙盯着你，仅剩的肉眼里满是恐惧和不确定。
25. 耗子: 他们没提我。
26. 他的手已经摸向藏在吧台下方的霰弹枪。

--- options:main ---
choice: confrontation
A. 掩护耗子，一起从后门杀出去 -> stick_with_rat
B. 趁乱独自携带芯片逃离 -> abandon_rat
C. 拖延时间，悄悄激活神经接口过载 -> stall

--- state:main ---
if confrontation == 1 -> @var 信任度 +20
if confrontation == 1 -> @var 体力 -15
if confrontation == 2 -> @var 信任度 -30
if confrontation == 2 -> @var 体力 -5
if confrontation == 2 -> @var 芯片完整度 -10
if confrontation == 3 -> @var 理智值 -15
if confrontation == 3 -> @var 体力 -10
if confrontation == 3 -> @var 信任度 +10

--- checkpoint ---
node ch2_confrontation_end
summary: 荒坂突袭酒吧，林焰在绝境中选择了下一步的行动方向。
if confrontation == 1 -> route ch3_ally_start
if confrontation == 2 -> route ch3_betrayal_start
if confrontation == 3 -> route ch3_ally_start

--- bridge ---

--- narrative:stick_with_rat ---
27. 你伸手抓住耗子的后领，把他往吧台后面拖。
28. 林焰: 别他妈死在这儿。
29. 耗子感激地看了你一眼，抄起霰弹枪对准门口轰出一发。
30. 枪口的火焰瞬间照亮了黑暗，掩护你们二人在硝烟中撞开后门。

--- narrative:abandon_rat ---
31. 你毫不犹豫地抓起芯片，翻过吧台朝侧窗方向冲去。
32. 身后耗子的咒骂声被脉冲步枪的射击声淹没。
33. 你没回头，用肩膀撞开防火窗，跌进了满是垃圾的后巷。

--- narrative:stall ---
34. 你举起双手，示意没有武器，同时神经接口悄悄开始过载预热。
35. 太阳穴传来熟悉的刺痛感，周围的电子设备开始发出细微的噼啪声。