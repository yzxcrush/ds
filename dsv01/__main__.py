# -*- coding: utf-8 -*-
"""`python3 -m dsv01` 入口：等价于 `ds` 驱动。"""

import sys

from .cli import main_ds

if __name__ == "__main__":
    sys.exit(main_ds(sys.argv[1:]))
