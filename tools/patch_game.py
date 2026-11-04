#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对 index.template.html 打游戏侧补丁：
 1) 一次性动画每帧 fadeIn 的 bug（动作只剩一成力气 -> 攻击软弱无力）
 2) 嘴锚点挂下颌骨（张嘴时喷火口跟着下颚）
 3) 攻击预警：地面范围贴花 + 顶部读条，尺寸与命中判定共用同一组参数
 4) 状态机：sweep 变成真攻击、charge 用专属片段、命中帧对齐片段出招帧
所有锚点都断言唯一命中，任何一条对不上就整体中止（不会打半个补丁）。
"""
import io
import sys

P = 'index.template.html'
RAW = io.open(P, 'rb').read()
NL = '\r\n' if b'\r\n' in RAW else '\n'
s = RAW.decode('utf-8').replace('\r\n', '\n')   # 内部统一用 \n，写回时还原原换行符
APPLIED = []


def rep(old, new, label):
    global s
    c = s.count(old)
    if c != 1:
        print('!! 锚点命中 %d 次（应为 1）: %s' % (c, label))
        print('   --- 锚点开头 ---')
        print(old[:200])
        sys.exit(1)
    s = s.replace(old, new, 1)
    APPLIED.append(label)


# ---------------------------------------------------------------- 1. CSS
rep('@media(pointer:coarse){#touch{display:flex}#controls{display:none}}',
    '''#dTell{position:relative;display:none;margin-top:5px;height:15px;line-height:15px;font-size:12px;letter-spacing:.3em;color:#ffd08a;text-shadow:0 0 12px rgba(0,0,0,.9),0 0 18px currentColor}
#dTell.show{display:block}
#dTell i{position:absolute;left:50%;transform:translateX(-50%);bottom:-3px;height:3px;width:0;border-radius:2px;background:currentColor;box-shadow:0 0 10px currentColor}
#dTell.flash{animation:tellflash .26s 2}
@keyframes tellflash{0%,100%{opacity:1}50%{opacity:.2}}
@media(pointer:coarse){#touch{display:flex}#controls{display:none}}''',
    '1 CSS 预警读条')

# ---------------------------------------------------------------- 2. 读条 DOM
rep('''    <div id="bossPhase"></div>
  </div>''',
    '''    <div id="bossPhase"></div>
    <div id="dTell"><b></b><i></i></div>
  </div>''',
    '2 读条 DOM')

# ---------------------------------------------------------------- 3. dSetAct
rep('''function dSetAct(name, once){
  const a = dActs[name]; if(!a) return;
  if(dCurAct === name && !once) return;
  const prev = dActs[dCurAct];
  a.enabled = true; a.setLoop(once? THREE.LoopOnce : THREE.LoopRepeat); a.clampWhenFinished = !!once; a.fadeIn(.09).play();
  if(prev && prev !== a) prev.fadeOut(.09);
  dCurAct = name;
}''',
    '''function dSetAct(name, once){
  const a = dActs[name]; if(!a) return;
  // 已经在这个动作上就直接返回：旧代码对一次性动作每帧都 fadeIn(.09)，
  // 而 fadeIn 是「从 0 涨到 1」，等于每帧把权重按回 0 —— 一招下来只出力一成，看着就是软绵绵抽一下。
  if(dCurAct === name) return;
  const prev = dActs[dCurAct];
  a.reset(); a.enabled = true; a.setEffectiveWeight(1);
  a.setLoop(once? THREE.LoopOnce : THREE.LoopRepeat); a.clampWhenFinished = !!once;
  a.fadeIn(.12).play();
  if(prev && prev !== a) prev.fadeOut(.12);
  dCurAct = name;
}''',
    '3 dSetAct 一次性动作权重')

# ---------------------------------------------------------------- 4. 嘴锚点挂下颌
rep('''  mouthPos = new THREE.Object3D(); mouthPos.position.set(0, -.045, .075); bones.head.add(mouthPos);
  mouthLight = new THREE.PointLight(0xff4400, 0, 16, 1.6); mouthLight.position.copy(mouthPos.position); bones.head.add(mouthLight);''',
    '''  const jawB = bones.jaw || bones.head; // 有下颌骨就挂下颌：张嘴时喷火口跟着下颚走
  mouthPos = new THREE.Object3D();
  mouthPos.position.set(jawB === bones.jaw? -.01 : 0, jawB === bones.jaw? -.02 : -.045, jawB === bones.jaw? .13 : .075);
  jawB.add(mouthPos);
  mouthLight = new THREE.PointLight(0xff4400, 0, 16, 1.6); mouthLight.position.copy(mouthPos.position); jawB.add(mouthLight);''',
    '4 嘴锚点挂下颌骨')

# ---------------------------------------------------------------- 5. 状态变量
rep("let dragonState='strafe', stateTime=1.2, breathOn=false, flyHeight=0, diveTarget=null, roarDone=false, clawHit=false;",
    "let dragonState='strafe', stateTime=1.2, breathOn=false, flyHeight=0, diveTarget=null, roarDone=false, "
    "clawHit=false, sweepHit=false, biteHit=false, breathFired=false, breathFiring=false, chargeFired=false;",
    '5 状态变量')

# ---------------------------------------------------------------- 6. setDragonState
rep("function setDragonState(s, t){ dragonState=s; stateTime=t; breathOn = (s==='breath'); if(s==='claw') clawHit=false; if(s==='breath') sfxFireBurst(); if(s==='roar'){ sfxRoar(); camShake=Math.max(camShake,.5);} }",
    '''function setDragonState(s, t){
  dragonState=s; stateTime=t; breathOn = (s==='breath'); dPrevState='';
  if(s==='claw') clawHit=false;
  if(s==='sweep') sweepHit=false;
  if(s==='bite') biteHit=false;
  if(s==='charge') chargeFired=false;
  if(s==='breath'){ breathFired=false; breathFiring=false; }
  if(s==='roar'){ sfxRoar(); camShake=Math.max(camShake,.5); }
  if(s==='claw' || s==='sweep') sfxWhoosh();
  tellClear(); tellBegin(s);
}''',
    '6 setDragonState 接预警')

# ---------------------------------------------------------------- 7. 预警模块
rep("function dragonForward(){ return new THREE.Vector3(-Math.sin(dragon.rotation.y), 0, -Math.cos(dragon.rotation.y)); }",
    '''function dragonForward(){ return new THREE.Vector3(-Math.sin(dragon.rotation.y), 0, -Math.cos(dragon.rotation.y)); }

/* ================= 攻击预警：地面范围贴花 + 顶部读条 =================
   贴花尺寸与命中判定共用下面的参数，所以「地上画的圈」就是真会挨打的范围。
   dir 为相对龙正前方的偏角（度，正数偏向模型右侧），fan=lane 用同一套旋转公式。 */
const TELLS = {
  claw:  {name:'爪 击',   col:0xffb455, kind:'fan',  r:6.4,  half:54,  dir: 34, t0:.06, hit:.56, rMin:1.6, glow:1},
  bite:  {name:'撕 咬',   col:0xff8a5e, kind:'lane', r:5.6,  half:1.9, dir:  0, t0:.06, hit:.52, glow:1},
  sweep: {name:'尾 扫',   col:0xffd76a, kind:'fan',  r:7.5,  half:70,  dir:180, t0:.06, hit:.68, rMin:1.4, glow:0},
  breath:{name:'吐 息',   col:0xff6a2a, kind:'fan',  r:13.5, half:26,  dir:  0, t0:.28, hit:.62, glow:1},
  charge:{name:'蓄力火球', col:0xff4d2a, kind:'lane', r:13, half:2.2, dir:  0, t0:.16, hit:.60, glow:1},
  dive:  {name:'俯 冲',   col:0xff3b3b, kind:'ring', r:5.5,  half:0,   dir:  0, t0:0,   hit:-1,  glow:0}
};
const tellGrp = new THREE.Group(); tellGrp.position.y = .05; dragon.add(tellGrp);
const tellMesh = {};
for(const k in TELLS){
  const c = TELLS[k];
  let g;
  if(c.kind === 'fan'){ const h = c.half*Math.PI/180; g = new THREE.RingGeometry((c.rMin||0)/c.r, 1, 34, 1, -h, h*2).rotateX(-Math.PI/2); }
  else if(c.kind === 'lane'){ g = new THREE.PlaneGeometry(2,1).rotateX(-Math.PI/2); g.translate(0,0,-.5); }
  else g = new THREE.RingGeometry(.84,1,48).rotateX(-Math.PI/2);
  const m = new THREE.Mesh(g, new THREE.MeshBasicMaterial({color:c.col, transparent:true, opacity:0,
    blending:THREE.AdditiveBlending, depthWrite:false, side:THREE.DoubleSide}));
  m.visible = false; m.position.set(0,.05,0); tellGrp.add(m); tellMesh[k] = m;
}
let dTell = null, tellFlashT = 0;
function tellClear(){
  dTell = null; tellFlashT = 0; tellGrp.position.y = .05;
  for(const k in tellMesh) tellMesh[k].visible = false;
  const e = document.getElementById('dTell'); if(e) e.className = '';
}
function tellBegin(s){
  const c = TELLS[s]; if(!c) return;
  const m = tellMesh[s];
  dTell = {s:s, c:c, t:0, hit:false};
  m.visible = true; m.material.opacity = 0;
  m.rotation.y = (c.kind === 'fan'? Math.PI/2 : 0) + c.dir*Math.PI/180;
  m.scale.set(c.kind === 'lane'? c.half : c.r, 1, c.r);
  const e = document.getElementById('dTell');
  if(e){ e.className = 'show'; e.style.color = '#' + c.col.toString(16).padStart(6,'0'); e.firstChild.textContent = c.name; }
}
function tellK(){ if(!dTell || dTell.c.hit < 0) return 0; return Math.min(1, dTell.t/Math.max(.001, dTell.c.hit)); }
function localXZ(v){ const c=Math.cos(dragon.rotation.y), sn=Math.sin(dragon.rotation.y); return new THREE.Vector3(v.x*c - v.z*sn, 0, v.x*sn + v.z*c); }
function tellImpact(){ tellFlashT = .28; }
// 命中判定（与贴花同参数）
function fanTest(rMax, dirDeg, halfDeg, rMin){
  const to = hero.position.clone().sub(dragon.position).setY(0); const L = to.length();
  if(L > rMax || L < (rMin||0)) return null;
  const a = dragon.rotation.y + dirDeg*Math.PI/180;
  const d = new THREE.Vector3(-Math.sin(a), 0, -Math.cos(a));
  return d.dot(to.normalize()) >= Math.cos(halfDeg*Math.PI/180) ? to : null;
}
function laneTest(rMax, halfW, dirDeg){
  const to = hero.position.clone().sub(dragon.position).setY(0); const L = to.length();
  if(L < .2 || L > rMax + .8) return null;
  const a = dragon.rotation.y + dirDeg*Math.PI/180;
  const d = new THREE.Vector3(-Math.sin(a), 0, -Math.cos(a));
  const f = to.dot(d);
  if(f < -.2) return null;
  return Math.sqrt(Math.max(0, to.lengthSq() - f*f)) <= halfW ? to : null;
}
function updateTell(dt, t){
  if(gameOver){ if(dTell) tellClear(); return; }
  const e = document.getElementById('dTell');
  if(!dTell){ if(e && e.className) e.className = ''; return; }
  const c = dTell.c, m = tellMesh[dTell.s];
  dTell.t += dt;
  const k = (c.hit < 0)? 0 : Math.min(1, Math.max(0, (dTell.t - c.t0)/Math.max(.001, c.hit - c.t0)));
  if(c.hit > 0 && !dTell.hit && dTell.t >= c.hit){ dTell.hit = true; tellImpact(); camShake = Math.max(camShake, .2); }
  let op = dTell.t < c.t0? 0 : (.13 + .12*k + .05*Math.sin(t*(10 + k*26)));
  if(dTell.hit) op *= Math.max(0, 1 - (dTell.t - c.hit)/.5);
  if(tellFlashT > 0){ tellFlashT -= dt; op = Math.max(op, tellFlashT*2.2); }
  m.material.opacity = Math.min(.9, Math.max(0, op));
  if(c.kind === 'ring'){
    if(diveTarget){
      m.position.copy(localXZ(diveTarget.clone().sub(dragon.position)));
      tellGrp.position.y = .05 - dragon.position.y;   // 贴花留在地面，不跟着龙飞
      const kk = 1 - Math.min(1, Math.max(0, dragon.position.y/9));
      m.scale.set(c.r*(1 - .5*kk), 1, c.r*(1 - .5*kk));
    }
  }
  if(e){
    e.lastChild.style.width = Math.round(k*100) + '%';
    if(tellFlashT > 0 && e.className.indexOf('flash') < 0) e.className = 'show flash';
    else if(tellFlashT <= 0 && e.className.indexOf('flash') >= 0) e.className = 'show';
  }
}''',
    '7 预警模块')

# ---------------------------------------------------------------- 8. 嘴里火光预警
rep("  mouthLight.intensity = breathOn? 60 : (dragonState==='charge'? 26+Math.sin(t*20)*8 : 0);",
    '''  const _gc = TELLS[dragonState];
  mouthLight.intensity = breathOn? 60 : (dragonState==='charge'? 26+Math.sin(t*20)*8
    : (_gc && _gc.glow? tellK()*(16+Math.sin(t*26)*10) : 0));''',
    '8 嘴里火光预警')

rep("  breathCone.material.opacity += ((breathOn? .16 : 0) - breathCone.material.opacity) * Math.min(1, dt*7);\n  if(!breathOn && breathCone.material.opacity<.01) breathCone.position.y = -99;",
    "  breathCone.material.opacity += (((breathOn && breathFiring)? .16 : 0) - breathCone.material.opacity) * Math.min(1, dt*7);\n"
    "  if((!breathOn || !breathFiring) && breathCone.material.opacity<.01) breathCone.position.y = -99;",
    '8b 喷火锥只在真喷火时出现')

# ---------------------------------------------------------------- 9. strafe
rep('''      if(stateTime<=0){
        if(!roarDone){ roarDone=true; setDragonState('roar', 1.0); }
        else if(dist<7.5){ const r=Math.random(); if(dist<6.8 && r<.34) setDragonState('claw', .75); else if(r<.62) setDragonState('bite', .7); else setDragonState('breath', 2.6); }
        else if(dist<14) setDragonState(Math.random()<.55?'breath':'charge', Math.random()<.55?2.6:.7);
        else setDragonState(Math.random()<.6?'charge':'strafe', Math.random()<.6?.7:.8);
        if(Math.random()<.22 && dist<16) setDragonState('fly', 2.2);
      }''',
    '''      if(stateTime<=0){
        const back = hero.position.clone().sub(dragon.position).setY(0).normalize().dot(dragonForward());
        if(!roarDone){ roarDone=true; setDragonState('roar', 1.5); }
        else if(back<-.45 && dist<5.8) setDragonState('sweep', 1.15);   // 猫绕到屁股后面 -> 甩尾
        else if(dist<7.5){ const r=Math.random(); if(dist<6.8 && r<.32) setDragonState('claw', 1.05); else if(r<.60) setDragonState('bite', 1.0); else setDragonState('breath', 2.6); }
        else if(dist<14) setDragonState(Math.random()<.5?'breath':'charge', Math.random()<.5?2.6:1.45);
        else setDragonState(Math.random()<.6?'charge':'strafe', Math.random()<.6?1.45:.9);
        if(Math.random()<.20 && dist<16 && dragonState==='strafe') setDragonState('fly', 2.6);
      }''',
    '9 strafe 选招 / 不再覆盖已选攻击 / 尾扫')

# ---------------------------------------------------------------- 10. roar
rep("    case 'roar': headPivot.rotation.x = -.35+Math.sin(t*30)*.03; if(stateTime<=0) setDragonState('strafe', .6); break;",
    "    case 'roar': headPivot.rotation.x = -.35+Math.sin(t*30)*.03; if(stateTime<=0) setDragonState('strafe', .7/speedMul); break;",
    '10 roar 收招')

# ---------------------------------------------------------------- 11. charge
rep('''      if(stateTime<=0){
        const mouth=new THREE.Vector3(); mouthPos.getWorldPosition(mouth);
        for(let i=0;i<3;i++) setTimeout(()=>{ if(!gameOver) shootFireball(mouth.clone(), hero.position.clone().add(new THREE.Vector3(0,.8,0))); }, i*260);
        setDragonState('strafe', 1.1/speedMul);
      }''',
    '''      if(!chargeFired && stateTime<=.85){    // 与 charge 片段 0.60s 张嘴那一刻对齐，连吐三发
        chargeFired = true;
        for(let i=0;i<3;i++) setTimeout(()=>{
          if(gameOver || dragonState!=='charge') return;
          const mouth=new THREE.Vector3(); mouthPos.getWorldPosition(mouth);
          shootFireball(mouth.clone(), hero.position.clone().add(new THREE.Vector3(0,.8,0)));
        }, i*280);
      }
      if(stateTime<=0) setDragonState('strafe', 1.1/speedMul);''',
    '11 charge 专属片段时序')

# ---------------------------------------------------------------- 12. breath
rep('''      let spawned=0;
      for(let i=0;i<500 && spawned<13;i++){ if(fireData[i].life<=0){''',
    '''      let spawned=0;
      breathFiring = stateTime <= 1.98;     // 与 breath 片段对齐：前 0.62s 抬头蓄气只给预警，之后才喷
      if(breathFiring && !breathFired){ breathFired = true; sfxFireBurst(); }
      for(let i=0;i<500 && breathFiring && spawned<13;i++){ if(fireData[i].life<=0){''',
    '12 breath 延迟喷火')

rep('''      breathCone.position.copy(mouth);
      breathCone.quaternion.setFromUnitVectors(new THREE.Vector3(0,-1,0), fwd);
      const toHero=hero.position.clone().sub(mouth).setY(0);
      const angle=toHero.clone().normalize().dot(fwd);
      if(toHero.length()<13.5 && angle>.9 && hurtCd<=0){ heroTakeDamage(8); burst(hero.position.clone().add(new THREE.Vector3(0,.9,0)), 10, 0xff7a1a, 3, 3); }''',
    '''      if(breathFiring){
        breathCone.position.copy(mouth);
        breathCone.quaternion.setFromUnitVectors(new THREE.Vector3(0,-1,0), fwd);
      }
      const toHero=hero.position.clone().sub(mouth).setY(0);
      const angle=toHero.clone().normalize().dot(fwd);
      if(breathFiring && toHero.length()<13.5 && angle>.9 && hurtCd<=0){ heroTakeDamage(8); burst(hero.position.clone().add(new THREE.Vector3(0,.9,0)), 10, 0xff7a1a, 3, 3); }''',
    '12b breath 命中只在喷火窗口')

# ---------------------------------------------------------------- 13. bite
rep('''    case 'bite':
      dragonFaceHero(dt, 4);
      dragon.position.addScaledVector(dragonForward(), dt*10);
      if(dist<5){ heroTakeDamage(16); setDragonState('strafe', 1.0); }
      if(stateTime<=0) setDragonState('strafe', .8);
      break;''',
    '''    case 'bite':
      dragonFaceHero(dt, 4);
      dragon.position.addScaledVector(dragonForward(), dt*(stateTime>.48? 8 : 2.2)); // 前半程扑出去，咬完收势
      if(!biteHit && stateTime<=.48){      // 与 bite 片段 0.52s 的咬合对齐
        biteHit = true;
        if(laneTest(5.6, 1.9, 0)){
          heroTakeDamage(16);
          burst(hero.position.clone().add(new THREE.Vector3(0,1,0)), 14, 0xffb090, 3.5, 2.5);
        }
      }
      if(stateTime<=0) setDragonState('strafe', .8/speedMul);
      break;''',
    '13 bite 命中帧')

# ---------------------------------------------------------------- 14. claw
rep('''    case 'claw':
      dragonFaceHero(dt, 3.5);
      if(!dragonRigged && stateTime>.38) dragon.position.addScaledVector(dragonForward(), dt*2.5); // 几何版无爪：以前扑代替
      if(!clawHit && stateTime<=.38){
        clawHit = true;
        if(dist<6.4){
          const toH = hero.position.clone().sub(dragon.position).setY(0).normalize();
          if(toH.dot(dragonForward()) > .1){ heroTakeDamage(15); burst(hero.position.clone().add(new THREE.Vector3(0,.9,0)), 12, 0xffc9a8, 3, 2.5); }
        }
      }
      if(stateTime<=0) setDragonState('strafe', .8);
      break;''',
    '''    case 'claw':
      dragonFaceHero(dt, 3.5);
      if(stateTime>.49) dragon.position.addScaledVector(dragonForward(), dt*(dragonRigged? 1.6 : 3.0)); // 几何版无爪：前扑代替
      if(!clawHit && stateTime<=.49){      // 与 claw 片段 0.56s 的扫击对齐；范围=地上画的那把扇子
        clawHit = true;
        if(fanTest(6.4, 34, 54, 1.6)){
          heroTakeDamage(15);
          burst(hero.position.clone().add(new THREE.Vector3(0,.9,0)), 12, 0xffc9a8, 3, 2.5);
        }
      }
      if(stateTime<=0) setDragonState('strafe', .8/speedMul);
      break;
    case 'sweep': {
      dragonFaceHero(dt, 1.4);
      dragon.position.addScaledVector(dragonForward(), dt*.8);
      if(!sweepHit && stateTime<=.47){     // 与 sweep 片段 0.68s 的甩尾对齐
        sweepHit = true;
        if(fanTest(7.5, 180, 70, 1.4)){
          heroTakeDamage(14);
          burst(hero.position.clone().add(new THREE.Vector3(0,.8,0)), 13, 0xffd76a, 3.4, 2.2);
        }
      }
      if(stateTime<=0) setDragonState('strafe', .9/speedMul);
      break; }''',
    '14 claw 命中帧 + sweep 新招')

# ---------------------------------------------------------------- 15. dive
rep('''      if(dragon.position.y<=0.1 && dl<4.5){
        camShake=.55; sfxHurt(); burst(hero.position.clone().add(new THREE.Vector3(0,.4,0)), 22, 0x9aa48c, 5, 4);
        if(hero.position.distanceTo(dragon.position)<5.5) heroTakeDamage(20);
        flyHeight=0; setDragonState('strafe', 1.3);
      }''',
    '''      if(dragon.position.y<=0.1 && dl<4.5){
        camShake=.55; sfxHurt(); burst(hero.position.clone().add(new THREE.Vector3(0,.4,0)), 22, 0x9aa48c, 5, 4);
        tellImpact();                                    // 砸地瞬间：预判圈闪一下
        if(hero.position.distanceTo(target)<5.5) heroTakeDamage(20);   // 与地上那圈同半径
        flyHeight=0; setDragonState('strafe', 1.3);
      }''',
    '15 dive 命中与贴花同径')

# ---------------------------------------------------------------- 16. 删掉没动画的被动尾扫
rep('''  const behind = hero.position.clone().sub(dragon.position).setY(0).normalize().dot(dragonForward());
  if(dist<5.5 && behind<-.45 && dragonState==='strafe'){ heroTakeDamage(14); burst(hero.position.clone().add(new THREE.Vector3(0,.8,0)), 12, 0xffaa55, 3, 2); setDragonState('strafe', .7); }
''', '', '16 删掉无动画被动尾扫')

# ---------------------------------------------------------------- 17. 主循环挂 updateTell
rep('''  updateDragon(dt, t);
''', '''  updateDragon(dt, t);
  updateTell(dt, t);
''', '17 主循环挂 updateTell')

# ---------------------------------------------------------------- 18. 动画驱动
rep('''        if(dragonState==='bite' && dActs.bite){ dActs.bite.stop(); if(dCurAct==='bite') dCurAct=''; }
        if(dragonState==='claw' && dActs.claw){ dActs.claw.stop(); if(dCurAct==='claw') dCurAct=''; }
        if(dragonState==='roar' && dActs.roar){ dActs.roar.stop(); if(dCurAct==='roar') dCurAct=''; }''',
    '''        ['bite','claw','sweep','charge','roar'].forEach(nm=>{ if(dragonState===nm && dActs[nm]){ dActs[nm].stop(); if(dCurAct===nm) dCurAct=''; } });''',
    '18a 切换时重播的一次性片段')

rep('''      else if(dragonState==='fly' || dragonState==='dive') dWant = 'flap';
      else if(dragonState==='breath' || dragonState==='charge') dWant = 'breath';
      else if(dragonState==='bite'){ dWant = 'bite'; dOnce = true; }
      else if(dragonState==='claw'){ dWant = 'claw'; dOnce = true; }
      else if(dragonState==='roar'){ dWant = 'roar'; dOnce = true; }''',
    '''      else if(dragonState==='fly' || dragonState==='dive') dWant = 'flap';
      else if(dragonState==='breath') dWant = 'breath';
      else if(dragonState==='charge'){ dWant = 'charge'; dOnce = true; }
      else if(dragonState==='bite'){ dWant = 'bite'; dOnce = true; }
      else if(dragonState==='claw'){ dWant = 'claw'; dOnce = true; }
      else if(dragonState==='sweep'){ dWant = 'sweep'; dOnce = true; }
      else if(dragonState==='roar'){ dWant = 'roar'; dOnce = true; }''',
    '18b 状态->片段映射')

io.open(P, 'wb').write(s.replace('\n', NL).encode('utf-8'))
print('补丁完成 %d 处：' % len(APPLIED))
for i, a in enumerate(APPLIED, 1):
    print('  %2d. %s' % (i, a))
