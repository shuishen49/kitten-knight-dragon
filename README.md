# 猫骑士屠龙 · Kitten Knight vs Dragon（Three.js 3D 游戏）

穿银甲、戴粉蝴蝶结的小奶猫骑士，对决雾原草原上胸口燃着火核的黑龙伊格尼斯。
按原片（LibTV《小猫屠龙》）逐帧还原：阴天浓雾、绿色草原、猫身边漂浮金色星火，圣剑第三连斩爆发圣光。

**在线玩**：https://sparkbazaar.cn/kitten-knight-dragon/ （星火集市）
**看龙的全部动作**：https://sparkbazaar.cn/kitten-knight-dragon/dragon-actions.html （9 个动作一键切换、可拖动旋转）

## 角色模型（真模型 + 程序化绑骨，不是几何拼装）

- **猫骑士**：混元 3D 多视图模型（右爪圣剑 + 左爪金纹圆盾）。`models/rig.py` 在 GLB 里程序化绑骨 20 根，烘焙待机/走路/劈砍/翻滚/跳跃/格挡等片段，游戏内 AnimationMixer 驱动；加载失败依次回退静态模型、几何猫。
- **雾原黑龙**：混元 3D 多视图模型（深灰黑鳞甲、王冠角、背刺排、铲形尾尖、胸口火核贴图发光）。`models/dragon_rig.py` 程序化绑骨 24 根，烘焙 9 个片段：待机 / 扇翼 / 吐息 / 撕咬 / 爪击 / 尾扫 / 咆哮 / 受击 / 死亡；头、嘴、火核锚点挂在骨骼上，火焰从真嘴里喷；加载失败回退几何龙。

## 运行

- **单文件版**：双击 `index-share.html` 即可（约 9.6 MB，猫/龙模型、BGM、草地贴图、主视觉海报全部内嵌；需要联网加载 Three.js CDN）。
- **项目版**：`index.html` 与 `models/` 目录一起放在静态服务器上（星火集市线上就是这份）；本地可 `python3 -m http.server 8901` 后打开 localhost:8901。
- 改代码请改 `index.template.html`，再跑 `python3 build.py` 重新生成 `index.html` / `index-share.html` / `dragon-actions.html`。

## 玩法

| 操作 | 按键 |
|---|---|
| 移动 | W / A / S / D（方向键 ↑↓←→ 也可以） |
| 疾跑 | Shift |
| 挥剑（三连斩，第 3 剑圣光爆发，打头暴击） | J 或鼠标左键 |
| 举盾格挡（减伤 82%，耗体力） | K 按住 或 鼠标右键按住 |
| 翻滚闪避（无敌帧） | 空格 |
| 跳跃 | L |
| BGM 开关 | 左上角按钮（首次按键/点击后播放） |

移动端有 ⚔️ / 🛡️ / 💨 / 🦘 触屏按钮。

## 恶龙 AI（雾原黑龙 · 伊格尼斯，1000 HP）

火焰吐息（判定从龙嘴算，胸口火核变亮即预警）/ 撕咬 / 利爪横扫（贴身触发）/ 尾扫 / 咆哮 / 升空俯冲，
血量 70% / 38% 后进入狂怒与垂死狂暴阶段。

## 素材（assets/）

- `bgm.mp3`：从用户提供的原片视频提取的原音轨（27 秒，循环播放，
  已 base64 内嵌进 index.html）
- `cat-knight-sheet.webp` / `dragon-sheet.webp`：按原片抽帧生成的角色设定图，
  猫与龙的多视图建模参考（见 `multiview/`、`dragon-multiview/`）
- `key-visual.webp`：主视觉海报（结算画面背景）
- `grass.jpg`：生图生成的草地纹理（已内嵌）

## 技术

Three.js 0.160（CDN importmap）；GLB 程序化骨骼绑定 + AnimationMixer 状态机；
浓雾 FogExp2、阴天漫射光、实例化草丛、粒子（喷火/火花/金色星火）、
顿帧、屏幕震动、伤害飘字、连斩系统；
音效（挥剑/格挡/龙吼/喷火）为 Web Audio 合成，BGM 为原片音轨。
