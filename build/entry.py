"""PyInstaller 专用的入口。

不能把 src/drink_or_not/__main__.py 直接交给 PyInstaller 当入口脚本:那样它是以**顶层
脚本**的身份被执行的(PyInstaller 6 之前叫 runpy 语义,之后是把脚本编进 PYZ 再 exec),
没有父包,`__package__` 是空的,里面 `from .config import ...` 这类相对导入会直接

    ImportError: attempted relative import with no known parent package

绕一层就好了 —— 用绝对导入把包里的 main() 拉起来,模块的包上下文是完整的。
打包走这个文件,开发时照旧 `python -m drink_or_not`。
"""

import sys

from drink_or_not.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
