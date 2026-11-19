#!/usr/bin/env python3
"""ui/app.html + ui/engine.js -> ui/simulator.html (tek dosya, bagimsiz).

Motorun tek kaynagi engine.js; boylece sayfa ile dogrulama kosusu
(ui/verify.mjs) birbirinden ayrismaz.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

eng = open(os.path.join(HERE, "engine.js")).read()
eng = re.sub(r"^export\s+", "", eng, flags=re.M)
eng = re.sub(r"^export\s*\{[^}]*\};?\s*$", "", eng, flags=re.M)
eng = "const AAG = (function(){\n" + eng + "\nreturn {defaults, simulate, binOf, gainsOf};\n})();"

page = open(os.path.join(HERE, "app.html")).read()
assert "/* ENGINE */" in page
page = page.replace("/* ENGINE */", eng)

out = os.path.join(HERE, "simulator.html")
open(out, "w").write(page)
print(f"{out}  ({len(page)/1024:.1f} KB)")
