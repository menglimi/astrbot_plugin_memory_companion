"""面板联动状态不许虚标「已安装」。

原缺陷：`companionStatus()` 用 `caps.available === true` 判定「陪伴插件已装」，
而那个字段的含义是**记忆侧自己的 contract 自检通过**——它恒为 true，跟
`astrbot_plugin_private_companion` 装没装毫无关系。于是根本没装陪伴插件的宿主上，
面板照样显示「已连接」「插件加载：-」。

这里做两层守护：

1. 静态断言：app.js 必须读 `companion_installed`，且不得再拿 `caps.available`
   当装没装的依据。
2. 行为断言：把 app.js 里那段**真实代码**截出来交给 node 跑，逐个输入验证
   「没装 / 装了但没活性 / 真装了」三种情况下的 `available`。
   只做静态断言不够——写死 `false` 也能骗过 grep。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL_SCRIPT = ROOT / "pages" / "记忆面板" / "app.js"

# 截取 app.js 里「原因码表 + 健康度文案 + companionStatus」这一段真实代码。
# 起点用常量名、终点用函数名，都不写行号：上面的注释块怎么改都不影响这里。
DRIVER = r"""
const raw = require("fs").readFileSync(process.argv[2], "utf8").replace(/\r\n/g, "\n");
const start = raw.indexOf("const REASON_TEXT = {");
const end = raw.indexOf("\n}\n", raw.indexOf("function companionStatus(")) + 3;
if (start < 0 || end < 3) {
  console.error("SLICE_MISSING");
  process.exit(2);
}
const compact = (v) => (v == null ? "" : String(v).trim().slice(0, 200));
const load = new Function(
  "compact",
  raw.slice(start, end) + "\nreturn { companionStatus, healthText };",
);
const { companionStatus, healthText } = load(compact);

const cases = [
  // 旧后端只给 available=true，没有 companion_installed —— 也必须报「未装」
  ["caps-only-available", { available: true, state: "available" }, { available: false }, false, false],
  ["not-installed", { available: true, companion_installed: false }, { available: false }, false, false],
  ["installed-inactive", { available: true, companion_installed: true }, { available: false }, true, false],
  [
    "installed-active",
    { available: true, companion_installed: true, companion_plugin_name: "astrbot_plugin_private_companion" },
    { available: true, daily_plan_enabled: true, detail_enabled: true },
    true,
    true,
  ],
];

const out = [];
let bad = 0;
for (const [name, caps, personal, wantInstalled, wantAvailable] of cases) {
  const s = companionStatus(caps, personal);
  const ok = s.installed === wantInstalled && s.available === wantAvailable;
  if (!ok) bad += 1;
  out.push({ name, ok, installed: s.installed, available: s.available, reason: s.reason });
}
out.push({ health: healthText("ready"), degraded: healthText("degraded"), unknown: healthText("") });
console.log(JSON.stringify({ bad, out }));
process.exit(bad ? 1 : 0);
"""


class CompanionLinkageHonestyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = PANEL_SCRIPT.read_text(encoding="utf-8")

    def test_installed_flag_comes_from_a_real_presence_field(self) -> None:
        self.assertIn(
            "caps.companion_installed === true",
            self.source,
            "面板必须用后端真实探测出来的 companion_installed 判定装没装",
        )
        self.assertNotIn(
            "available: caps.available === true",
            self.source,
            "caps.available 是「记忆侧 contract 自检通过」，不能当「已安装」用",
        )

    def test_internal_reason_codes_are_not_shown_raw(self) -> None:
        """内部原因码是给日志看的，面板必须翻译过再显示。"""
        self.assertNotIn(
            "原因码：",
            self.source,
            "「原因码：xxx」直接把内部码甩给用户",
        )
        self.assertIn("companion_api_unavailable", self.source, "缺少原因码对照表")

    @unittest.skipIf(shutil.which("node") is None, "容器/CI 没有 node，跳过行为断言")
    def test_uninstalled_companion_never_reports_connected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            driver = Path(tmp) / "probe.js"
            driver.write_text(DRIVER, encoding="utf-8")
            proc = subprocess.run(
                ["node", str(driver), str(PANEL_SCRIPT)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
        self.assertNotEqual(
            proc.returncode, 2,
            f"没能从 app.js 里截出联动判定那段代码：{proc.stderr.strip()}",
        )
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        for case in payload["out"]:
            if "name" not in case:
                continue
            self.assertTrue(
                case["ok"],
                f"{case['name']}: installed={case['installed']} available={case['available']} "
                f"（reason={case['reason']!r}）",
            )
        self.assertEqual(0, payload["bad"])
        health = payload["out"][-1]
        self.assertEqual("正常", health["health"], "ready 必须翻译成人话")
        self.assertEqual("降级", health["degraded"])
        self.assertEqual("未知", health["unknown"])


if __name__ == "__main__":
    unittest.main()
