/* Shared asynchronous dialogs, independent of the editor's content modal. */
(() => {
  'use strict';
  let queue=Promise.resolve(),active=null;
  function choose(message,{title='确认操作',buttons=[{value:'cancel',label:'取消'},{value:'confirm',label:'确定',primary:true}],cancel='cancel',danger=false}={}){
    const run=()=>new Promise(resolve=>{
      const previous=document.activeElement,layer=document.createElement('div');
      layer.className='workbench-dialog-backdrop';layer.id='workbench-dialog-backdrop';
      const box=document.createElement('section');box.className='workbench-dialog';box.id='workbench-dialog';
      box.setAttribute('role','alertdialog');box.setAttribute('aria-modal','true');
      box.setAttribute('aria-labelledby','workbench-dialog-title');box.setAttribute('aria-describedby','workbench-dialog-message');
      const icon=document.createElement('span');icon.className='workbench-dialog-icon';icon.textContent=danger?'!':'◇';icon.setAttribute('aria-hidden','true');
      const heading=document.createElement('h3');heading.id='workbench-dialog-title';heading.textContent=title;
      const text=document.createElement('p');text.id='workbench-dialog-message';text.textContent=message;
      const actions=document.createElement('footer');
      const finish=value=>{document.removeEventListener('keydown',keydown,true);layer.remove();active=null;if(previous?.isConnected)previous.focus({preventScroll:true});resolve(value)};
      for(const item of buttons){const button=document.createElement('button');button.type='button';button.dataset.dialogResult=item.value;
        button.className=item.primary?'primary-btn':'secondary-btn';if(item.danger)button.classList.add('dialog-danger');
        button.textContent=item.label;button.onclick=()=>finish(item.value);actions.append(button)}
      function keydown(event){
        if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();finish(cancel)}
        else if(event.key==='Tab'){
          const items=[...actions.querySelectorAll('button')],first=items[0],last=items.at(-1);
          if(event.shiftKey&&(document.activeElement===first||!box.contains(document.activeElement))){event.preventDefault();last.focus()}
          else if(!event.shiftKey&&(document.activeElement===last||!box.contains(document.activeElement))){event.preventDefault();first.focus()}
          event.stopImmediatePropagation();
        }else if((event.ctrlKey||event.metaKey)&&['s','k'].includes(event.key.toLowerCase())){event.preventDefault();event.stopImmediatePropagation()}
      }
      layer.onmousedown=event=>{if(event.target===layer)finish(cancel)};
      box.append(icon,heading,text,actions);layer.append(box);document.body.append(layer);active=layer;
      document.addEventListener('keydown',keydown,true);
      actions.querySelector(`[data-dialog-result="${cancel}"]`)?.focus({preventScroll:true});
      if(!box.contains(document.activeElement))actions.querySelector('button')?.focus();
    });
    const result=queue.then(run);queue=result.catch(()=>{});return result;
  }
  async function confirm(message,options={}){
    const danger=/删除|清空|移入.*Trash/.test(message),complete=/确认完成/.test(message);
    return (await choose(message,{title:complete?'完成待办':danger?'确认删除':'确认操作',danger,
      buttons:[{value:'cancel',label:'取消'},{value:'confirm',label:complete?'确认完成':danger?'确认删除':'确定',primary:true,danger}],...options}))==='confirm';
  }
  const alert=(message,{title='操作提示'}={})=>choose(String(message),{title,cancel:'confirm',buttons:[{value:'confirm',label:'知道了',primary:true}]});
  window.ERWDialog={choose,confirm,alert,isOpen:()=>!!active};
})();
