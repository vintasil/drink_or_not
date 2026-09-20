"""环境自检的薄壳。逻辑本体在 drink_or_not/selfcheck.py —— 打包产物跑的是同一份。

    uv run python script/check_env.py [--hold]     源码树里
    drink-or-not --self-check [--hold]             打包产物里,同样的检查

这个壳只干两件事:把 src/ 挂上 sys.path,以及在 Qt 导入之前调 prepare_platform()
(__main__ 里那份,XWayland 的强制走 xcb 必须早于 QApplication 构造)。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from drink_or_not.__main__ import prepare_platform  # noqa: E402

notes = prepare_platform()

from drink_or_not.selfcheck import main as selfcheck_main  # noqa: E402

if __name__ == "__main__":
    sys.exit(selfcheck_main(notes, "--hold" in sys.argv))
