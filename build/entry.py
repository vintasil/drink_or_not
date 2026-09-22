"""PyInstaller 的入口脚本。

不能直接把 `src/drink_or_not/__main__.py` 交给 PyInstaller —— 它会把这个文件当成顶层
脚本 `__main__` 来执行,里面的 `from .config import ...` 就找不到父包了,冻结后一启动
就 `ImportError: attempted relative import with no known parent package`。

更麻烦的是模块分析也一起废掉:相对导入解析不出来,整个 `drink_or_not` 包都不会被打进
包体(连带 PIL 这些只有包内才引用的依赖也一起漏掉),产出的 exe 看着挺大,实际一跑就崩。

这里用绝对导入做个薄壳,包本身仍按常规方式收集。
"""

import sys

from drink_or_not.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
