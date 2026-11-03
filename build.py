#!/usr/bin/env python3
"""组装游戏文件：index.template.html + base64 素材 -> index.html（项目版）/ index-share.html（单文件版）
同时把 .b64 素材还原为二进制原文件（assets/bgm.mp3、assets/grass.jpg、assets/poster.jpg、models/cat.glb）。
用法：python3 build.py"""
import base64, pathlib
root = pathlib.Path(__file__).parent

def b64(name): return (root / name).read_text().strip()

t = (root / 'index.template.html').read_text()
t = t.replace('%%BGM_B64%%', b64('assets/bgm.b64'))
t = t.replace('%%GRASS_B64%%', b64('assets/grass.b64'))
t = t.replace('%%POSTER_B64%%', b64('assets/poster.b64'))
(root / 'index.html').write_text(t.replace('%%CAT_B64%%', '').replace('%%DRAGON_B64%%', ''))
(root / 'index-share.html').write_text(t.replace('%%CAT_B64%%', b64('models/cat-anim.b64')).replace('%%DRAGON_B64%%', b64('models/dragon-anim.b64')))
at = (root / 'dragon-actions.template.html').read_text()
(root / 'dragon-actions.html').write_text(at.replace('%%DRAGON_B64%%', b64('models/dragon-anim.b64')))
for src, dst in [('assets/bgm.b64', 'assets/bgm.mp3'), ('assets/grass.b64', 'assets/grass.jpg'),
                 ('assets/poster.b64', 'assets/poster.jpg'), ('models/cat.b64', 'models/cat.glb'),
                 ('models/cat-anim.b64', 'models/cat-anim.glb'), ('models/dragon-anim.b64', 'models/dragon-anim.glb')]:
    (root / dst).write_bytes(base64.b64decode(b64(src)))
print('build OK: index.html / index-share.html / 素材二进制已还原')
