let ws=null,myId=null,roomId=null,lastState=null,lastVisualSequence=0,lastToastSequence=0,toastTimer=null,announcedGameOver=false,pendingTargetCard=null,pendingAttackChoice=null,deferredAttackMode=false,permanentActivationCard=null,chosenAvatar='🐈‍⬛',wildTargetMode=false,lastTurnPlayer=null;
const $=(id)=>document.getElementById(id);
const SFX={click:'assets/audio/click.ogg',card:'assets/audio/card-play.ogg',drawer:'assets/audio/drawer.ogg',turn:'assets/audio/turn.ogg',error:'assets/audio/error.ogg'};const soundPool=Object.fromEntries(Object.entries(SFX).map(([name,url])=>{const audio=new Audio(url);audio.preload='auto';audio.volume=name==='turn'?.075:.055;return [name,audio]}));let soundOn=localStorage.getItem('krutagidon_sound')!=='off';function softTurnChime(){try{const Ctx=window.AudioContext||window.webkitAudioContext;const ctx=new Ctx();const gain=ctx.createGain();gain.gain.setValueAtTime(.0001,ctx.currentTime);gain.gain.exponentialRampToValueAtTime(.035,ctx.currentTime+.04);gain.gain.exponentialRampToValueAtTime(.0001,ctx.currentTime+.65);gain.connect(ctx.destination);[174.6,220].forEach((freq,index)=>{const osc=ctx.createOscillator();osc.type='sine';osc.frequency.setValueAtTime(freq,ctx.currentTime+index*.05);osc.connect(gain);osc.start(ctx.currentTime+index*.05);osc.stop(ctx.currentTime+.7)});setTimeout(()=>ctx.close(),800)}catch(e){}}function paperCardSound(){try{const Ctx=window.AudioContext||window.webkitAudioContext;const ctx=new Ctx();const length=Math.floor(ctx.sampleRate*.16);const buffer=ctx.createBuffer(1,length,ctx.sampleRate);const data=buffer.getChannelData(0);for(let i=0;i<length;i++)data[i]=(Math.random()*2-1)*(1-i/length);const source=ctx.createBufferSource();source.buffer=buffer;const filter=ctx.createBiquadFilter();filter.type='bandpass';filter.frequency.value=850;filter.Q.value=.7;const gain=ctx.createGain();gain.gain.setValueAtTime(.0001,ctx.currentTime);gain.gain.exponentialRampToValueAtTime(.045,ctx.currentTime+.012);gain.gain.exponentialRampToValueAtTime(.0001,ctx.currentTime+.17);source.connect(filter);filter.connect(gain);gain.connect(ctx.destination);source.start();setTimeout(()=>ctx.close(),250)}catch(e){}}function playSound(name){if(!soundOn)return;if(name==='turn'){softTurnChime();return}if(name==='card'){paperCardSound();return}const base=soundPool[name];if(!base)return;const audio=base.cloneNode();audio.volume=base.volume;try{const pr=audio.play();if(pr&&typeof pr.catch==='function')pr.catch(()=>{})}catch(e){}}
function wsUrl(room){return `${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/${encodeURIComponent(room)}`}
$("join-btn").onclick=()=>{const name=$("name-input").value.trim()||'Колдун';roomId=$("room-input").value.trim()||'default';const saved=localStorage.getItem('krutagidon_pid_'+roomId);$("join-btn").disabled=true;$("join-btn").textContent='Подключаемся…';ws=new WebSocket(wsUrl(roomId));ws.onopen=()=>ws.send(JSON.stringify({name,avatar:chosenAvatar,player_id:saved||undefined}));ws.onmessage=e=>handleMessage(JSON.parse(e.data));ws.onclose=()=>{$("join-btn").disabled=false;$("join-btn").textContent='Войти в Крутагидон'}};
function handleMessage(msg){if(msg.type==='joined'){myId=msg.player_id;localStorage.setItem('krutagidon_pid_'+roomId,myId);$('lobby-room-code').textContent=roomId;$('room-code-game').textContent=roomId;show('lobby-screen')}else if(msg.type==='lobby'){renderLobby(msg);if(msg.started)show('game-screen')}else if(msg.type==='state'){const motion=captureVisualMotion(msg.state.visual_event);lastState=msg.state;show('game-screen');render(msg.state);prepareVisualMotion(motion);requestAnimationFrame(()=>playVisualMotion(motion,msg.state.visual_event))}else if(msg.type==='error'){playSound('error');alert(msg.message)}}
function show(id){['join-screen','lobby-screen','game-screen'].forEach(s=>$(s).classList.toggle('hidden',s!==id))}
function renderLobby(msg){$('lobby-players').innerHTML=msg.players.map(p=>`<li>${escapeHtml(p.name)}${p.id===msg.host_id?' · хост':''} <span class="${p.ready?'ready':''}">${p.ready?'✓ готов':'выбирает свойство / фамильяра'}</span></li>`).join('');const hasProperty=Boolean(msg.selected_property_id);$('familiar-picker').classList.toggle('hidden',!hasProperty);if(hasProperty){const selected=msg.selected_familiar_ids||[];$('familiar-choice-title').textContent=msg.familiar_required===3?`Выбери фамильяров: ${selected.length}/3`:`Выбери одного фамильяра: ${selected.length}/1`;$('familiar-options').replaceChildren(...msg.familiar_choices.map(board=>familiarButton(board,selected)))}$('property-options').replaceChildren(...msg.property_choices.map(p=>propertyButton(p,msg.selected_property_id)));$('start-btn').disabled=msg.players.some(p=>!p.ready);$('host-settings').classList.toggle('hidden',!msg.is_host);$('add-bot-btn').classList.toggle('hidden',!msg.is_host);if(msg.is_host){$('zhdk-mode').value=msg.settings?.zhdk_mode||'standard';$('zhdk-custom').classList.toggle('hidden',$('zhdk-mode').value!=='custom');if(msg.settings?.zhdk_count)$('zhdk-custom').value=msg.settings.zhdk_count}}
function boardToCard(board){return {id:board.familiar_id||board.id,name:board.familiar_name,type:board.type||'Фамильяр',cost:board.cost||0,power:board.power||0,vp:board.vp||0,text:board.familiar_text||''}}
function familiarButton(board,selected){
  const isPicked=selected.includes(board.id);
  const el=document.createElement('div');
  el.className='familiar-option'+(isPicked?' selected':'');
  const src=`https://raw.githubusercontent.com/SpongeGamer/krutagidoniwe/main/frontend/assets/cards/${encodeURIComponent(board.id)}.webp`;
  // Только крупная картинка карты — весь текст и так напечатан на самой карте.
  el.innerHTML=`
    <div class="fam-photo"><img src="${src}" alt="${escapeHtml(board.familiar_name)}" loading="lazy"><button class="fam-zoom" type="button" title="Увеличить">⌕</button></div>
    <button class="fam-pick" type="button">${isPicked?'✓ Выбран — отменить':'Выбрать'}</button>`;
  const card=boardToCard(board);
  el.querySelector('.fam-photo').onclick=(e)=>{e.stopPropagation();showCard(card)};
  el.querySelector('.fam-zoom').onclick=(e)=>{e.stopPropagation();showCard(card)};
  el.querySelector('.fam-pick').onclick=(e)=>{
    e.stopPropagation();playSound('click');
    if(isPicked){ws.send(JSON.stringify({action:'unchoose_familiar',familiar_id:board.id}));return}
    confirmFamiliar(board);
  };
  return el;
}
/* Подтверждение выбора — чтобы случайный клик не залочил фамильяра.
   Показываем только саму карту крупно: всё описание напечатано на ней. */
function confirmFamiliar(board){
  const src=`https://raw.githubusercontent.com/SpongeGamer/krutagidoniwe/main/frontend/assets/cards/${encodeURIComponent(board.id)}.webp`;
  $('confirm-fam-photo').innerHTML=`<img src="${src}" alt="${escapeHtml(board.familiar_name)}">`;
  $('confirm-fam-title').textContent=board.familiar_name;
  $('confirm-fam-wizard').textContent=board.wizard_name;
  $('confirm-fam-yes').onclick=()=>{playSound('click');ws.send(JSON.stringify({action:'choose_familiar',familiar_id:board.id}));$('confirm-fam-modal').classList.add('hidden')};
  $('confirm-fam-no').onclick=()=>$('confirm-fam-modal').classList.add('hidden');
  $('confirm-fam-close').onclick=()=>$('confirm-fam-modal').classList.add('hidden');
  $('confirm-fam-modal').classList.remove('hidden');
}

function propertyButton(property,selected){const btn=document.createElement('button');btn.className='property-option'+(selected===property.id?' selected':'');btn.innerHTML=`<b>${escapeHtml(property.name)}</b><small>${escapeHtml(property.effect_text)}</small>`;btn.onclick=()=>ws.send(JSON.stringify({action:'choose_property',property_id:property.id}));return btn}
const AVATARS=[['🐈‍⬛','Чёрный кот'],['🐕','Верный пёс'],['🦊','Лиса-колдунья'],['🐸','Жабий маг'],['🐉','Маленький дракон'],['🦄','Единорог'],['🦇','Летучая мышь'],['🐺','Лунный волк'],['🦝','Енот-воришка'],['🐙','Осьминог из бездны'],['🦜','Попугай-предсказатель'],['🦎','Ящер-маг'],['🐌','Улитка хаоса'],['🦋','Ночная бабочка'],['👽','Космический колдун'],['🤡','Сальный шут'],['🧙','Старый колдун'],['🧙‍♀️','Ведьма'],['🧛','Вампир'],['🧟','Зомби'],['👹','Демон'],['🧞','Джинн'],['🧚','Фея'],['🧜','Русалка']];let avatarIndex=0;function renderAvatar(direction=1){const avatar=$('avatar-current');avatar.classList.add('swap');setTimeout(()=>{const [icon,name]=AVATARS[avatarIndex];chosenAvatar=icon;avatar.textContent=icon;$('avatar-name').textContent=name;avatar.classList.remove('swap')},120)}$('avatar-prev').onclick=()=>{avatarIndex=(avatarIndex-1+AVATARS.length)%AVATARS.length;renderAvatar(-1)};$('avatar-next').onclick=()=>{avatarIndex=(avatarIndex+1)%AVATARS.length;renderAvatar(1)};
function sendRoomSettings(){ws.send(JSON.stringify({action:'configure_room',zhdk_mode:$('zhdk-mode').value,zhdk_count:$('zhdk-custom').value}));playSound('click')}$('zhdk-mode').onchange=()=>{$('zhdk-custom').classList.toggle('hidden',$('zhdk-mode').value!=='custom');if($('zhdk-mode').value!=='custom')sendRoomSettings()};$('zhdk-custom').onchange=sendRoomSettings;$('save-room-settings').onclick=sendRoomSettings;$('info-close').onclick=()=>$('info-modal').classList.add('hidden');function showInfo(title,text){$('info-title').textContent=title;$('info-text').textContent=text;$('info-modal').classList.remove('hidden')}$('card-close').onclick=()=>$('card-modal').classList.add('hidden');function showCard(card){$('inspect-type').textContent=card.type||'Карта';$('inspect-name').textContent=card.name;$('inspect-stats').innerHTML=`<b>◉ ${card.cost}</b><b>⚡ +${card.power}</b><b>★ ${card.vp||0} ПО</b>`;$('inspect-text').textContent=card.text||'';const visual=cardEl(card,null);visual.classList.add('inspect-card');$('inspect-card').replaceChildren(visual);$('card-modal').classList.remove('hidden')}$('event-continue').onclick=()=>{playSound('drawer');ws.send(JSON.stringify({action:'resolve_event'}))};$('sound-toggle').textContent=soundOn?'🔊':'🔇';$('sound-toggle').onclick=()=>{soundOn=!soundOn;localStorage.setItem('krutagidon_sound',soundOn?'on':'off');$('sound-toggle').textContent=soundOn?'🔊':'🔇';if(soundOn)playSound('click')};$('add-bot-btn').onclick=()=>{playSound('click');ws.send(JSON.stringify({action:'add_bot'}))};$('start-btn').onclick=()=>{playSound('click');ws.send(JSON.stringify({action:'start_game'}));};$('end-turn-btn').onclick=()=>ws.send(JSON.stringify({action:'end_turn'}));$('buy-wild-btn').onclick=()=>ws.send(JSON.stringify({action:'buy_wild_magic'}));$('buy-familiar-btn').onclick=()=>ws.send(JSON.stringify({action:'buy_familiar'}));$('target-cancel').onclick=closeTargetModal;$('attack-cancel').onclick=()=>$('attack-modal').classList.add('hidden');$('attack-later').onclick=()=>{sendPlay(pendingAttackChoice,{defer_attack:true});$('attack-modal').classList.add('hidden')};$('attack-now').onclick=()=>{const card=pendingAttackChoice;$('attack-modal').classList.add('hidden');playAttackNow(card)};$('wild-cancel').onclick=()=>$('wild-modal').classList.add('hidden');$('wild-power').onclick=()=>{sendPlay({id:'spec_wild'}, {choice:'power'});$('wild-modal').classList.add('hidden')};$('wild-steal').onclick=()=>{wildTargetMode=true;$('wild-modal').classList.add('hidden');openTargetModal({id:'spec_wild',name:'Шальная магия'})};$('log-toggle').onclick=()=>document.querySelector('.event-feed').classList.add('open');$('log-close').onclick=()=>document.querySelector('.event-feed').classList.remove('open');document.querySelectorAll('.drawer-tab').forEach(tab=>tab.onclick=()=>{playSound('drawer');tab.closest('.market-drawer').classList.toggle('open')});document.addEventListener('contextmenu',event=>{const card=event.target.closest?.('.card');if(card?._cardData){event.preventDefault();showCard(card._cardData)}else event.preventDefault()},true);document.addEventListener('dragstart',event=>event.preventDefault(),true);
function elementFor(selector){return document.querySelector(selector)}
function lastElementFor(selector){const all=document.querySelectorAll(selector);return all.length?all[all.length-1]:null}
function createBotHandSource(playerId,card){
  const seat=elementFor(`.opp-card[data-player-id="${CSS.escape(playerId)}"]`);
  if(!seat)return null;
  const r=seat.getBoundingClientRect();
  const ghost=cardEl(card,null);
  return {from:{left:r.left+r.width/2-46,top:r.bottom-12,width:92,height:126},clone:ghost};
}
function fallbackSource(event,card){
  let anchor=null;
  if(event.source==='market') anchor=elementFor('.market-rail')||elementFor('#market');
  else if(event.source==='table') anchor=elementFor('.table-stage');
  else anchor=event.player_id===myId?elementFor('#self-panel'):elementFor(`.opp-card[data-player-id="${CSS.escape(event.player_id)}"]`);
  if(!anchor)return null;
  const r=anchor.getBoundingClientRect();
  const ghost=cardEl(card,null);
  return {from:{left:r.left+r.width/2-46,top:r.top+r.height/2-63,width:92,height:126},clone:ghost};
}
function captureVisualMotion(event){
  if(!event||!event.seq||event.seq<=lastVisualSequence)return null;
  lastVisualSequence=event.seq;
  const card=event.cards?.[0];
  if(!card||!event.player_id)return null;
  let source=null,target=null;
  if(event.type==='play'){
    if(event.player_id===myId){
      const el=elementFor(`#hand .card[data-card-id="${CSS.escape(card.id)}"]`);
      if(el)source={from:el.getBoundingClientRect(),clone:el.cloneNode(true)};
    }else source=createBotHandSource(event.player_id,card);
    target=event.destination==='permanent'?`#permanents .card[data-card-id="${CSS.escape(card.id)}"]`:`#played-cards .card[data-card-id="${CSS.escape(card.id)}"]`;
  }else if(event.type==='buy'){
    const el=elementFor(`#market .card[data-card-id="${CSS.escape(card.id)}"],#legend-market .card[data-card-id="${CSS.escape(card.id)}"]`);
    if(el)source={from:el.getBoundingClientRect(),clone:el.cloneNode(true)};
    target=`.opp-card[data-player-id="${CSS.escape(event.player_id)}"] .discard-stat`;
  }else if(event.type==='discard'){
    const el=elementFor(`#played-cards .card[data-card-id="${CSS.escape(card.id)}"]`);
    if(el)source={from:el.getBoundingClientRect(),clone:el.cloneNode(true)};
    target=`.opp-card[data-player-id="${CSS.escape(event.player_id)}"] .discard-stat`;
  }
  source=source||fallbackSource(event,card);return source&&target?{kind:event.type,card,from:source.from,target,sourceClone:source.clone}:null;
}
function prepareVisualMotion(motion){if(!motion)return;const target=lastElementFor(motion.target);if(target)target.classList.add('motion-target-hidden')}
function flyCard(motion){
  const target=lastElementFor(motion.target);if(!target||!motion.from)return;
  const to=target.getBoundingClientRect();
  const ghost=motion.sourceClone || cardEl(motion.card,null);
  ghost.classList.add('flying-card');ghost.removeAttribute('id');
  Object.assign(ghost.style,{left:`${motion.from.left}px`,top:`${motion.from.top}px`,width:`${motion.from.width}px`,height:`${motion.from.height}px`,opacity:'1',transform:'translate3d(0,0,0) scale(1)'});
  document.body.appendChild(ghost);
  const dx=(to.left+to.width/2)-(motion.from.left+motion.from.width/2);
  const dy=(to.top+to.height/2)-(motion.from.top+motion.from.height/2);
  const scale=Math.max(.18,Math.min(to.width/motion.from.width,to.height/motion.from.height));
  void ghost.offsetWidth;
  ghost.animate([
    {transform:'translate3d(0,0,0) scale(1)',opacity:1,offset:0},
    {transform:`translate3d(${dx*.58}px,${dy*.58}px,50px) scale(${1-(1-scale)*.42}) rotateZ(-2deg)`,opacity:1,offset:.55},
    {transform:`translate3d(${dx}px,${dy}px,0) scale(${scale})${motion.kind==='discard'?' rotateY(180deg) rotate(10deg)':' rotateZ(-4deg)'}`,opacity:.22,offset:1}
  ],{duration:900,easing:'cubic-bezier(.18,.78,.18,1)',fill:'forwards'});
  setTimeout(()=>{ghost.remove();target.classList.remove('motion-target-hidden')},920);
}
function playVisualMotion(motion,event){
  if(motion)flyCard(motion);
  if(event?.type==='turn'){
    const overlay=$('turn-overlay');overlay.textContent=`ХОД ИГРОКА ${event.player||''}`;overlay.classList.remove('hidden');setTimeout(()=>overlay.classList.add('hidden'),1300);
  }
}
/* ---------- Счётчики стопок и диагностика (v43) ---------- */
const BUILD_TAG='v48';
function setPileCounts(me){
  const d=$('self-deck-count'),c=$('self-discard-count');
  if(d)d.textContent=(me&&Number.isFinite(me.deck_count))?me.deck_count:0;
  if(c)c.textContent=(me&&Number.isFinite(me.discard_count))?me.discard_count:0;
  const img=$('self-discard-card');
  if(img){
    if(me&&me.discard_top)img.src=`https://raw.githubusercontent.com/SpongeGamer/krutagidoniwe/main/frontend/assets/cards/${encodeURIComponent(me.discard_top.id)}.webp`;
    else img.src='assets/cards/card_closed.webp';
  }
}
function showRenderError(err){
  console.error('render упал:',err);
  let box=$('render-error');
  if(!box){
    box=document.createElement('div');box.id='render-error';
    box.style.cssText='position:fixed;left:12px;bottom:12px;z-index:99999;max-width:520px;padding:10px 14px;border-radius:10px;background:#b3122f;color:#fff;font:12px/1.45 monospace;box-shadow:0 6px 20px #000a;white-space:pre-wrap';
    document.body.appendChild(box);
  }
  box.textContent='Ошибка отрисовки ('+BUILD_TAG+'):\n'+(err&&err.stack||err);
}
/* Плашка версии — сразу видно, свежий ли код загрузил браузер */
function stampBuild(){
  let s=document.getElementById('build-stamp');
  if(!s){
    s=document.createElement('div');s.id='build-stamp';
    s.style.cssText='position:fixed;right:8px;bottom:6px;z-index:99998;padding:3px 9px;border-radius:8px;background:#1c0f22cc;color:#ffd34e;font:10px/1.4 monospace;pointer-events:none';
    document.body.appendChild(s);
  }
  s.textContent='build '+BUILD_TAG;
}
document.addEventListener('DOMContentLoaded',stampBuild);
document.addEventListener('DOMContentLoaded',()=>bindPreview($('buy-wild-btn'),()=>WILD_CARD));
if(document.readyState!=='loading')bindPreview($('buy-wild-btn'),()=>WILD_CARD);
if(document.readyState!=='loading')stampBuild();
/* ---------- Пути к картинкам карт (v46) ----------
   Дохляки sdk_1..sdk_5 лежат в assets/tokens, а не в assets/cards,
   поэтому пробуем несколько адресов по очереди, пока не загрузится. */
const RAW_ASSETS='https://raw.githubusercontent.com/SpongeGamer/krutagidoniwe/main/frontend/assets';
function cardImageCandidates(id){
  const e=encodeURIComponent(id);
  const tokenFirst=/^(sdk_|dk_)/.test(id);
  const cards=[`assets/cards/${e}.webp`,`${RAW_ASSETS}/cards/${e}.webp`];
  const tokens=[`assets/tokens/${e}.webp`,`${RAW_ASSETS}/tokens/${e}.webp`];
  return tokenFirst?tokens.concat(cards):cards.concat(tokens);
}
function attachCardImage(img,id,onFail){
  const list=cardImageCandidates(id);let i=0;
  img.onerror=()=>{i++;if(i<list.length){img.src=list[i]}else{img.onerror=null;if(onFail)onFail()}};
  img.src=list[0];
}
/* Предпросмотр карт покупки (Шальная магия / Фамильяр) — v47 */
const WILD_CARD={id:'spec_wild',name:'Шальная магия',type:'Шальная магия',cost:3,power:2,vp:0,
  text:'Выбери одно: +2 мощи ИЛИ разыграй верхнюю карту колоды выбранного врага.'};
function bindPreview(el,getCard){
  if(!el)return;
  el.addEventListener('contextmenu',(e)=>{const card=getCard();if(!card)return;e.preventDefault();showCard(card)});
  const zoom=document.createElement('button');
  zoom.className='buy-zoom';zoom.type='button';zoom.textContent='⌕';zoom.title='Рассмотреть карту';
  zoom.onclick=(e)=>{e.preventDefault();e.stopPropagation();const card=getCard();if(card)showCard(card)};
  el.appendChild(zoom);
}
function escapeHtml(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function cardEl(card,onClick){const el=document.createElement('article');el.className='card'+(onClick?' is-actionable':'');el.dataset.cardId=card.id;el.title=`${card.name}\n${card.text||''}`;const img=document.createElement('img');img.className='cart-img';img.alt=card.name;img.loading='lazy';img.onload=()=>el.classList.add('has-image');attachCardImage(img,card.id,()=>{img.remove();el.classList.remove('has-image')});const info=document.createElement('div');info.className='card-info';info.innerHTML=`<div class="cname">${escapeHtml(card.name)}</div><div class="ctext">${escapeHtml((card.text||'').slice(0,128))}</div><div class="cfooter"><span class="cost">◉ ${card.cost}</span><span class="power">⚡ +${card.power}</span></div>`;el._cardData=card;const zoom=document.createElement('button');zoom.className='card-zoom';zoom.type='button';zoom.textContent='⌕';zoom.title='Открыть карту';zoom.onclick=(event)=>{event.stopPropagation();showCard(card)};el.append(img,info,zoom);if(onClick)el.onclick=onClick;return el}
function playerEl(p,isMe,isTurn,seat){
  const el=document.createElement('article');
  el.className='opp-card player-seat seat-'+seat+(isTurn?' active-turn':'')+(p.is_loshara?' loshara-player':'');
  el.dataset.playerId=p.id;
  const familiarSrc=p.familiar?`https://raw.githubusercontent.com/SpongeGamer/krutagidoniwe/main/frontend/assets/cards/${encodeURIComponent(p.familiar.id)}.webp`:'';
  const hpPercent=Math.max(0,Math.min(100,Math.round((p.life/Math.max(1,p.max_life))*100)));
  el.innerHTML=`
    ${isTurn?`<div class="seat-power">Мощь: <b>${p.power_available}</b></div>`:''}
    ${p.controls_prize?'<img class="player-prize" src="assets/prize/prize.webp" alt="Главный приз" title="Контролирует Главный приз">':''}
    <div class="player-core">
      <div class="avatar-box"><span>${escapeHtml(p.avatar||'🧙')}</span></div>
      <div class="player-main">
        <div class="player-name">${escapeHtml(p.name)}${isMe?' · Ты':''}</div>
        <div class="main-resources"><span class="main-chips"><img src="https://raw.githubusercontent.com/SpongeGamer/krutagidoniwe/main/frontend/assets/tokens/chips.webp" alt="">${p.chipsines}</span><span class="main-zhdk"><img src="assets/tokens/zdk.webp" alt="">${p.death_tokens}</span></div>
        <div class="hp-bar" title="${p.life}/${p.max_life} HP"><div class="hp-fill" style="width:${hpPercent}%"></div><span>♥ ${p.life}/${p.max_life} HP</span></div>
        ${p.is_loshara?'<div class="loshara-label">ЛОШАРА · максимум 15 HP</div>':''}
      </div>
      <button class="familiar-card" title="${p.familiar?escapeHtml(p.familiar.name):'Фамильяр'}">${p.familiar?`<img src="${familiarSrc}" alt="${escapeHtml(p.familiar.name)}">`:'✦'}</button>
    </div>`;
  if(p.familiar)el.querySelector('.familiar-card').onclick=(event)=>{event.stopPropagation();showCard(p.familiar)};
  return el;
}
function render(state){const me=state.players.find(p=>p.id===myId),active=state.players.find(p=>p.id===state.turn_player_id),myTurn=state.turn_player_id===myId;/* СЧЁТЧИКИ КОЛОДЫ/СБРОСА — В САМОМ НАЧАЛЕ. Никакая ошибка ниже не должна их обнулять. */setPileCounts(me);try{if(lastTurnPlayer&&lastTurnPlayer!==state.turn_player_id)playSound('turn');lastTurnPlayer=state.turn_player_id;renderVisualEvent(state.visual_event);renderEvent(state.pending_event);renderDecision(state.pending_decision);$('turn-banner').textContent=active?(myTurn?'Твой ход — наводи Крутагидон':`Ходит ${active.name}`):'Подготовка';$('log-panel').innerHTML=state.logs.map(l=>`<div>${escapeHtml(l)}</div>`).join('');$('log-panel').scrollTop=$('log-panel').scrollHeight;const seatedPlayers=[...(me?[me]:[]),...state.players.filter(p=>p.id!==myId)];const seatLayouts={1:[0],2:[0,1],3:[0,2,3],4:[0,4,1,5],5:[0,4,2,3,5]};const seats=seatLayouts[seatedPlayers.length]||seatLayouts[5];$('opponents').replaceChildren(...seatedPlayers.map((p,index)=>playerEl(p,p.id===myId,p.id===state.turn_player_id,seats[index])));$('played-cards').replaceChildren(...(active?.played_this_turn||[]).map(c=>cardEl(c,null)));$('main-deck-count').textContent=state.main_deck_count;$('legend-deck-count').textContent=state.legend_deck_count;$('vyal-count').textContent=state.vyal_remaining;$('zhdk-count').textContent=state.undead_stack_count;$('chips-bank-count').textContent=state.chips_bank;$('market').replaceChildren(...state.market.map(c=>cardEl(c,()=>myTurn&&buyCard(c.id))));$('legend-market').replaceChildren(...state.legend_market.map(c=>cardEl(c,()=>myTurn&&buyCard(c.id))));$('buy-wild-btn').disabled=!myTurn;$('buy-familiar-btn').disabled=!myTurn||!me||me.familiar_bought;const famBtn=$('buy-familiar-btn');if(me?.familiar){famBtn.innerHTML='<img class="buy-fam-thumb" alt="">';famBtn.title=`Купить фамильяра: ${me.familiar.name} · 6`;attachCardImage(famBtn.querySelector('img'),me.familiar.id);bindPreview(famBtn,()=>me.familiar)}else{famBtn.innerHTML='';famBtn.title='Купить фамильяра · 6'};$('hand').replaceChildren(...(me?.hand||[]).map(c=>cardEl(c,()=>myTurn&&playCard(c))));$('permanents').replaceChildren(...(me?.zone_in_play||[]).map(c=>cardEl(c,c.activation?()=>activatePermanent(c):null)));$('attack-actions').replaceChildren(...(me?.available_attacks||[]).map(c=>deferredAttackButton(c,myTurn)));$('self-panel').classList.toggle('self-loshara',Boolean(me?.is_loshara));$('self-stats').innerHTML=me?`<div class="self-name">${escapeHtml(me.name)}${me.is_loshara?' · ЛОШАРА':''}${myTurn?' · ТВОЙ ХОД':''}</div><div class="self-meta"><span class="stat-chip health">♥ ${me.life}/${me.max_life} HP</span><span class="stat-chip power">⚡ ${me.power_available} мощи</span></div>`:'';if(me?.discard_top){$('self-discard-card').src=`https://raw.githubusercontent.com/SpongeGamer/krutagidoniwe/main/frontend/assets/cards/${encodeURIComponent(me.discard_top.id)}.webp`}else{$('self-discard-card').src='assets/cards/card_closed.webp'}$('prize-supply').classList.toggle('hidden',state.players.some(p=>p.controls_prize));$('end-turn-btn').disabled=!myTurn;if(state.game_over&&!announcedGameOver){announcedGameOver=true;alert('Игра окончена! Победитель: '+(state.players.find(p=>p.id===state.winner)?.name||'?'))}}catch(err){showRenderError(err)}}
function renderVisualEvent(event){const toast=$('activity-toast');if(!event||!event.seq)return;if(event.seq===lastToastSequence)return;lastToastSequence=event.seq;const card=event.cards?.[0];const verb=event.type==='buy'?'покупает':event.type==='play'?'разыгрывает':event.type==='turn'?'получает ход':'заканчивает ход';toast.innerHTML=`<b>${escapeHtml(event.player)}</b> ${verb}${card?`: <span>${escapeHtml(card.name)}</span>`:''}`;toast.classList.remove('hidden');clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.classList.add('hidden'),1500)}
function renderEvent(event){const modal=$('event-modal');if(!event){modal.classList.add('hidden');return}$('event-type').textContent=event.type||'СОБЫТИЕ';$('event-name').textContent=event.name||'Событие';$('event-text').textContent=event.text||'';modal.classList.remove('hidden')}
function renderDecision(decision){const modal=$('decision-modal');if(!decision||decision.waiting_for){modal.classList.add('hidden');return}$('decision-title').textContent=decision.title||'Выбери вариант';$('decision-text').textContent=decision.text||'';$('decision-revealed').replaceChildren(...(decision.revealed_cards||[]).map(card=>cardEl(card,null)));$('decision-options').replaceChildren(...(decision.options||[]).map(option=>{const button=document.createElement('button');button.className='target-button';button.innerHTML=`<b>${escapeHtml(option.label)}</b>${option.detail?`<small>${escapeHtml(option.detail)}</small>`:''}`;button.onclick=()=>{playSound('click');ws.send(JSON.stringify({action:'resolve_decision',option_id:option.id}))};return button}));modal.classList.remove('hidden')}
function buyCard(cardId){playSound('click');ws.send(JSON.stringify({action:'buy_card',card_id:cardId}))}
function playCard(card){if(card.id==='spec_wild'){$('wild-modal').classList.remove('hidden');return}if(card.has_attack){pendingAttackChoice=card;$('attack-card-name').textContent=card.name;$('attack-modal').classList.remove('hidden');return}sendPlay(card,{})}
function playAttackNow(card){if(card.text&&card.text.toLowerCase().includes('выбранн'))openTargetModal(card);else sendPlay(card,{})}
function deferredAttackButton(card,myTurn){const b=document.createElement('button');b.className='deferred-attack';b.disabled=!myTurn;b.innerHTML=`⚔ Атаковать: <b>${escapeHtml(card.name)}</b>`;b.onclick=()=>activateDeferredAttack(card);return b}
function activateDeferredAttack(card){deferredAttackMode=true;if(card.text&&card.text.toLowerCase().includes('выбранн'))openTargetModal(card);else sendAttackActivation(card,{})}
function openTargetModal(card){pendingTargetCard=card;$('target-card-name').textContent=card.name;const selfAllowed=card.id==='start_syrpal'||card.id==='start_hrenal';const targets=lastState.players.filter(p=>selfAllowed||p.id!==myId);$('target-list').replaceChildren(...targets.map(p=>{const b=document.createElement('button');b.className='target-button';b.innerHTML=`<b>${escapeHtml(p.name)}${p.id===myId?' · ты':''}</b><small>♥ ${p.life}/${p.max_life} · ☠ ЖДК ${p.death_tokens}</small>`;b.onclick=()=>{if(permanentActivationCard){sendPermanentActivation(permanentActivationCard,{target_id:p.id});permanentActivationCard=null}else if(deferredAttackMode){sendAttackActivation(card,{target_id:p.id});deferredAttackMode=false}else{sendPlay(card,wildTargetMode?{choice:'steal',target_id:p.id}:{target_id:p.id})}wildTargetMode=false;closeTargetModal()};return b}));$('target-modal').classList.remove('hidden')}
function closeTargetModal(){$('target-modal').classList.add('hidden');pendingTargetCard=null}
function sendPlay(card,params){playSound('card');ws.send(JSON.stringify({action:'play_card',card_id:card.id,params}))}
function sendAttackActivation(card,params){playSound('card');ws.send(JSON.stringify({action:'activate_attack',card_id:card.id,params}))}
function activatePermanent(card){if(['beast_jaba','leg_throne'].includes(card.id)){permanentActivationCard=card;openTargetModal(card)}else sendPermanentActivation(card,{})}
function sendPermanentActivation(card,params){playSound('card');ws.send(JSON.stringify({action:'activate_permanent',card_id:card.id,params}))}

