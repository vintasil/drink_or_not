"""端到端冒烟:在隔离的配置目录里起真实 Application,驱动 scheduler 走完各判定分支。

空闲值用假的 —— 本机真实 idle 会被用户当下的键鼠输入随时清零,拿它做时序断言必然
flaky。真实 IdleDetector 的正确性由 `--debug-idle` 和 `script/check_env.py` 单独覆盖,
这里只验证 调度器 → 判定 → 记录 → 托盘统计 这条链路的接线。

    uv run python script/e2e_test.py
"""

import json
import logging
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="drink_e2e_")
if sys.platform == "darwin":
    # macOS 忽略 XDG_CONFIG_HOME,config_dir() 看的是 ~/Library/Application Support
    os.environ["HOME"] = TMP
else:
    os.environ["XDG_CONFIG_HOME"] = TMP
if sys.platform.startswith("linux"):
    # 只有 X11/XWayland 需要钉死 xcb;macOS 上必须让 Qt 自己选 cocoa
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-7s %(name)s: %(message)s",
    stream=sys.stderr,
)

from PyQt5.QtCore import QTimer  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from drink_or_not import config as config_mod  # noqa: E402
from drink_or_not import tracker  # noqa: E402
from drink_or_not.app import Application  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)

failures = []


def check(ok, label, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (f"   [{detail}]" if detail else ""))
    if not ok:
        failures.append(label)


cfg = config_mod.load()
check(config_mod.config_path().exists(), "首次运行生成 config.json", str(config_mod.config_path()))

app = Application(qapp, cfg)

# ---- 假空闲时钟:每 250ms 前进 0.25s;"晃鼠标"则清零 ----
state = {"idle": 0.0, "moving": False}
app.detector._query = lambda: state["idle"]


def tick():
    state["idle"] = 0.0 if state["moving"] else state["idle"] + 0.25


clock = QTimer()
clock.setInterval(250)
clock.timeout.connect(tick)
clock.start()

app.pet.show()

phases = []


def run(name):
    def deco(fn):
        phases.append((name, fn))
        return fn

    return deco


@run("喝水:提醒后静止 3s → completed")
def p1():
    cfg["reminders"]["water"]["idle_threshold_sec"] = 3
    cfg["reminders"]["water"]["window_sec"] = 60
    state["idle"] = 0.0
    app.scheduler.trigger("water", dry_run=False)
    check(app.judge.watching == "water", "触发后进入观察", str(app.judge.watching))


@run("上厕所:阈值 99999s → 窗口到期 missed")
def p2():
    cfg["reminders"]["toilet"]["idle_threshold_sec"] = 99999
    cfg["reminders"]["toilet"]["window_sec"] = 10
    app.scheduler.trigger("toilet", dry_run=False)


@run("喝水:一直晃鼠标 → 窗口到期 missed")
def p3():
    cfg["reminders"]["water"]["idle_threshold_sec"] = 5
    cfg["reminders"]["water"]["window_sec"] = 8
    state["moving"] = True
    app.scheduler.trigger("water", dry_run=False)


@run("喝水:弹出时已静止 100s,基准必须被扣掉")
def p4():
    state["moving"] = False
    state["idle"] = 100.0
    cfg["reminders"]["water"]["idle_threshold_sec"] = 3
    cfg["reminders"]["water"]["window_sec"] = 60
    app.scheduler.trigger("water", dry_run=False)


@run("  2s 后仍未完成(证明没有拿旧 idle 凑数)")
def p4b():
    # 若拿旧 idle(100s)去凑,这里早就该判完成了。阈值 3s,此时只新攒了 2s。
    check(app.judge.watching == "water", "2s 时仍在观察", str(app.judge.watching))


@run("汇总与落盘")
def p5():
    summary = tracker.today_summary()
    print("  今日统计:", json.dumps(summary, ensure_ascii=False))
    print("  托盘那行:", tracker.format_summary(summary))

    water, toilet = summary.get("water", {}), summary.get("toilet", {})
    check(water.get("fired") == 3, "water fired=3", str(water))
    check(water.get("completed") == 2, "water completed=2(3s 那次 + 扣基准那次)", str(water))
    check(water.get("missed") == 1, "water missed=1(一直晃鼠标那次)", str(water))
    check(toilet.get("fired") == 1, "toilet fired=1", str(toilet))
    check(toilet.get("missed") == 1, "toilet missed=1", str(toilet))

    entries = []
    with config_mod.records_path().open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                entries.append(json.loads(line))
    print(f"  records.jsonl 共 {len(entries)} 行:")
    for entry in entries:
        print("    ", json.dumps(entry, ensure_ascii=False))

    check(len(entries) == 8, "8 行 = 4 fired + 4 judged", str(len(entries)))
    check(
        all(e.get("item") != "startup" for e in entries),
        "dry_run 的启动语没写盘",
    )
    check(
        sum(1 for e in entries if e["event"] == "judged" and e["outcome"] == "completed") == 2,
        "judged completed 恰好 2 条",
    )


def advance(index=0):
    if index >= len(phases):
        finish()
        return
    name, fn = phases[index]
    print(f"\n[{index + 1}/{len(phases)}] {name}")
    fn()
    QTimer.singleShot(DELAYS[index], lambda: advance(index + 1))


# 每一步的等待时长,都得比"预期完成时刻"再宽 3 秒以上。判定是每秒轮询一次的,而下一
# 阶段一触发就会 cancel() 掉还在观察的那一轮 —— 余量卡在 1 秒左右时,完成时刻正好落在
# 下一次轮询上,于是随机地"还没判完就被下一轮顶掉",表现为 completion 凭空少一条。
DELAYS = [7000, 14000, 12000, 2000, 7000, 4000]


def finish():
    print()
    if failures:
        print(f"失败 {len(failures)} 项: {failures}")
        qapp.exit(1)
    else:
        print("全部通过")
        qapp.exit(0)


QTimer.singleShot(300, advance)
QTimer.singleShot(60000, lambda: (print("超时"), qapp.exit(2)))

sys.exit(qapp.exec_())
