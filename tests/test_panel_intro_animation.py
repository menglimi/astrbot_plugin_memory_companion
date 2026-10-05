"""开场动画的行为守护（无渲染器验证）。

三个必须成立的性质，少一个这个动画就是有害的：

1. **不吃点击** —— `.intro` 的 `pointer-events` 恒为 none。带 `position:fixed; inset:0`
   的遮罩一旦吃了事件，面板在动画期间就是死的，用户会以为面板卡了。
2. **不靠 JS 收尾** —— 最后一帧 keyframe 自带 `visibility:hidden`。JS 报错、
   被 CSP 拦掉、或者标签页在后台被冻结导致 animationend 不触发，遮罩都得自己消失。
3. **尊重减少动效** —— `prefers-reduced-motion: reduce` 时不播，CSS 直接 `display:none`。

第 3 条与「每会话只播一次」一起用真实的内联脚本 + 最小 DOM 桩在 node 里跑，
验证的是 HTML 里那段脚本本身，不是我们的复述。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "pages" / "记忆面板"
LEGACY_HTML = PANEL / "legacy.html"
APP_CSS = PANEL / "app.css"
INTRO_TITLE = "我会牢牢记住你"

# 只取 class="intro" 那一段里的内联脚本（收尾逻辑），不连 theme 引导脚本一起跑。
DRIVER = r"""
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");

// 抽出带 intro 标记的那段 <script>…</script>
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
const code = scripts.find((s) => s.includes("memory_companion_intro_shown"));
if (!code) { console.error("NO_INTRO_SCRIPT"); process.exit(2); }

function run({ reduceMotion, alreadyShown, fireAnimationEnd, advanceToTimeout }) {
  const listeners = {};
  let timers = [];
  const node = {
    parentNode: {
      removeChild(child) { child.removed = true; this.child = null; },
    },
    removed: false,
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
  };
  const store = alreadyShown ? { getItem: () => "1", setItem() {} } : { getItem: () => null, setItem() {} };
  const sandbox = {
    window: {
      matchMedia: (q) => ({ matches: reduceMotion && String(q).includes("reduce") }),
      setTimeout: (fn) => { timers.push(fn); return timers.length; },
    },
    sessionStorage: store,
    document: { getElementById: (id) => (id === "intro" ? node : null) },
  };
  const names = Object.keys(sandbox);
  const values = names.map((n) => sandbox[n]);
  new Function(...names, code)(...values);
  if (fireAnimationEnd) (listeners.animationend || []).forEach((fn) => fn());
  if (advanceToTimeout) timers.forEach((fn) => fn());
  return { removed: node.removed, timerCount: timers.length };
}

const out = {
  normalThenAnimationEnd: run({ fireAnimationEnd: true }),
  normalNoEvent: run({}),
  normalTimeoutFallback: run({ advanceToTimeout: true }),
  reduceMotion: run({ reduceMotion: true }),
  alreadyShownThisSession: run({ alreadyShown: true }),
};
console.log(JSON.stringify(out));
"""


class IntroAnimationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = LEGACY_HTML.read_text(encoding="utf-8")
        cls.css = APP_CSS.read_text(encoding="utf-8")

    def test_title_is_given_immediately_on_first_screen(self) -> None:
        self.assertIn(f'class="intro-title">{INTRO_TITLE}<', self.html)
        # 标题必须在遮罩里、且遮罩在 <body> 起始处，才能抢到首帧
        body_at = self.html.index("<body>")
        intro_at = self.html.index('class="intro"')
        self.assertLess(body_at, intro_at, "开场遮罩必须紧跟 <body>，否则会闪一下面板")

    def test_overlay_never_swallows_clicks(self) -> None:
        block = re.search(r"\.intro \{[^}]*\}", self.css)
        self.assertIsNotNone(block, "找不到 .intro 规则")
        self.assertIn("pointer-events: none", block.group(0))

    def test_overlay_hides_itself_without_javascript(self) -> None:
        veil = re.search(r"@keyframes intro-veil \{([\s\S]*?)\n\}", self.css)
        self.assertIsNotNone(veil, "找不到 intro-veil 关键帧")
        self.assertIn("visibility: hidden", veil.group(1), "最后一帧必须自己隐藏遮罩")
        # forwards 是关键：没有它，动画结束后会回到初始帧（不透明），遮罩就永远留在屏幕上
        rule = re.search(r"\.intro \{[^}]*\}", self.css).group(0)
        self.assertRegex(rule, r"animation:\s*intro-veil[^;]*\bforwards\b")

    def test_reduced_motion_skips_the_intro(self) -> None:
        block = re.search(r"@media \(prefers-reduced-motion: reduce\) \{([^}]*\.intro[^}]*)\}", self.css)
        self.assertIsNotNone(block, "缺少 prefers-reduced-motion 分支")
        self.assertIn("display: none", block.group(1))

    def test_css_defines_every_keyframe_it_uses(self) -> None:
        used = set(re.findall(r"animation:\s*(intro-[a-z]+)", self.css))
        defined = set(re.findall(r"@keyframes\s+(intro-[a-z]+)", self.css))
        self.assertTrue(used, "开场动画没有被 CSS 引用，规则可能写错了位置")
        self.assertEqual(set(), used - defined, "引用了不存在的关键帧")

    def test_title_has_a_solid_colour_fallback(self) -> None:
        """渐变扫描光只能锦上添花，不能把标题本身押在特性支持上。

        `-webkit-text-fill-color: transparent` 一旦遇上不支持 background-clip:text
        的浏览器，整个标题就消失了——而这是用户点名要第一眼看到的字。
        """
        base = re.search(r"\.intro-title \{[^}]*\}", self.css)
        self.assertIsNotNone(base)
        self.assertIn("color: var(--text)", base.group(0), "标题必须有实色兜底")
        self.assertNotIn("-webkit-text-fill-color", base.group(0))
        guarded = re.search(r"@supports[^}]*\{\s*\.intro-title \{[^}]*\}", self.css)
        self.assertIsNotNone(guarded, "扫描光必须包在 @supports 里")
        self.assertIn("-webkit-text-fill-color: transparent", guarded.group(0))

    @unittest.skipIf(shutil.which("node") is None, "容器/CI 没有 node，跳过行为断言")
    def test_intro_script_cleans_up_and_respects_session_and_motion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            driver = Path(tmp) / "probe.js"
            driver.write_text(DRIVER, encoding="utf-8")
            proc = subprocess.run(
                ["node", str(driver), str(LEGACY_HTML)],
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertNotEqual(proc.returncode, 2, f"没找到开场脚本：{proc.stderr.strip()}")
        import json

        out = json.loads(proc.stdout.strip().splitlines()[-1])

        self.assertTrue(out["normalThenAnimationEnd"]["removed"], "动画结束必须摘掉节点")
        self.assertEqual(
            1, out["normalThenAnimationEnd"]["timerCount"],
            "收尾监听与超时兜底各注册一次，说明兜底确实在",
        )
        self.assertTrue(
            out["normalTimeoutFallback"]["removed"],
            "animationend 没来时（后台标签页被冻结），超时兜底必须把节点摘掉",
        )
        self.assertFalse(
            out["reduceMotion"]["removed"],
            "减少动效时脚本应直接返回，遮罩交给 CSS 的 display:none 处理",
        )
        self.assertEqual(
            0, out["reduceMotion"]["timerCount"],
            "减少动效时不该再挂定时器",
        )
        self.assertFalse(
            out["alreadyShownThisSession"]["removed"],
            "本会话已经播过就不该再摘一次（说明它提前返回了）",
        )


if __name__ == "__main__":
    unittest.main()
