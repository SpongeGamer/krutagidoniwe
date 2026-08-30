let ws=null,myId=null,roomId=null,lastState=null,lastVisualSequence=0,lastToastSequence=0,toastTimer=null,announcedGameOver=false,pendingTargetCard=null,pendingAttackChoice=null,deferredAttackMode=false,permanentActivationCard=null,chosenAvatar='🐈‍⬛',wildTargetMode=false,lastTurnPlayer=null;
const $=(id)=>document.getElementById(id);
const SFX={click:'assets/audio/click.ogg',card:'assets/audio/card-play.ogg',drawer:'assets/audio/drawer.ogg',turn:'assets/audio/turn.ogg',error:'assets/audio/error.ogg'};const soundPool=Object.fromEntries(Object.entries(SFX).map(([name,url])=>{const audio=new Audio(url);audio.preload='auto';audio.volume=name==='turn'?.075:.055;return [name,audio]}));let soundOn=localStorage.getItem('krutagidon_sound')!=='off';function softTurnChime(){try{const Ctx=window.AudioContext||window.webkitAudioContext;const ctx=new Ctx();const gain=ctx.createGain();gain.gain.setValueAtTime(.0001,ctx.currentTime);gain.gain.exponentialRampToValueAtTime(.035,ctx.currentTime+.04);gain.gain.exponentialRampToValueAtTime(.0001,ctx.currentTime+.65);gain.connect(ctx.destination);[174.6,220].forEach((freq,index)=>{const osc=ctx.createOscillator();osc.type='sine';osc.frequency.setValueAtTime(freq,ctx.currentTime+index*.05);osc.connect(gain);osc.start(ctx.currentTime+index*.05);osc.stop(ctx.currentTime+.7)});setTimeout(()=>ctx.close(),800)}catch(e){}}function paperCardSound(){try{const Ctx=window.AudioContext||window.webkitAudioContext;const ctx=new Ctx();const length=Math.floor(ctx.sampleRate*.16);const buffer=ctx.createBuffer(1,length,ctx.sampleRate);const data=buffer.getChannelData(0);for(let i=0;i<length;i++)data[i]=(Math.random()*2-1)*(1-i/length);const source=ctx.createBufferSource();source.buffer=buffer;const filter=ctx.createBiquadFilter();filter.type='bandpass';filter.frequency.value=850;filter.Q.value=.7;const gain=ctx.createGain();gain.gain.setValueAtTime(.0001,ctx.currentTime);gain.gain.exponentialRampToValueAtTime(.045,ctx.currentTime+.012);gain.gain.exponentialRampToValueAtTime(.0001,ctx.currentTime+.17);source.connect(filter);filter.connect(gain);gain.connect(ctx.destination);source.start();setTimeout(()=>ctx.close(),250)}catch(e){}}function playSound(name){if(!soundOn)return;if(name==='turn'){softTurnChime();return}if(name==='card'){paperCardSound();return}const base=soundPool[name];if(!base)return;const audio=base.cloneNode();audio.volume=base.volume;try{const pr=audio.play();if(pr&&typeof pr.catch==='function')pr.catch(()=>{})}catch(e){}}
function wsUrl(room){return `${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/${encodeURIComponent(room)}`}
/* ---------- Комната берётся из ссылки: делиться = скинуть URL ---------- */
function roomFromUrl(){
  const p=new URLSearchParams(location.search).get('room');
  if(p)return p.trim().slice(0,32);
  const h=location.hash.replace(/^#\/?/,'').trim();
  return h?h.slice(0,32):'';
}
function makeRoomCode(){
  const words=['kotel','zhaba','griby','chipsy','vopli','loshara','magiya','vihr','peklo','sopli'];
  return words[Math.floor(Math.random()*words.length)]+'-'+Math.floor(1000+Math.random()*9000);
}
function inviteUrl(room){return `${location.origin}${location.pathname}?room=${encodeURIComponent(room)}`}
function setupInvite(){
  roomId=roomFromUrl();
  const fresh=!roomId;
  if(fresh){roomId=makeRoomCode();history.replaceState(null,'',inviteUrl(roomId))}
  $('room-input').value=roomId;
  const link=inviteUrl(roomId);
  const box=$('room-invite'); if(box)box.classList.remove('hidden');
  const f=$('invite-link'); if(f)f.value=link;
  const l=$('lobby-link'); if(l)l.value=link;
  $('join-btn').textContent=fresh?'Создать игру':'Присоединиться';
  // Имя запоминаем: второй раз вводить не надо.
  const savedName=localStorage.getItem('krutagidon_name');
  if(savedName&&!$('name-input').value)$('name-input').value=savedName;
}
function copyLink(input,btn){
  if(!input)return;
  input.select();
  const done=()=>{const t=btn.textContent;btn.textContent='Скопировано ✓';setTimeout(()=>btn.textContent=t,1500)};
  if(navigator.clipboard?.writeText)navigator.clipboard.writeText(input.value).then(done).catch(()=>{try{document.execCommand('copy');done()}catch(e){}});
  else{try{document.execCommand('copy');done()}catch(e){}}
}
/* ---------- Подключение с авто-восстановлением ---------- */
let reconnectTimer=null,reconnectTries=0,wantConnection=false,keepAliveTimer=null;
function connect(name){
  const saved=localStorage.getItem('krutagidon_pid_'+roomId);
  ws=new WebSocket(wsUrl(roomId));
  ws.onopen=()=>{
    reconnectTries=0;setLinkState(true);
    ws.send(JSON.stringify({name,avatar:chosenAvatar,player_id:saved||undefined}));
    // Туннели (CloudPub и др.) рвут «молчащее» соединение — шлём пинг.
    clearInterval(keepAliveTimer);
    keepAliveTimer=setInterval(()=>{
      if(ws&&ws.readyState===1){try{ws.send(JSON.stringify({action:'ping'}))}catch(e){}}
    },20000);
  };
  ws.onmessage=e=>handleMessage(JSON.parse(e.data));
  ws.onclose=()=>{
    clearInterval(keepAliveTimer);
    setLinkState(false);
    if(!wantConnection){$('join-btn').disabled=false;$('join-btn').textContent='Играть';return}
    // Связь оборвалась — молча пробуем вернуться, партия ждёт на паузе.
    reconnectTries++;
    const delay=Math.min(1000*reconnectTries,5000);
    clearTimeout(reconnectTimer);
    reconnectTimer=setTimeout(()=>connect(name),delay);
  };
}
function setLinkState(online){
  const b=document.getElementById('link-state');
  if(!b)return;
  b.textContent=online?'':'нет связи — восстанавливаем…';
  b.classList.toggle('hidden',online);
}
$("join-btn").onclick=()=>{
  const name=$("name-input").value.trim()||'Колдун';
  localStorage.setItem('krutagidon_name',name);
  if(!roomId)setupInvite();
  wantConnection=true;
  $("join-btn").disabled=true;$("join-btn").textContent='Подключаемся…';
  connect(name);
};
$("name-input")?.addEventListener('keydown',e=>{if(e.key==='Enter')$('join-btn').click()});
function handleMessage(msg){if(msg.type==='pong'){return}if(msg.type==='to_lobby'){returnToLobby();return}if(msg.type==='kicked'){handleKicked(msg);return}if(msg.type==='joined'){myId=msg.player_id;localStorage.setItem('krutagidon_pid_'+roomId,myId);$('lobby-room-code').textContent=roomId;$('room-code-game').textContent=roomId;const l=$('lobby-link');if(l)l.value=inviteUrl(roomId);if(!msg.returning)show('lobby-screen')}else if(msg.type==='lobby'){renderLobby(msg);if(msg.started)show('game-screen')}else if(msg.type==='state'){const motion=captureVisualMotion(msg.state.visual_event);lastState=msg.state;show('game-screen');render(msg.state);prepareVisualMotion(motion);requestAnimationFrame(()=>playVisualMotion(motion,msg.state.visual_event))}else if(msg.type==='error'){playSound('error');alert(msg.message)}}
function show(id){['join-screen','lobby-screen','game-screen'].forEach(s=>$(s).classList.toggle('hidden',s!==id))}
/* Хост убрал игрока из комнаты: не переподключаемся молча (v74) */
function handleKicked(msg){
  wantConnection=false;                    // иначе автореконнект вернёт нас обратно
  clearTimeout(reconnectTimer);
  localStorage.removeItem('krutagidon_pid_'+roomId);
  try{ws&&ws.close()}catch(e){}
  playSound('error');
  alert(msg.message||'Хост убрал тебя из комнаты');
  show('join-screen');
  const btn=$('join-btn');
  if(btn){btn.disabled=false;btn.textContent='Играть'}
}
/* Хост нажал «Все в лобби»: чистим стол и показываем комнату (v73) */
function returnToLobby(){
  ['gameover-modal','event-modal','decision-modal','target-modal','attack-modal',
   'wild-modal','tokens-modal','card-modal','confirm-act-modal','confirm-fam-modal',
   'pay-modal','pause-overlay','burn-layer'].forEach(id=>{
    const el=$(id);if(el)el.classList.add('hidden');
  });
  // Сбрасываем состояние партии, иначе новая начнётся с чужими данными.
  announcedGameOver=false;lastState=null;lastTurnPlayer=null;
  lastToastSequence=0;lastVisualSequence=0;lastBurstKey='';
  lastDestroySeq=0;burnQueue=[];burnBusy=false;
  deferredAttackMode=false;wildTargetMode=false;
  pendingTargetCard=null;pendingAttackChoice=null;permanentActivationCard=null;
  show('lobby-screen');
}
function renderLobby(msg){renderLobbyPlayers(msg);const hasProperty=Boolean(msg.selected_property_id);$('familiar-picker').classList.toggle('hidden',!hasProperty);if(hasProperty){const selected=msg.selected_familiar_ids||[];$('familiar-choice-title').textContent=msg.familiar_required===3?`Выбери фамильяров: ${selected.length}/3`:`Выбери одного фамильяра: ${selected.length}/1`;$('familiar-options').replaceChildren(...msg.familiar_choices.map(board=>familiarButton(board,selected)))}$('property-options').replaceChildren(...msg.property_choices.map(p=>propertyButton(p,msg.selected_property_id)));$('start-btn').disabled=msg.players.some(p=>!p.ready);$('host-settings').classList.toggle('hidden',!msg.is_host);$('add-bot-btn').classList.toggle('hidden',!msg.is_host);if(msg.is_host){$('zhdk-mode').value=msg.settings?.zhdk_mode||'standard';$('zhdk-custom').classList.toggle('hidden',$('zhdk-mode').value!=='custom');if(msg.settings?.zhdk_count)$('zhdk-custom').value=msg.settings.zhdk_count}}
/* Список игроков в лобби. У хоста рядом с каждым — кнопка «выгнать» (v74) */
function renderLobbyPlayers(msg){
  const list=$('lobby-players');
  const iamHost=Boolean(msg.is_host);
  list.replaceChildren(...msg.players.map(p=>{
    const li=document.createElement('li');
    li.className='lobby-player'+(p.is_bot?' is-bot':'');
    const canKick=iamHost&&p.id!==msg.host_id;
    li.innerHTML=`
      <span class="lp-who">${escapeHtml(p.avatar||'🧙')} ${escapeHtml(p.name)}${p.id===msg.host_id?' · хост':''}${p.id===myId?' · ты':''}</span>
      <span class="lp-state ${p.ready?'ready':''}">${p.ready?'✓ готов':'выбирает свойство / фамильяра'}</span>`;
    if(canKick){
      const btn=document.createElement('button');
      btn.className='lp-kick';btn.type='button';
      btn.title=`Убрать ${p.name} из комнаты`;
      btn.textContent='✕';
      btn.onclick=()=>{
        if(!confirm(`Убрать ${p.name} из комнаты?`))return;
        playSound('click');
        ws.send(JSON.stringify({action:'kick_player',player_id:p.id}));
      };
      li.appendChild(btn);
    }
    return li;
  }));
}
function boardToCard(board){return {id:board.familiar_id||board.id,name:board.familiar_name,type:board.type||'Фамильяр',cost:board.cost||0,power:board.power||0,vp:board.vp||0,text:board.familiar_text||''}}
function familiarButton(board,selected){
  const isPicked=selected.includes(board.id);
  const el=document.createElement('div');
  el.className='familiar-option'+(isPicked?' selected':'');
  const src=`assets/cards/${encodeURIComponent(board.id)}.webp`;
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
  const src=`assets/cards/${encodeURIComponent(board.id)}.webp`;
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
function sendRoomSettings(){ws.send(JSON.stringify({action:'configure_room',zhdk_mode:$('zhdk-mode').value,zhdk_count:$('zhdk-custom').value}));playSound('click')}$('zhdk-mode').onchange=()=>{$('zhdk-custom').classList.toggle('hidden',$('zhdk-mode').value!=='custom');if($('zhdk-mode').value!=='custom')sendRoomSettings()};$('zhdk-custom').onchange=sendRoomSettings;$('save-room-settings').onclick=sendRoomSettings;$('info-close').onclick=()=>$('info-modal').classList.add('hidden');function showInfo(title,text){$('info-title').textContent=title;$('info-text').textContent=text;$('info-modal').classList.remove('hidden')}$('card-close').onclick=()=>$('card-modal').classList.add('hidden');function showCard(card){$('inspect-type').textContent=card.type||'Карта';$('inspect-name').textContent=card.name;$('inspect-stats').innerHTML=`<b>◉ ${card.cost}</b><b>⚡ +${card.power}</b><b>★ ${card.vp||0} ПО</b>`;$('inspect-text').textContent=card.text||'';const visual=cardEl(card,null);visual.classList.add('inspect-card');$('inspect-card').replaceChildren(visual);$('card-modal').classList.remove('hidden')}$('event-continue').onclick=()=>{
  // Гасим кнопку сразу: два клика подряд слали второй resolve_event в пустоту.
  const btn=$('event-continue');
  if(btn.disabled)return;
  btn.disabled=true;
  playSound('drawer');
  ws.send(JSON.stringify({action:'resolve_event'}));
};$('sound-toggle').textContent=soundOn?'🔊':'🔇';$('sound-toggle').onclick=()=>{soundOn=!soundOn;localStorage.setItem('krutagidon_sound',soundOn?'on':'off');$('sound-toggle').textContent=soundOn?'🔊':'🔇';if(soundOn)playSound('click')};$('add-bot-btn').onclick=()=>{playSound('click');ws.send(JSON.stringify({action:'add_bot'}))};$('start-btn').onclick=()=>{playSound('click');ws.send(JSON.stringify({action:'start_game'}));};$('end-turn-btn').onclick=()=>ws.send(JSON.stringify({action:'end_turn'}));$('buy-wild-btn').onclick=()=>ws.send(JSON.stringify({action:'buy_wild_magic'}));$('buy-familiar-btn').onclick=()=>{
  const me=lastState?.players.find(p=>p.id===myId);
  const bought=me?.bought_familiars||[];
  const list=(me?.familiars||[]).filter(f=>!bought.includes(f.id));
  if(list.length<=1){ws.send(JSON.stringify({action:'buy_familiar',card_id:list[0]?.id}));return}
  // Фамильяров несколько — даём выбрать, кого именно покупаем.
  const eb=$('tokens-eyebrow');if(eb)eb.textContent='КУПИТЬ ФАМИЛЬЯРА · 6 МОЩИ';
  $('tokens-title').textContent='Кого берём?';
  $('tokens-list').innerHTML=list.map((f,i)=>`
    <button class="fam-line" data-i="${i}">
      <img src="assets/cards/${encodeURIComponent(f.id)}.webp" alt="">
      <span><b>${escapeHtml(f.name)}</b><small>${escapeHtml((f.text||'').slice(0,150))}</small></span>
    </button>`).join('');
  $('tokens-list').querySelectorAll('.fam-line').forEach(b=>{
    b.onclick=()=>{
      $('tokens-modal').classList.add('hidden');
      playSound('click');
      ws.send(JSON.stringify({action:'buy_familiar',card_id:list[Number(b.dataset.i)].id}));
    };
  });
  $('tokens-modal').classList.remove('hidden');
};$('target-cancel').onclick=closeTargetModal;$('attack-cancel').onclick=()=>$('attack-modal').classList.add('hidden');$('attack-later').onclick=()=>{sendPlay(pendingAttackChoice,{defer_attack:true});$('attack-modal').classList.add('hidden')};$('attack-now').onclick=()=>{const card=pendingAttackChoice;$('attack-modal').classList.add('hidden');playAttackNow(card)};$('wild-cancel').onclick=()=>$('wild-modal').classList.add('hidden');$('wild-power').onclick=()=>{sendPlay({id:'spec_wild'}, {choice:'power'});$('wild-modal').classList.add('hidden')};$('wild-steal').onclick=()=>{wildTargetMode=true;$('wild-modal').classList.add('hidden');openTargetModal({id:'spec_wild',name:'Шальная магия'})};$('log-toggle').onclick=()=>document.querySelector('.event-feed').classList.add('open');$('log-close').onclick=()=>document.querySelector('.event-feed').classList.remove('open');document.querySelectorAll('.drawer-tab').forEach(tab=>tab.onclick=()=>{playSound('drawer');tab.closest('.market-drawer').classList.toggle('open')});document.addEventListener('contextmenu',event=>{const card=event.target.closest?.('.card');if(card?._cardData){event.preventDefault();showCard(card._cardData)}else event.preventDefault()},true);document.addEventListener('dragstart',event=>event.preventDefault(),true);
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
    // Карта может лежать в рынке, в зале легенд ИЛИ быть кнопкой сбоку
    // (Шальная магия, фамильяр) — иначе покупка выглядела бы «ничем».
    let el=elementFor(`#market .card[data-card-id="${CSS.escape(card.id)}"],#legend-market .card[data-card-id="${CSS.escape(card.id)}"]`);
    if(!el&&card.id==='spec_wild')el=elementFor('#buy-wild-btn');
    if(!el)el=elementFor('#buy-familiar-btn');
    if(el)source={from:el.getBoundingClientRect(),clone:el.cloneNode(true)};
    target=buyTarget(event.player_id);
  }else if(event.type==='discard'){
    const el=elementFor(`#played-cards .card[data-card-id="${CSS.escape(card.id)}"]`);
    if(el)source={from:el.getBoundingClientRect(),clone:el.cloneNode(true)};
    target=buyTarget(event.player_id);
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
  if(event?.type==='defend')showDefendFx(event);
  if(event?.type==='turn'){
    const overlay=$('turn-overlay');overlay.textContent=`ХОД ИГРОКА ${event.player||''}`;overlay.classList.remove('hidden');setTimeout(()=>overlay.classList.add('hidden'),1300);
  }
}
/* ---------- Счётчики стопок и диагностика (v43) ---------- */
const BUILD_TAG='v74';
function setPileCounts(me){
  const d=$('self-deck-count'),c=$('self-discard-count');
  if(d)d.textContent=(me&&Number.isFinite(me.deck_count))?me.deck_count:0;
  if(c)c.textContent=(me&&Number.isFinite(me.discard_count))?me.discard_count:0;
  const img=$('self-discard-card');
  if(img){
    if(me&&me.discard_top)img.src=`assets/cards/${encodeURIComponent(me.discard_top.id)}.webp`;
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
document.addEventListener('DOMContentLoaded',()=>{const b=$('tokens-close');if(b)b.onclick=()=>$('tokens-modal').classList.add('hidden')});
document.addEventListener('DOMContentLoaded',()=>{
  setupInvite();
  $('copy-link')?.addEventListener('click',()=>copyLink($('invite-link'),$('copy-link')));
  $('lobby-copy')?.addEventListener('click',()=>copyLink($('lobby-link'),$('lobby-copy')));
  const send=()=>{if(ws&&ws.readyState===1){playSound('click');ws.send(JSON.stringify({action:'toggle_pause'}))}};
  $('pause-btn')?.addEventListener('click',send);
  $('pause-resume')?.addEventListener('click',send);
});
document.addEventListener('DOMContentLoaded',()=>{const b=$('gameover-close');if(b)b.onclick=()=>$('gameover-modal').classList.add('hidden')});
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
/* Экран итогов вместо alert — v51 */
function showGameOver(state){
  const rows=state.final_scores||[];
  const modal=$('gameover-modal');
  $('gameover-winner').textContent='Подсчёт очков…';
  $('gameover-table').innerHTML=rows.map(r=>`
    <div class="score-row" data-pid="${r.id}">
      <span class="score-place">·</span>
      <span class="score-ava">${escapeHtml(r.avatar||'')}</span>
      <span class="score-name">${escapeHtml(r.name)}${r.id===myId?' · Ты':''}</span>
      <span class="score-sub"></span>
      <span class="score-vp">0</span>
    </div>`).join('');
  $('gameover-close').classList.add('hidden');
  modal.classList.remove('hidden');
  countUpScores(state,rows);
}
/* Очки набегают по статьям — интрига до последней карты (v62) */
function countUpScores(state,rows){
  const running={};rows.forEach(r=>running[r.id]=0);
  // все шаги всех игроков вперемешку по порядку статей
  // Пояснения вида «↳ в том числе фамильяр» очков не меняют — в бегущий
  // подсчёт их не берём, они видны только в развёрнутой разбивке.
  const scoring=r=>(r.steps||[]).filter(s=>s.kind!=='note');
  const maxSteps=Math.max(0,...rows.map(r=>scoring(r).length));
  const queue=[];
  for(let i=0;i<maxSteps;i++)rows.forEach(r=>{const st=scoring(r)[i];if(st)queue.push({pid:r.id,st})});
  let k=0;
  const tick=()=>{
    if(k>=queue.length){finishCount(state,rows);return}
    const {pid,st}=queue[k++];
    running[pid]+=st.delta;
    const row=$('gameover-table').querySelector(`[data-pid="${CSS.escape(pid)}"]`);
    if(row){
      const vp=row.querySelector('.score-vp');
      vp.textContent=running[pid];
      vp.classList.remove('bump-good','bump-bad');
      void vp.offsetWidth;
      vp.classList.add(st.delta>0?'bump-good':'bump-bad');
      const sub=row.querySelector('.score-sub');
      sub.textContent=`${st.delta>0?'+':''}${st.delta} · ${st.label}`;
      sub.classList.remove('flash');void sub.offsetWidth;sub.classList.add('flash');
      row.classList.add('is-active');
      setTimeout(()=>row.classList.remove('is-active'),700);
    }
    playSound('click');
    setTimeout(tick,760);
  };
  setTimeout(tick,900);
}
function finishCount(state,rows){
  const win=state.players.find(p=>p.id===state.winner);
  const table=$('gameover-table');
  rows.forEach((r,i)=>{
    const row=table.querySelector(`[data-pid="${CSS.escape(r.id)}"]`);
    if(!row)return;
    row.querySelector('.score-place').textContent=i+1;
    row.querySelector('.score-vp').textContent=`${r.vp} ПО`;
    row.querySelector('.score-sub').textContent=`легенд ${r.legends} · ЖДК ${r.death_tokens} · нажми ▾`;
    row.querySelector('.score-sub').classList.remove('flash');
    if(r.id===state.winner)row.classList.add('is-winner');
    // Разворачиваем подробный список: за что именно начислены очки.
    row.classList.add('is-expandable');
    if(!row.querySelector('.score-details')){
      const det=document.createElement('div');
      det.className='score-details hidden';
      det.innerHTML=(r.steps||[]).map(st=>st.kind==='note'
        ? `<div class="detail-line note">
             <span>${escapeHtml(st.label)}</span><b>${escapeHtml(st.note||'')}</b>
           </div>`
        : `<div class="detail-line ${st.delta>0?'plus':'minus'}">
             <span>${escapeHtml(st.label)}</span><b>${st.delta>0?'+':''}${st.delta}</b>
           </div>`).join('')||'<div class="detail-line"><span>Нет начислений</span><b>0</b></div>';
      det.innerHTML+=`<div class="detail-line total"><span>Итого</span><b>${r.vp} ПО</b></div>`;
      row.appendChild(det);
    }
    row.onclick=()=>{
      const det=row.querySelector('.score-details');
      if(!det)return;
      det.classList.toggle('hidden');
      row.classList.toggle('is-open',!det.classList.contains('hidden'));
    };
  });
  setTimeout(()=>{
    $('gameover-winner').textContent=win?`Победитель: ${win.name}`:'Игра окончена';
    $('gameover-winner').classList.add('reveal');
    $('gameover-close').classList.remove('hidden');
    // Кнопка «в лобби» — только у хоста. Он жмёт, и уходят ВСЕ.
    const lob=$('gameover-lobby');
    if(lob){
      const isHost=Boolean(state.is_host);
      lob.classList.toggle('hidden',!isHost);
      lob.onclick=()=>{playSound('click');ws.send(JSON.stringify({action:'return_to_lobby'}))};
      const note=$('gameover-note');
      if(note){
        note.textContent=isHost?'Нажми «Все в лобби» — и вся компания вернётся в комнату для новой партии.'
                               :'Ждём хоста: он вернёт всех в лобби для новой партии.';
        note.classList.remove('hidden');
      }
    }
    playSound('turn');
  },700);
}

/* ---------- Пауза: партия ждёт, никто ничего не теряет ---------- */
function renderPause(state){
  const info=state.pause||{};
  const overlay=$('pause-overlay');
  if(!overlay)return;
  overlay.classList.toggle('hidden',!info.paused);
  if(info.paused){
    const manual=info.kind==='manual';
    $('pause-title').textContent=manual?'Перерыв':'Ждём игрока';
    $('pause-reason').textContent=info.reason||'';
    // Снять можно только ручную паузу: отключившегося надо дождаться.
    $('pause-resume').classList.toggle('hidden',!manual);
  }
  const btn=$('pause-btn');
  if(btn){btn.textContent=info.paused?'▶':'⏸';btn.title=info.paused?'Продолжить игру':'Перерыв — поставить игру на паузу';}
}
/* Список жетонов ЖДК: у части из них постоянные эффекты — v54 */
function showTokens(player){
  const eb=$('tokens-eyebrow');if(eb)eb.textContent='ЖЕТОНЫ ДОХЛОГО КОЛДУНА';
  const list=player.death_token_cards||[];
  $('tokens-title').textContent=`Жетоны: ${escapeHtml(player.name)}`;
  $('tokens-list').innerHTML=list.length?list.map(t=>`
    <div class="token-row${t.permanent?' is-permanent':''}">
      <div class="token-head"><b>${escapeHtml(t.name)}</b><span>${t.vp} ПО</span></div>
      ${t.permanent?'<div class="token-flag">Действует постоянно</div>':''}
      <p>${escapeHtml(t.text||'')}</p>
    </div>`).join(''):'<p>Жетонов пока нет.</p>';
  $('tokens-modal').classList.remove('hidden');
}
/* Список фамильяров, если их несколько (свойство «Фамильяры») — v57 */
function showFamiliars(player,list){
  const eb=$('tokens-eyebrow');if(eb)eb.textContent='ФАМИЛЬЯРЫ';
  $('tokens-title').textContent=`Фамильяры: ${escapeHtml(player.name)}`;
  $('tokens-list').innerHTML=list.map((f,i)=>`
    <button class="fam-line" data-i="${i}">
      <img src="assets/cards/${encodeURIComponent(f.id)}.webp" alt="">
      <span><b>${escapeHtml(f.name)}</b><small>${escapeHtml((f.text||'').slice(0,150))}</small></span>
    </button>`).join('');
  $('tokens-list').querySelectorAll('.fam-line').forEach(b=>{
    b.onclick=()=>{$('tokens-modal').classList.add('hidden');showCard(list[Number(b.dataset.i)])};
  });
  $('tokens-modal').classList.remove('hidden');
}
let lastBurstKey='';
/* Извержение «БЕСПРЕДЕЛ!»: вспышка + тряска стола + надпись снизу вверх — v58 */
function playBespredelBurst(isMega){
  const box=$('besp-burst');
  if(!box)return;
  box.classList.toggle('is-mega',Boolean(isMega));
  box.querySelector('.besp-word').innerHTML=(isMega?'МЕГАБЕСПРЕДЕЛ!':'БЕСПРЕДЕЛ!')
    .split('').map((ch,i)=>`<span style="animation-delay:${120+i*45}ms">${ch}</span>`).join('');
  // перезапуск анимации
  box.classList.remove('hidden');box.classList.remove('run');
  void box.offsetWidth;
  box.classList.add('run');
  const shell=document.querySelector('.board-shell');
  if(shell){shell.classList.remove('quake');void shell.offsetWidth;shell.classList.add('quake');
    setTimeout(()=>shell.classList.remove('quake'),900)}
  playSound('turn');
  clearTimeout(playBespredelBurst._t);
  playBespredelBurst._t=setTimeout(()=>{box.classList.add('hidden');box.classList.remove('run')},3600);
}
/* Куда летят купленные и сброшенные карты. Раньше целью был .discard-stat,
   которого в вёрстке нет, — анимация просто не проигрывалась. */
function buyTarget(playerId){
  if(playerId===myId&&document.getElementById('self-discard-pile'))return '#self-discard-pile';
  return `.opp-card[data-player-id="${CSS.escape(playerId)}"] .familiar-card`;
}
/* Нужна ли карте цель. Раньше искали только слово «выбранн» — из-за этого
   «Повелитель шкурок» («выбери правого или левого врага») бил молча. */
const NO_TARGET_IDS=new Set(['leg_minigun','leg_necrorot','fam_weaboo','leg_hemor']);
function cardNeedsTarget(card){
  if(!card)return false;
  if(NO_TARGET_IDS.has(card.id))return false;
  const t=(card.text||'').toLowerCase();
  if(/кажд(ый|ому|ого) (колдун|враг)/.test(t))return false;   // бьёт по всем
  return /выбранн|выбери|левому|правому|левого|правого/.test(t);
}
/* ---------- СОЖЖЕНИЕ КАРТЫ (v73) ----------
   Уничтоженную карту показываем ВСЕМ: крупная картинка, название, текст,
   кто её потерял и почему. Карта обугливается и осыпается пеплом.
   Очередь: несколько уничтожений подряд проигрываются по одному. */
let lastDestroySeq=0,burnQueue=[],burnBusy=false;
function renderDestroyReel(reel){
  if(!Array.isArray(reel)||!reel.length)return;
  const fresh=reel.filter(d=>d&&d.seq>lastDestroySeq);
  if(!fresh.length)return;
  lastDestroySeq=Math.max(...reel.map(d=>d.seq||0));
  fresh.forEach(d=>burnQueue.push(d));
  pumpBurnQueue();
}
function pumpBurnQueue(){
  if(burnBusy||!burnQueue.length)return;
  burnBusy=true;
  playBurnCard(burnQueue.shift(),()=>{burnBusy=false;pumpBurnQueue()});
}
function playBurnCard(info,done){
  const layer=$('burn-layer');
  if(!layer){done();return}
  const COLS=4,ROWS=6;                    // на сколько кусков ломаем карту
  layer.innerHTML=`
    <div class="burn-stage">
      <div class="burn-eyebrow">КАРТА УНИЧТОЖЕНА</div>
      <div class="burn-card">
        <div class="burn-whole"><img alt=""></div>
        <div class="burn-shards"></div>
        <div class="burn-flash"></div>
      </div>
      <div class="burn-copy">
        <div class="burn-name">${escapeHtml(info.name||'Карта')}</div>
        <div class="burn-type">${escapeHtml(info.type||'')}</div>
        <div class="burn-text">${escapeHtml((info.text||'').slice(0,190))}</div>
        <div class="burn-reason">${escapeHtml(info.reason||'')}</div>
      </div>
    </div>`;
  const whole=layer.querySelector('.burn-whole');
  const img=whole.querySelector('img');
  let srcUsed=null;
  attachCardImage(img,info.card_id,()=>{
    // Картинки нет — ломаем текстовую карточку, эффект тот же.
    whole.innerHTML=`<div class="burn-fallback"><b>${escapeHtml(info.name||'')}</b><small>${escapeHtml((info.text||'').slice(0,110))}</small></div>`;
  });

  layer.classList.remove('hidden');
  void layer.offsetWidth;
  layer.classList.add('run');
  playSound('error');

  // Осколки строим, когда известен реальный размер карты.
  const buildShards=()=>{
    const box=layer.querySelector('.burn-card');
    const shards=layer.querySelector('.burn-shards');
    if(!box||!shards)return;
    const W=box.clientWidth,H=box.clientHeight;
    if(!W||!H)return;
    srcUsed=img&&img.getAttribute('src');
    const tileW=W/COLS,tileH=H/ROWS;
    const frag=document.createDocumentFragment();
    for(let r=0;r<ROWS;r++)for(let c=0;c<COLS;c++){
      const sh=document.createElement('div');
      sh.className='shard';
      sh.style.left=`${c*tileW}px`;   sh.style.top=`${r*tileH}px`;
      sh.style.width=`${tileW}px`;    sh.style.height=`${tileH}px`;
      // Кусок картинки: та же картинка, сдвинутая так, чтобы попал нужный фрагмент.
      if(srcUsed){
        const im=document.createElement('img');
        im.src=srcUsed;
        im.style.width=`${W}px`;im.style.height=`${H}px`;
        im.style.left=`${-c*tileW}px`;im.style.top=`${-r*tileH}px`;
        sh.appendChild(im);
      }else{
        sh.style.background='linear-gradient(150deg,#4a2a52,#20122a)';
        sh.style.boxShadow='inset 0 0 0 1px #e0a94f55';
      }
      // Рваный край: слегка «покусанный» четырёхугольник вместо ровного квадрата.
      const j=()=>(Math.random()*16).toFixed(1);
      sh.style.setProperty('--clip',
        `${j()}% ${j()}%, ${100-j()}% ${j()}%, ${100-j()}% ${100-j()}%, ${j()}% ${100-j()}%`);
      // Разлёт: от центра карты наружу + случайный доворот.
      const cx=(c+0.5)/COLS-0.5, cy=(r+0.5)/ROWS-0.5;
      const push=170+Math.random()*190;
      sh.style.setProperty('--tx',`${(cx*push*2.1+(Math.random()*40-20)).toFixed(0)}px`);
      sh.style.setProperty('--ty',`${(cy*push*1.5+90+Math.random()*70).toFixed(0)}px`);
      sh.style.setProperty('--rot',`${(Math.random()*150-75).toFixed(0)}deg`);
      sh.style.setProperty('--sc',(0.45+Math.random()*0.3).toFixed(2));
      sh.style.setProperty('--ang',`${Math.floor(Math.random()*360)}deg`);
      sh.style.setProperty('--dur',`${(1.25+Math.random()*0.55).toFixed(2)}s`);
      // Куски снизу срываются первыми — карта «оседает».
      sh.style.setProperty('--delay',`${(1.16+(ROWS-1-r)*0.035+Math.random()*0.07).toFixed(2)}s`);
      frag.appendChild(sh);
    }
    shards.appendChild(frag);
  };
  // Ждём загрузку картинки, но не дольше 600 мс — эффект важнее.
  if(img&&!img.complete){
    let built=false;
    const once=()=>{if(built)return;built=true;buildShards()};
    img.addEventListener('load',once,{once:true});
    img.addEventListener('error',()=>setTimeout(once,60),{once:true});
    setTimeout(once,600);
  }else{
    requestAnimationFrame(buildShards);
  }

  clearTimeout(playBurnCard._t);
  playBurnCard._t=setTimeout(()=>{
    layer.classList.remove('run');
    layer.classList.add('hidden');
    layer.innerHTML='';
    done();
  },3400);
}
/* Щит над игроком, когда он отбил атаку — v70 */
function showDefendFx(event){
  const card=event.cards&&event.cards[0];
  const row=document.querySelector(`.opp-card[data-player-id="${CSS.escape(event.player_id)}"]`);
  if(row){
    const fx=document.createElement('div');
    fx.className='defend-fx';
    fx.innerHTML='<span class="shield">🛡</span>';
    row.appendChild(fx);
    setTimeout(()=>fx.remove(),1800);
  }
  if(card){
    const t=$('activity-toast');
    if(t){
      t.innerHTML=`<b>${escapeHtml(event.player||'Игрок')} защитился!</b><br>«${escapeHtml(card.name)}» — ${escapeHtml((card.text||'').slice(0,90))}`;
      t.classList.remove('hidden');
      clearTimeout(showDefendFx._t);
      showDefendFx._t=setTimeout(()=>t.classList.add('hidden'),3200);
    }
  }
}
/* Постоянки соседа: клик по его планшету */
function showPermanents(player){
  const list=player.zone_in_play||[];
  const eb=$('tokens-eyebrow');if(eb)eb.textContent='ПОСТОЯНКИ НА СТОЛЕ';
  $('tokens-title').textContent=`Постоянки: ${escapeHtml(player.name)}`;
  $('tokens-list').innerHTML=list.length?list.map((c,i)=>`
    <button class="fam-line" data-i="${i}">
      <img src="assets/cards/${encodeURIComponent(c.id)}.webp" alt="">
      <span><b>${escapeHtml(c.name)}</b><small>${escapeHtml((c.text||'').slice(0,150))}</small></span>
    </button>`).join(''):'<p>Постоянок нет.</p>';
  $('tokens-list').querySelectorAll('.fam-line').forEach(b=>{
    b.onclick=()=>{$('tokens-modal').classList.add('hidden');showCard(list[Number(b.dataset.i)])};
  });
  $('tokens-modal').classList.remove('hidden');
}
/* Чем платим за карту: мощь, чипсины или пополам */
function askPayment(card,onPay){
  const me=lastState?.players.find(p=>p.id===myId);
  if(!me)return;
  let cost=card.cost;
  if(me.property_id==='svo_1'&&/Сокровище/.test(card.type||''))cost=Math.max(0,cost-1);
  const power=me.power_available,chips=me.chipsines;
  // Чипсинами платят только за легенды и фамильяров.
  const isLegend=/Легенда/.test(card.type||'')||(lastState?.legend_market||[]).some(c=>c.id===card.id);
  if(!isLegend){
    if(cost>power){alert('За эту карту чипсинами платить нельзя — не хватает мощи');return}
    onPay(0);return;
  }
  const minChips=Math.max(0,cost-power);
  if(minChips>chips){alert('Не хватает мощи и чипсин');return}
  const maxChips=Math.min(chips,cost);
  // Даже когда мощи хватает, игрок может доплатить чипсинами и сберечь
  // мощь на вторую покупку — это тактика, отбирать её нельзя.
  // Спрашиваем всегда, кроме случая, когда выбора реально нет.
  if(minChips===maxChips){onPay(minChips);return}
  $('pay-title').textContent=card.name;
  $('pay-sub').textContent=`Стоимость ${cost} · у тебя ${power} мощи и ${chips} чипсин`;
  // Ползунок: игрок сам решает, сколько чипсин отдать.
  $('pay-options').innerHTML=`
    <div class="pay-slider">
      <div class="pay-readout"><b id="pay-pw">⚡ ${cost-minChips}</b><span>+</span><b id="pay-ch">◉ ${minChips}</b></div>
      <input id="pay-range" type="range" min="${minChips}" max="${maxChips}" value="${minChips}" step="1">
      <div class="pay-left" id="pay-left"></div>
      <div class="pay-hint">Двигай: слева — больше мощи, справа — больше чипсин</div>
      <button id="pay-go" class="button-primary">Купить</button>
    </div>`;
  const rng=$('pay-range');
  const upd=()=>{
    const ch=Number(rng.value);
    $('pay-pw').textContent=`⚡ ${cost-ch}`;
    $('pay-ch').textContent=`◉ ${ch}`;
    // Показываем остаток: на него можно взять ещё карту в этом же ходу.
    $('pay-left').textContent=`После покупки останется: ⚡ ${power-(cost-ch)} мощи · ◉ ${chips-ch} чипсин`;
  };
  rng.oninput=upd;upd();
  $('pay-go').onclick=()=>{$('pay-modal').classList.add('hidden');onPay(Number(rng.value))};
  $('pay-modal').classList.remove('hidden');
}
function escapeHtml(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function cardEl(card,onClick){const el=document.createElement('article');el.className='card'+(onClick?' is-actionable':'');el.dataset.cardId=card.id;el.title=`${card.name}\n${card.text||''}`;const img=document.createElement('img');img.className='cart-img';img.alt=card.name;img.loading='lazy';img.onload=()=>el.classList.add('has-image');attachCardImage(img,card.id,()=>{img.remove();el.classList.remove('has-image')});const info=document.createElement('div');info.className='card-info';info.innerHTML=`<div class="cname">${escapeHtml(card.name)}</div><div class="ctext">${escapeHtml((card.text||'').slice(0,128))}</div><div class="cfooter"><span class="cost">◉ ${card.cost}</span><span class="power">⚡ +${card.power}</span></div>`;el._cardData=card;const zoom=document.createElement('button');zoom.className='card-zoom';zoom.type='button';zoom.textContent='⌕';zoom.title='Открыть карту';zoom.onclick=(event)=>{event.stopPropagation();showCard(card)};el.append(img,info,zoom);if(onClick)el.onclick=onClick;return el}
function playerEl(p,isMe,isTurn,seat){
  const el=document.createElement('article');
  el.className='opp-card player-seat seat-'+seat+(isTurn?' active-turn':'')+(p.is_loshara?' loshara-player':'');
  el.dataset.playerId=p.id;
  // Свойство «Фамильяры» даёт три карты — показываем все, что есть.
  const famList=(p.familiars&&p.familiars.length)?p.familiars:(p.familiar?[p.familiar]:[]);
  const hpPercent=Math.max(0,Math.min(100,Math.round((p.life/Math.max(1,p.max_life))*100)));
  el.innerHTML=`
    ${isTurn?`<div class="seat-power">Мощь: <b>${p.power_available}</b></div>`:''}
    ${p.controls_prize?'<img class="player-prize" src="assets/prize/prize.webp" alt="Главный приз" title="Контролирует Главный приз">':''}
    <div class="player-core">
      <div class="avatar-box"><span>${escapeHtml(p.avatar||'🧙')}</span></div>
      <div class="player-main">
        <div class="player-name">${escapeHtml(p.name)}${isMe?' · Ты':''}</div>
        <div class="main-resources"><span class="main-chips"><img src="assets/tokens/chips.webp" alt="">${p.chipsines}</span><span class="main-zhdk${p.death_tokens?' has-tokens':''}" title="${p.death_tokens?'Нажми, чтобы посмотреть жетоны':'Жетонов дохлого колдуна нет'}"><img src="assets/tokens/zdk.webp" alt="">${p.death_tokens}</span></div>
        <div class="hp-bar" title="${p.life}/${p.max_life} HP"><div class="hp-fill" style="width:${hpPercent}%"></div><span>♥ ${p.life}/${p.max_life} HP</span></div>
        ${p.is_loshara?'<div class="loshara-label">ЛОШАРА · максимум 15 HP</div>':''}
      </div>
      <button class="familiar-card" title="${famList.length?escapeHtml(famList[0].name):'Фамильяр'}">${famList.length?`<img src="assets/cards/${encodeURIComponent(famList[0].id)}.webp" alt="${escapeHtml(famList[0].name)}">`:'✦'}${famList.length>1?`<span class="fam-count" title="Всего фамильяров: ${famList.length}">${famList.length}</span>`:''}</button>
    </div>
    ${p.property?`<button class="property-plate" title="${escapeHtml(p.property.name)}">Свойство: ${escapeHtml(p.property.name)}</button>`:''}`;
  const famBtnEl=el.querySelector('.familiar-card');
  if(famBtnEl&&famList.length)famBtnEl.onclick=(event)=>{
    event.stopPropagation();
    if(famList.length>1)showFamiliars(p,famList); else showCard(famList[0]);
  };
  const plate=el.querySelector('.property-plate');
  if(plate)plate.onclick=(event)=>{event.stopPropagation();showInfo(p.property.name,p.property.text||'')};
  const main=el.querySelector('.player-main');
  if(main)main.onclick=(event)=>{event.stopPropagation();showPermanents(p)};
  const zh=el.querySelector('.main-zhdk');
  if(zh&&p.death_tokens)zh.onclick=(event)=>{event.stopPropagation();showTokens(p)};
  return el;
}
function render(state){const me=state.players.find(p=>p.id===myId),active=state.players.find(p=>p.id===state.turn_player_id),myTurn=state.turn_player_id===myId;/* СЧЁТЧИКИ КОЛОДЫ/СБРОСА — В САМОМ НАЧАЛЕ. Никакая ошибка ниже не должна их обнулять. */setPileCounts(me);try{if(lastTurnPlayer&&lastTurnPlayer!==state.turn_player_id)playSound('turn');lastTurnPlayer=state.turn_player_id;renderVisualEvent(state.visual_event);renderDestroyReel(state.destroy_reel);renderEvent(state.pending_event);renderDecision(state.pending_decision);$('turn-banner').textContent=active?(myTurn?'Твой ход — наводи Крутагидон':`Ходит ${active.name}`):'Подготовка';$('log-panel').innerHTML=state.logs.map(l=>`<div>${escapeHtml(l)}</div>`).join('');$('log-panel').scrollTop=$('log-panel').scrollHeight;const seatedPlayers=[...(me?[me]:[]),...state.players.filter(p=>p.id!==myId)];const seatLayouts={1:[0],2:[0,1],3:[0,2,3],4:[0,4,1,5],5:[0,4,2,3,5]};const seats=seatLayouts[seatedPlayers.length]||seatLayouts[5];$('opponents').replaceChildren(...seatedPlayers.map((p,index)=>playerEl(p,p.id===myId,p.id===state.turn_player_id,seats[index])));$('played-cards').replaceChildren(...(active?.played_this_turn||[]).map(c=>cardEl(c,null)));$('main-deck-count').textContent=state.main_deck_count;$('legend-deck-count').textContent=state.legend_deck_count;$('vyal-count').textContent=state.vyal_remaining;$('zhdk-count').textContent=state.undead_stack_count;$('chips-bank-count').textContent=state.chips_bank;$('market').replaceChildren(...state.market.map(c=>cardEl(c,()=>myTurn&&buyCard(c.id))));$('legend-market').replaceChildren(...state.legend_market.map(c=>cardEl(c,()=>myTurn&&buyCard(c.id))));$('buy-wild-btn').disabled=!myTurn;const famBtn=$('buy-familiar-btn');const famLeft=(me?.familiars||[]).filter(f=>!(me?.bought_familiars||[]).includes(f.id));famBtn.disabled=!myTurn||!me||famLeft.length===0;
/* Фамильяр куплен — карточка уходит совсем, Шальная магия занимает её место. */
famBtn.classList.toggle('hidden',famLeft.length===0);
if(famLeft.length){famBtn.innerHTML='<img class="buy-fam-thumb" alt="">';famBtn.title=famLeft.length>1?`Купить фамильяра (${famLeft.length} на выбор) · 6`:`Купить фамильяра: ${famLeft[0].name} · 6`;attachCardImage(famBtn.querySelector('img'),famLeft[0].id);bindPreview(famBtn,()=>famLeft[0]);if(famLeft.length>1)famBtn.innerHTML+=`<b class="fam-left">${famLeft.length}</b>`}else{famBtn.innerHTML=''};$('hand').replaceChildren(...(me?.hand||[]).map(c=>cardEl(c,()=>myTurn&&playCard(c))));$('permanents').replaceChildren(...(me?.zone_in_play||[]).map(c=>cardEl(c,c.activation?()=>activatePermanent(c):null)));$('attack-actions').replaceChildren(...(me?.available_attacks||[]).map(c=>deferredAttackButton(c,myTurn)));$('self-panel').classList.toggle('self-loshara',Boolean(me?.is_loshara));$('self-stats').innerHTML=me?`<div class="self-name">${escapeHtml(me.name)}${me.is_loshara?' · ЛОШАРА':''}${myTurn?' · ТВОЙ ХОД':''}</div><div class="self-meta"><span class="stat-chip health">♥ ${me.life}/${me.max_life} HP</span><span class="stat-chip power">⚡ ${me.power_available} мощи</span></div>`:'';if(me?.discard_top){$('self-discard-card').src=`assets/cards/${encodeURIComponent(me.discard_top.id)}.webp`}else{$('self-discard-card').src='assets/cards/card_closed.webp'}$('prize-supply').classList.toggle('hidden',state.players.some(p=>p.controls_prize));renderPause(state);$('end-turn-btn').disabled=!myTurn||Boolean(state.pause?.paused);if(state.game_over&&!announcedGameOver){announcedGameOver=true;showGameOver(state)}}catch(err){showRenderError(err)}}
function renderVisualEvent(event){const toast=$('activity-toast');if(!event||!event.seq)return;if(event.seq===lastToastSequence)return;lastToastSequence=event.seq;const card=event.cards?.[0];const verb=event.type==='buy'?'покупает':event.type==='play'?'разыгрывает':event.type==='turn'?'получает ход':'заканчивает ход';toast.innerHTML=`<b>${escapeHtml(event.player)}</b> ${verb}${card?`: <span>${escapeHtml(card.name)}</span>`:''}`;toast.classList.remove('hidden');clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.classList.add('hidden'),1500)}
function renderEvent(event){
  const modal=$('event-modal');
  if(!event){modal.classList.add('hidden');return}
  const isToken=(event.type||'').includes('дохлого колдуна');
  $('event-type').textContent=isToken?((event.owner_id===myId?'ТЫ ПОЛУЧАЕШЬ':((event.owner||'Игрок').toUpperCase()+' ПОЛУЧАЕТ'))+' ЖЕТОН'):(event.type||'СОБЫТИЕ');
  $('event-name').textContent=event.name||'Событие';
  $('event-text').textContent=event.text||'';
  // Картинка жетона: показываем, ЧТО именно выпало, а не только имя строкой.
  const art=$('event-art');
  if(isToken&&event.id){
    art.classList.remove('hidden');
    art.innerHTML='<img alt="">';
    attachCardImage(art.querySelector('img'),event.id,()=>{art.classList.add('hidden')});
  }else{art.classList.add('hidden');art.innerHTML=''}
  // Кто получил жетон — уже написано в заголовке, дублировать не нужно.
  const who=$('event-owner');
  if(who)who.classList.add('hidden');
  $('event-continue').textContent=isToken?'Понятно →':'Показать эффект →';
  $('event-continue').disabled=false;
  // Беспредел и Мегабеспредел объявляем громко: вспышка, тряска, надпись.
  const kind=(event.type||'');
  const isBesp=!isToken&&/еспредел/i.test(kind);
  // Ключ включает id карты и порядковый номер события: два одинаковых
  // Беспределa подряд больше не считаются «тем же самым».
  const burstKey=isBesp?`${kind}|${event.id||''}|${event.seq||lastToastSequence||''}`:'';
  if(isBesp&&burstKey!==lastBurstKey){
    lastBurstKey=burstKey;
    playBespredelBurst(/Мега/i.test(kind));
    clearTimeout(renderEvent._t);
    renderEvent._t=setTimeout(()=>{
      // Показываем окно, только если событие ещё актуально.
      if(lastState&&lastState.pending_event)modal.classList.remove('hidden');
    },3000);
    return;
  }
  if(!isBesp)lastBurstKey='';
  // Страховка: окно обязано открыться, даже если анимация не сработала.
  clearTimeout(renderEvent._t);
  modal.classList.remove('hidden');
}
function renderDecision(decision){const modal=$('decision-modal');if(!decision||decision.waiting_for){modal.classList.add('hidden');return}$('decision-title').textContent=decision.title||'Выбери вариант';$('decision-text').textContent=decision.text||'';$('decision-revealed').replaceChildren(...(decision.revealed_cards||[]).map(card=>cardEl(card,null)));$('decision-options').replaceChildren(...(decision.options||[]).map(option=>{const button=document.createElement('button');button.className='target-button';button.innerHTML=`<b>${escapeHtml(option.label)}</b>${option.detail?`<small>${escapeHtml(option.detail)}</small>`:''}`;button.onclick=()=>{playSound('click');ws.send(JSON.stringify({action:'resolve_decision',option_id:option.id}))};return button}));modal.classList.remove('hidden')}
function buyCard(cardId){
  const card=[...(lastState?.market||[]),...(lastState?.legend_market||[])].find(c=>c.id===cardId);
  if(!card){ws.send(JSON.stringify({action:'buy_card',card_id:cardId}));return}
  askPayment(card,(chips)=>{
    playSound('click');
    ws.send(JSON.stringify({action:'buy_card',card_id:cardId,use_chipsines:chips}));
  });
}
function playCard(card){if(card.id==='spec_wild'){$('wild-modal').classList.remove('hidden');return}if(card.has_attack){pendingAttackChoice=card;$('attack-card-name').textContent=card.name;$('attack-modal').classList.remove('hidden');return}sendPlay(card,{})}
function playAttackNow(card){if(cardNeedsTarget(card))openTargetModal(card);else sendPlay(card,{})}
function deferredAttackButton(card,myTurn){const b=document.createElement('button');b.className='deferred-attack';b.disabled=!myTurn;b.innerHTML=`⚔ Атаковать: <b>${escapeHtml(card.name)}</b>`;b.onclick=()=>activateDeferredAttack(card);return b}
function activateDeferredAttack(card){deferredAttackMode=true;if(cardNeedsTarget(card))openTargetModal(card);else sendAttackActivation(card,{})}
function openTargetModal(card){pendingTargetCard=card;$('target-card-name').textContent=card.name;const selfAllowed=card.id==='start_syrpal'||card.id==='start_hrenal';const targets=lastState.players.filter(p=>selfAllowed||p.id!==myId);$('target-list').replaceChildren(...targets.map(p=>{const b=document.createElement('button');b.className='target-button';b.innerHTML=`<b>${escapeHtml(p.name)}${p.id===myId?' · ты':''}</b><small>♥ ${p.life}/${p.max_life} · ☠ ЖДК ${p.death_tokens}</small>`;b.onclick=()=>{if(permanentActivationCard){sendPermanentActivation(permanentActivationCard,{target_id:p.id});permanentActivationCard=null}else if(deferredAttackMode){sendAttackActivation(card,{target_id:p.id});deferredAttackMode=false}else{sendPlay(card,wildTargetMode?{choice:'steal',target_id:p.id}:{target_id:p.id})}wildTargetMode=false;closeTargetModal()};return b}));$('target-modal').classList.remove('hidden')}
function closeTargetModal(){$('target-modal').classList.add('hidden');pendingTargetCard=null}
function sendPlay(card,params){playSound('card');ws.send(JSON.stringify({action:'play_card',card_id:card.id,params}))}
function sendAttackActivation(card,params){playSound('card');ws.send(JSON.stringify({action:'activate_attack',card_id:card.id,params}))}
function activatePermanent(card){
  // Мисклик по постоянке не должен уничтожать карту — сначала спрашиваем.
  const needTarget=['beast_jaba','leg_throne'].includes(card.id);
  confirmActivation(card,()=>{
    if(needTarget){permanentActivationCard=card;openTargetModal(card)}
    else sendPermanentActivation(card,{});
  });
}
function confirmActivation(card,onYes){
  $('confirm-act-title').textContent=card.name;
  $('confirm-act-text').textContent=card.text||'';
  const photo=$('confirm-act-photo');
  photo.innerHTML='<img alt="">';
  attachCardImage(photo.querySelector('img'),card.id,()=>{photo.innerHTML=''});
  $('confirm-act-yes').onclick=()=>{$('confirm-act-modal').classList.add('hidden');onYes()};
  $('confirm-act-no').onclick=()=>$('confirm-act-modal').classList.add('hidden');
  $('confirm-act-close').onclick=()=>$('confirm-act-modal').classList.add('hidden');
  $('confirm-act-modal').classList.remove('hidden');
}
function sendPermanentActivation(card,params){playSound('card');ws.send(JSON.stringify({action:'activate_permanent',card_id:card.id,params}))}

