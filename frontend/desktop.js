/* Desktop layout and persistent market preferences. No game rules live here. */
window.DesktopUI=(()=>{
  const $=id=>document.getElementById(id);
  const drawers=()=>[...document.querySelectorAll('.market-drawer')];
  let active='main',docked=false,popup=false,utility=false,hooks={},initialized=false;
  const storage={read(key,fallback){try{return localStorage.getItem(key)||fallback;}catch{return fallback;}},write(key,value){try{localStorage.setItem(key,value);}catch{}}};
  function activeDrawer(){return document.querySelector(`.market-drawer[data-market="${active}"]`);}
  function positionPopup(){
    if(!popup||docked||!document.body.classList.contains('in-game'))return;
    const drawer=activeDrawer(),panel=drawer.querySelector('.drawer-content'),tab=drawer.querySelector('.drawer-tab');
    panel.style.cssText='';
    const anchor=tab.getBoundingClientRect(),width=Math.min(680,window.innerWidth-32);
    const height=Math.min(panel.scrollHeight,window.innerHeight-100);
    const top=Math.max(60,Math.min(anchor.bottom+8,window.innerHeight-height-16));
    Object.assign(panel.style,{position:'fixed',width:`${width}px`,left:`${Math.max(16,Math.min(anchor.right-width,window.innerWidth-width-16))}px`,top:`${top}px`});
  }
  function apply(){
    document.body.classList.toggle('market-docked',docked);
    drawers().forEach(drawer=>{
      const selected=drawer.dataset.market===active;
      const opened=selected&&(docked||popup);
      drawer.dataset.active=String(selected);drawer.dataset.open=String(opened);
      const tab=drawer.querySelector('.drawer-tab');
      tab.setAttribute('aria-expanded',String(opened));tab.classList.toggle('is-selected',opened);
      const panel=drawer.querySelector('.drawer-content');panel.style.cssText='';
      panel.setAttribute('aria-hidden',String(!opened));panel.inert=!opened;
      const pin=drawer.querySelector('.market-pin');pin.textContent=docked?'Открепить':'Закрепить';
      pin.setAttribute('aria-pressed',String(docked));
      drawer.querySelector('.drawer-close').title=docked?'Открепить и закрыть':'Закрыть рынок';
    });
    storage.write('krutagidon_market_dock',docked?'on':'off');storage.write('krutagidon_market_active',active);
    positionPopup();hooks.layout?.();
  }
  function closeMarket(){const drawer=activeDrawer(),restore=drawer?.querySelector('.drawer-content').contains(document.activeElement);popup=false;apply();if(restore&&!docked)drawer.querySelector('.drawer-tab').focus();}
  function closeUtility(){const restore=$('self-utilities').contains(document.activeElement);utility=false;$('self-utilities').classList.add('hidden');$('utility-toggle').setAttribute('aria-expanded','false');if(restore)$('utility-toggle').focus();}
  function openMarket(kind){
    hooks.sound?.('drawer');closeUtility();
    if(docked){active=kind;popup=false;}
    else{popup=!(popup&&active===kind);active=kind;}
    apply();
  }
  function toggleDock(){
    docked=!docked;popup=!docked;apply();
  }
  function sync(){
    if(!initialized)return;
    const permanents=$('permanents').children.length,attacks=$('attack-actions').children.length;
    const toggle=$('utility-toggle');toggle.classList.toggle('hidden',permanents+attacks===0);
    toggle.textContent=attacks?`Постоянки ${permanents} · Атаки ${attacks}`:`Постоянки · ${permanents}`;
    $('permanent-group').classList.toggle('hidden',permanents===0);
    $('attack-group').classList.toggle('hidden',attacks===0);
    if(!permanents&&!attacks)closeUtility();
    const hand=$('hand');$('hand-scroll-hint').classList.toggle('hidden',hand.scrollWidth<=hand.clientWidth+2);
  }
  function init(options={}){
    if(initialized)return;initialized=true;hooks=options;
    docked=storage.read('krutagidon_market_dock','off')==='on';
    active=storage.read('krutagidon_market_active','main')==='legend'?'legend':'main';
    drawers().forEach(drawer=>{
      const tab=drawer.querySelector('.drawer-tab'),panel=drawer.querySelector('.drawer-content');
      tab.onclick=event=>{event.stopPropagation();openMarket(drawer.dataset.market);};
      drawer.querySelector('.market-pin').onclick=event=>{event.stopPropagation();active=drawer.dataset.market;toggleDock();};
      drawer.querySelector('.drawer-close').onclick=event=>{event.stopPropagation();docked=false;popup=false;apply();tab.focus();};
      panel.addEventListener('click',event=>event.stopPropagation());
    });
    $('utility-toggle').onclick=()=>{
      closeMarket();utility=!utility;$('self-utilities').classList.toggle('hidden',!utility);
      $('utility-toggle').setAttribute('aria-expanded',String(utility));
    };
    $('utilities-close').onclick=closeUtility;
    document.addEventListener('pointerdown',event=>{
      if(event.target.closest('.modal'))return;
      if(popup&&!event.target.closest('.market-drawer'))closeMarket();
      if(utility&&!event.target.closest('#self-panel'))closeUtility();
    });
    document.addEventListener('keydown',event=>{
      if(event.key!=='Escape'||document.querySelector('.modal:not(.hidden)'))return;
      if(utility){closeUtility();event.preventDefault();event.stopImmediatePropagation();}
      else if(popup){closeMarket();event.preventDefault();event.stopImmediatePropagation();}
      // A dock is a permanent part of the layout, not an Escape-dismissed modal.
    },true);
    window.addEventListener('resize',()=>{positionPopup();sync();});
    const hand=$('hand');
    hand.addEventListener('wheel',event=>{
      if(event.ctrlKey||Math.abs(event.deltaX)>Math.abs(event.deltaY)||hand.scrollWidth<=hand.clientWidth+2)return;
      const before=hand.scrollLeft;hand.scrollLeft+=event.deltaY;
      if(hand.scrollLeft!==before)event.preventDefault();
    },{passive:false});
    new ResizeObserver(()=>{positionPopup();sync();}).observe($('game-screen'));
    apply();sync();
  }
  function screenChanged(inGame){if(!inGame){popup=false;closeUtility();}apply();}
  return {init,sync,screenChanged,closeTransient(){popup=false;closeUtility();apply();},getPreference(){return {docked,active};}};
})();
