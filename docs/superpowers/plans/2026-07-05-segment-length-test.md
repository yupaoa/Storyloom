# Segment Length TTFT Impact Test — Implementation Plan

> **面向 AI 代理的工作者：** 推荐使用 subagent-driven-development 逐任务实现。步骤使用复选框语法跟踪进度。

**目标：** 构建参数化 prompt 生成 + 结果分析工具链，运行 4 档段长测试验证 TTFT 假设。

**架构：** 模板渲染 (`generate_prompt.py`) → 现有测试框架 (`run_prompt_test.py`) → 聚合分析 (`analyze_seg_test.py`)。YAML 驱动参数矩阵，JSON manifest 桥接两个脚本。

**技术栈：** Python 3 (stdlib: yaml, json, xml.etree, re, pathlib), DeepSeek API

---

### 任务 1：创建 prompt 模板

**文件：**
- 创建：`tests/data/prompts/round1-en.tmpl`

- [ ] **步骤 1：从 round1-en.txt 复制并替换段数相关内容为占位符**

关键替换（4 处）：
- `60-120` → `{{MIN_SEG}}-{{MAX_SEG}}`（行 122）
- `between segment 30 and 60` → `between segment {{BRIDGE_MIN}} and {{BRIDGE_MAX}}`（行 123）
- 参考示例行：`40 interaction + 40 tail = 80` → `{{REF_SINGLE}} interaction + {{REF_SINGLE}} tail = {{REF_TOTAL}}`（行 163）
- 参考示例行：`40 interaction + 20 per branch = 80` → `{{REF_SINGLE}} interaction + {{REF_HALF}} per branch = {{REF_TOTAL}}`（行 163）

- [ ] **步骤 2：验证模板中占位符数量**

```bash
grep -c '{{' tests/data/prompts/round1-en.tmpl
# Expected: 12 (6 placeholders × 2 occurrences each; MIN_SEG/MAX_SEG appear 2×, BRIDGE_MIN/MAX appear 1× each = actually let's just verify)
```

- [ ] **步骤 3：Commit**

```bash
git add tests/data/prompts/round1-en.tmpl
git commit -m "feat: add parameterized segment-count prompt template"
```

---

### 任务 2：创建参数配置文件

**文件：**
- 创建：`tests/data/prompts/seg-test-config.yaml`

- [ ] **步骤 1：编写 YAML 配置**

```yaml
template: tests/data/prompts/round1-en.tmpl
output_dir: tests/data/prompts
manifest: tests/data/prompts/seg-test-manifest.json
tiers:
  - label: t1-60-120
    min_seg: 60
    max_seg: 120
    bridge_min: 30
    bridge_max: 60
    ref_total: 100
    ref_single: 50
    ref_half: 25
  - label: t2-120-200
    min_seg: 120
    max_seg: 200
    bridge_min: 60
    bridge_max: 100
    ref_total: 160
    ref_single: 80
    ref_half: 40
  - label: t3-180-280
    min_seg: 180
    max_seg: 280
    bridge_min: 90
    bridge_max: 140
    ref_total: 240
    ref_single: 120
    ref_half: 60
  - label: t4-240-360
    min_seg: 240
    max_seg: 360
    bridge_min: 120
    bridge_max: 180
    ref_total: 320
    ref_single: 160
    ref_half: 80
```

- [ ] **步骤 2：Commit**

```bash
git add tests/data/prompts/seg-test-config.yaml
git commit -m "feat: add segment test parameter matrix config"
```

---

### 任务 3：实现 generate_prompt.py

**文件：**
- 创建：`tests/generate_prompt.py`

- [ ] **步骤 1：编写生成脚本**

```python
#!/usr/bin/env python3
"""Generate prompt files from template + YAML parameter matrix.

Usage:
  python3 tests/generate_prompt.py [--config tests/data/prompts/seg-test-config.yaml]
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML required: pip install pyyaml")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def render(template: str, params: dict) -> str:
    """Replace {{PLACEHOLDER}} with values from params dict."""
    result = template
    for key, value in params.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate segment-test prompt files from template + config."
    )
    parser.add_argument(
        "--config", type=Path,
        default=PROJECT_ROOT / "tests" / "data" / "prompts" / "seg-test-config.yaml",
        help="Path to YAML config file.",
    )
    args = parser.parse_args()

    config_path = args.config.resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    template_path = PROJECT_ROOT / config["template"]
    template_text = template_path.read_text(encoding="utf-8")

    output_dir = PROJECT_ROOT / config["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {"tiers": [], "config": str(config_path)}

    for tier in config["tiers"]:
        rendered = render(template_text, tier)
        out_name = f"seg-{tier['label']}.txt"
        out_path = output_dir / out_name
        out_path.write_text(rendered, encoding="utf-8")

        # Verify placeholders all replaced
        remaining = [line for line in rendered.splitlines() if "{{" in line]
        if remaining:
            print(f"WARNING: Unreplaced placeholders in {out_name}:")
            for line in remaining:
                print(f"  {line.strip()}")

        entry = {
            "label": tier["label"],
            "file": str(out_path.relative_to(PROJECT_ROOT)),
            "params": tier,
        }
        manifest["tiers"].append(entry)
        print(f"Generated: {out_path.relative_to(PROJECT_ROOT)}")

    manifest_path = PROJECT_ROOT / config["manifest"]
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Manifest: {manifest_path.relative_to(PROJECT_ROOT)}")
    print(f"Done. {len(config['tiers'])} prompt files generated.")


if __name__ == "__main__":
    main()
```

- [ ] **步骤 2：运行验证生成 4 个 prompt 文件**

```bash
python3 tests/generate_prompt.py
```
预期：生成 4 个文件 + manifest，无 unreplaced placeholder 警告。

- [ ] **步骤 3：验证生成的 prompt 文件内容正确**

```bash
# T1 should have original 60-120 values
grep '60-120' tests/data/prompts/seg-t1-60-120.txt
# T4 should have 240-360
grep '240-360' tests/data/prompts/seg-t4-240-360.txt
# No file should have unreplaced placeholders
grep -l '{{' tests/data/prompts/seg-t*.txt
# Expected: no output from the last command
```

- [ ] **步骤 4：Commit**

```bash
git add tests/generate_prompt.py tests/data/prompts/seg-test-manifest.json
git commit -m "feat: add prompt template renderer for segment tests"
```

---

### 任务 4：实现 analyze_seg_test.py

**文件：**
- 创建：`tests/analyze_seg_test.py`

- [ ] **步骤 1：编写分析脚本**

```python
#!/usr/bin/env python3
"""Analyze segment-length test results across multiple tiers.

Usage:
  python3 tests/analyze_seg_test.py [--output-dir tests/data/output/seg-t1-60-120 ...]
  python3 tests/analyze_seg_test.py --all   # auto-discover from manifest
"""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_header(file_path: Path) -> dict:
    """Extract metrics from a result file's YAML-like header."""
    text = file_path.read_text(encoding="utf-8")
    data = {"file": str(file_path.relative_to(PROJECT_ROOT))}

    patterns = {
        "time": r"\*\*Time\*\*:\s*([\d.]+)s",
        "ttft": r"\*\*TTFT\*\*:\s*([\d.]+)s",
        "first_seg": r"\*\*FirstSegment\*\*:\s*([\d.]+)s",
        "finish": r"\*\*Finish\*\*:\s*(\w+)",
        "prompt_tokens": r"prompt=(\d+)",
        "completion_tokens": r"completion=(\d+)",
        "total_tokens": r"total=(\d+)",
    }

    for key, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            val = m.group(1)
            data[key] = float(val) if "." in val else int(val)

    return data


def count_segments(content: str) -> tuple[int, int, int]:
    """Count total segs, pre-bridge segs, post-bridge segs. Returns (total, pre, post)."""
    segs = re.findall(r'<seg n="(\d+)"', content)
    if not segs:
        return 0, 0, 0

    seg_nums = [int(n) for n in segs]
    total = len(seg_nums)
    max_n = max(seg_nums)

    # Find bridge position: the max seg n before bridge marker
    bridge_pos = content.find("<bridge/>")
    if bridge_pos == -1:
        bridge_pos = content.find("<bridge />")
    before_bridge = content[:bridge_pos] if bridge_pos != -1 else content
    pre_segs = re.findall(r'<seg n="(\d+)"', before_bridge)
    pre_count = len(pre_segs)
    post_count = total - pre_count

    return total, pre_count, post_count


def check_correctness(content: str, tier_label: str) -> dict:
    """Run all correctness checks. Returns dict of check_name -> bool/str."""
    checks = {}

    # XML validity
    try:
        ET.fromstring(content.strip())
        checks["xml_valid"] = True
    except ET.ParseError as e:
        checks["xml_valid"] = False
        checks["xml_error"] = str(e)[:100]

    # Bridge count
    bridge_count = content.count("<bridge/>") + content.count("<bridge />")
    checks["bridge_count_1"] = bridge_count == 1

    # Checkpoint count
    cp_count = len(re.findall(r'<checkpoint\b', content))
    checks["checkpoint_le_1"] = cp_count <= 1

    # No interactive elements after bridge
    bridge_idx = max(content.find("<bridge/>"), content.find("<bridge />"))
    if bridge_idx != -1:
        after = content[bridge_idx:]
        checks["no_interactive_after_bridge"] = (
            "<choice" not in after
            and "<set" not in after
            and "<checkpoint" not in after
        )

    # Seg numbering
    seg_nums = [int(n) for n in re.findall(r'<seg n="(\d+)"', content)]
    if seg_nums:
        checks["seg_starts_at_1"] = seg_nums[0] == 1
        checks["seg_continuous"] = seg_nums == list(range(seg_nums[0], seg_nums[-1] + 1))
        checks["seg_no_duplicates"] = len(seg_nums) == len(set(seg_nums))
        total = len(seg_nums)
        checks["seg_count"] = total
    else:
        checks["seg_starts_at_1"] = False
        checks["seg_continuous"] = False
        checks["seg_no_duplicates"] = False
        checks["seg_count"] = 0

    # Markdown fence / external text
    stripped = content.strip()
    checks["no_markdown_fence"] = not (
        stripped.startswith("```") or stripped.endswith("```")
    )

    # Prohibited dialogue: quotation marks
    # Look for dialogue segments with quotes (heuristic)
    dialogue_lines = re.findall(r'<seg n="\d+">(.*?)</seg>', content)
    quote_count = sum(1 for d in dialogue_lines if '"' in d or '"' in d or '"' in d)
    checks["no_quoted_dialogue"] = quote_count == 0

    return checks


def aggregate(tiers_data: dict) -> str:
    """Build summary table from per-tier results."""
    lines = []
    header = (
        f"{'Tier':<16} {'Runs':>4}  {'TTFT(avg)':>9}  {'TTFT(min/max)':>16}  "
        f"{'Segs(avg)':>9}  {'Bridge%':>7}  {'Valid':>5}  {'Correct%':>7}  {'Time(avg)':>9}"
    )
    lines.append(header)
    lines.append("-" * len(header))

    for label in sorted(tiers_data.keys()):
        runs = tiers_data[label]
        n = len(runs)

        ttfts = [r.get("ttft") for r in runs if r.get("ttft")]
        times = [r.get("time") for r in runs if r.get("time")]
        segs = [r.get("checks", {}).get("seg_count", 0) for r in runs]

        ttft_avg = sum(ttfts) / len(ttfts) if ttfts else 0
        ttft_min = min(ttfts) if ttfts else 0
        ttft_max = max(ttfts) if ttfts else 0
        seg_avg = sum(segs) / len(segs) if segs else 0
        time_avg = sum(times) / len(times) if times else 0

        # Bridge % from pre/post if available
        pre_counts = [r.get("pre_segs", 0) for r in runs]
        post_counts = [r.get("post_segs", 0) for r in runs]
        total_pre = sum(pre_counts)
        total_post = sum(post_counts)
        if total_pre + total_post > 0:
            bridge_pct = total_pre / (total_pre + total_post) * 100
        else:
            bridge_pct = 0

        # Valid count
        valid_count = sum(1 for r in runs if r.get("checks", {}).get("xml_valid", False))

        # Correct%: average of all boolean check pass rates (excluding seg_count which is numeric)
        bool_checks = [
            "xml_valid", "bridge_count_1", "checkpoint_le_1",
            "no_interactive_after_bridge", "seg_starts_at_1",
            "seg_continuous", "seg_no_duplicates",
            "no_markdown_fence", "no_quoted_dialogue",
        ]
        correctness_scores = []
        for r in runs:
            c = r.get("checks", {})
            passed = sum(1 for k in bool_checks if c.get(k, False))
            correct_pct = passed / len(bool_checks) * 100
            correctness_scores.append(correct_pct)
        correct_avg = sum(correctness_scores) / len(correctness_scores) if correctness_scores else 0

        ttft_range = f"{ttft_min:.1f} / {ttft_max:.1f}"
        lines.append(
            f"{label:<16} {n:>4}  {ttft_avg:>7.1f}s  {ttft_range:>16}  "
            f"{seg_avg:>7.0f}  {bridge_pct:>5.0f}%  {valid_count:>3}/{n:<3}  {correct_avg:>5.0f}%  {time_avg:>7.1f}s"
        )

    # Constraint check
    lines.append("")
    lines.append("Constraint check (TTFT < N × RATE × t, RATE=0.5, t=0.5s):")
    for label in sorted(tiers_data.keys()):
        runs = tiers_data[label]
        ttfts = [r.get("ttft") for r in runs if r.get("ttft")]
        segs = [r.get("checks", {}).get("seg_count", 0) for r in runs]
        if ttfts and segs:
            # For constraint: bridge_text = seg_avg * 0.5, reading_time = bridge_text * 0.5
            max_ttft = max(ttfts)
            bridge_segs = sum(s for s in segs) / len(segs) * 0.5
            reading_time = bridge_segs * 0.5
            ratio = max_ttft / reading_time if reading_time > 0 else float("inf")
            status = "PASS" if ratio < 1 else "FAIL"
            lines.append(
                f"  {label:<16}: max_TTFT={max_ttft:.1f}s, "
                f"bridge_reading={reading_time:.1f}s, "
                f"ratio={ratio:.2f} → {status}"
            )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze segment-length test results."
    )
    parser.add_argument(
        "dirs", type=Path, nargs="*",
        help="Output directories to analyze.",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Auto-discover test output dirs from manifest.",
    )
    parser.add_argument(
        "--manifest", type=Path,
        default=PROJECT_ROOT / "tests" / "data" / "prompts" / "seg-test-manifest.json",
        help="Path to manifest JSON.",
    )
    args = parser.parse_args()

    dirs = []

    if args.all:
        manifest_path = args.manifest
        if not manifest_path.exists():
            print(f"Manifest not found: {manifest_path}")
            sys.exit(1)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for tier in manifest["tiers"]:
            label = tier["label"]
            output_dir = PROJECT_ROOT / "tests" / "data" / "output" / f"seg-{label}"
            if output_dir.exists():
                dirs.append(output_dir)
            else:
                print(f"SKIP: no output dir for {label} ({output_dir})")
    else:
        dirs = args.dirs

    if not dirs:
        print("No output directories specified. Use --all or pass dirs directly.")
        sys.exit(1)

    tiers_data = defaultdict(list)

    for d in dirs:
        label = d.name.replace("seg-", "")
        for md_file in sorted(d.glob("prompt-test-*.md")):
            result = parse_header(md_file)

            # Extract XML content (everything after --- separator)
            text = md_file.read_text(encoding="utf-8")
            parts = text.split("---\n", 1)
            content = parts[1] if len(parts) > 1 else ""

            if content.strip():
                # Count segments
                total, pre, post = count_segments(content)
                result["total_segs"] = total
                result["pre_segs"] = pre
                result["post_segs"] = post

                # Correctness checks
                result["checks"] = check_correctness(content, label)

            tiers_data[label].append(result)

    print(aggregate(tiers_data))

    # Detailed per-run breakdown
    print("\n" + "=" * 60)
    print("Per-run Detail")
    print("=" * 60)
    for label in sorted(tiers_data.keys()):
        print(f"\n--- {label} ---")
        for r in tiers_data[label]:
            c = r.get("checks", {})
            check_items = []
            for k, v in c.items():
                if isinstance(v, bool):
                    check_items.append(f"{k}={v}")
            print(
                f"  {Path(r['file']).name}: "
                f"TTFT={r.get('ttft', 'N/A')}, "
                f"Segs={c.get('seg_count', 'N/A')}, "
                f"Valid={c.get('xml_valid', 'N/A')}, "
                f"Passed={sum(1 for v in c.values() if v is True)}/{len([v for v in c.values() if isinstance(v, bool)])}"
            )


if __name__ == "__main__":
    main()
```

- [ ] **步骤 2：验证脚本可导入**

```bash
python3 -c "import tests.analyze_seg_test; print('OK')" 2>&1 || \
python3 -c "import sys; sys.path.insert(0, '.'); exec(open('tests/analyze_seg_test.py').read()); print('OK')"
```

- [ ] **步骤 3：Commit**

```bash
git add tests/analyze_seg_test.py
git commit -m "feat: add segment test results analyzer"
```

---

### 任务 5：运行生成 + 测试

**前置：** 任务 1-4 完成。

- [ ] **步骤 1：生成 4 个 prompt 文件**

```bash
python3 tests/generate_prompt.py
```

- [ ] **步骤 2：运行 T1 (对照) 3 次**

```bash
python3 tests/run_prompt_test.py --prompt tests/data/prompts/seg-t1-60-120.txt --runs 3
```

- [ ] **步骤 3：运行 T2 3 次**

```bash
python3 tests/run_prompt_test.py --prompt tests/data/prompts/seg-t2-120-200.txt --runs 3
```

- [ ] **步骤 4：运行 T3 3 次**

```bash
python3 tests/run_prompt_test.py --prompt tests/data/prompts/seg-t3-180-280.txt --runs 3
```

- [ ] **步骤 5：运行 T4 3 次**

```bash
python3 tests/run_prompt_test.py --prompt tests/data/prompts/seg-t4-240-360.txt --runs 3
```

- [ ] **步骤 6：Commit 测试结果**

```bash
git add tests/data/output/ tests/data/prompts/seg-*.txt
git commit -m "test: add segment-length TTFT test results (4 tiers × 3 runs)"
```

---

### 任务 6：分析并报告

- [ ] **步骤 1：运行分析脚本**

```bash
python3 tests/analyze_seg_test.py --all
```

- [ ] **步骤 2：解读结果**

对照约束公式 `TTFT < N × RATE × t`（RATE=0.5, t=0.5s）判断各档位是否通过。观察 TTFT 随段数增长曲线，确认拐点。

- [ ] **步骤 3：输出结论**

基于数据确定 Phase 1 最优 N 范围，为 Phase 2 RATE 测试提供输入。
