import {api,el,root,state,heading,field,button,notice,statuses,dateInput,time} from './core.js';
import {editor,sample} from './editor.js';
import {filler} from './filler.js';
import {stats} from './stats.js';

function nav(){
  const box=document.querySelector('#nav');
  box.replaceChildren(...(state.user?[el('span',{},state.user.username),el('a',{href:'/',class:'button'},'我的问卷'),button('退出',async()=>{await api('/auth/logout','POST');state.user=null;state.csrf='';nav();auth();})]:[el('span',{class:'muted'},'登录后创建或填写问卷')]));
}
function auth(register=false){
  const username=el('input',{name:'username',autocomplete:'username',minlength:3,maxlength:40,required:true});
  const password=el('input',{name:'password',type:'password',autocomplete:register?'new-password':'current-password',minlength:8,maxlength:128,required:true});
  const message=el('p',{class:'error',role:'alert'});
  const submit=el('button',{type:'submit',class:'primary'},register?'注册并登录':'登录');
  const form=el('form',{class:'panel auth',onSubmit:async e=>{
    e.preventDefault();submit.disabled=true;message.textContent='';
    try{
      const body={username:username.value,password:password.value};
      if(register)await api('/auth/register','POST',body);
      const session=await api('/auth/login','POST',body);state.user=session.user;state.csrf=session.csrfToken;nav();await route();
    }catch(error){message.textContent=error.message;}finally{submit.disabled=false;}
  }},el('p',{class:'eyebrow'},'问卷工作台'),el('h1',{},register?'创建账号':'欢迎回来'),el('p',{class:'muted'},location.pathname.startsWith('/survey/')?'登录后即可继续填写这份问卷。':'创建问卷、配置路径，并查看真实回答。'),
    field('用户名',username),field('密码',password,'8至128个字符'),message,el('div',{class:'actions'},submit,button(register?'已有账号，去登录':'没有账号，去注册',()=>auth(!register))));
  root.replaceChildren(form);
}
async function dashboard(skip=0){
  const data=await api(`/surveys?skip=${skip}&limit=20`);
  root.replaceChildren(heading('我的问卷','管理问卷、分发填写链接，并查看结果。'));
  root.append(el('div',{class:'toolbar'},el('span',{class:'muted'},`共 ${data.total} 份问卷`),el('div',{class:'actions'},
    button('创建演示问卷',async()=>{const created=await api('/surveys','POST',sample());await editor(created,()=>dashboard());}),
    button('＋ 新建问卷',()=>editor(null,()=>dashboard()),'primary'))));
  if(!data.items.length){root.append(el('div',{class:'empty'},el('h2',{},'从第一份问卷开始'),el('p',{class:'muted'},'新建空白问卷，或使用演示问卷体验条件跳转与校验。')));return;}
  const grid=el('div',{class:'grid'});
  for(const item of data.items){
    const card=el('article',{class:'survey-card'},el('span',{class:'badge '+item.effectiveStatus},statuses[item.effectiveStatus]),el('h2',{},item.title),
      el('p',{class:'muted'},item.description||'暂无说明'),el('small',{},'更新于 '+time(item.updatedAt)));
    const actions=el('div',{class:'actions'});
    const full=()=>api('/surveys/'+item.id);
    if(item.status==='DRAFT'){
      actions.append(button('编辑',async()=>editor(await full(),()=>dashboard(skip))),button('发布',async()=>{
        if(confirm('发布后题目、规则和参与策略将冻结，确定发布？')){await api('/surveys/'+item.id+'/publish','POST',{revision:item.revision});notice('问卷已发布');await dashboard(skip);}
      },'primary'));
    }else{
      actions.append(button('查看统计',async()=>stats(await full(),()=>dashboard(skip))),el('a',{class:'button',href:'/survey/'+item.shareSlug},'填写入口'));
      const link=el('input',{value:location.origin+'/survey/'+item.shareSlug,readonly:true,'aria-label':'分享链接'});
      card.append(el('div',{class:'link-box'},link,button('复制链接',async()=>{await navigator.clipboard.writeText(link.value);notice('分享链接已复制');})));
    }
    if(['DRAFT','PUBLISHED'].includes(item.effectiveStatus))actions.append(button('截止时间',async()=>deadlineDialog(await full(),skip)));
    if(item.status==='PUBLISHED')actions.append(button('关闭',async()=>{
      if(confirm('关闭后不能重新开放，确定关闭这份问卷？')){await api('/surveys/'+item.id+'/close','POST',{revision:item.revision});await dashboard(skip);}
    },'danger'));
    card.append(actions);grid.append(card);
  }
  root.append(grid,el('div',{class:'toolbar'},skip?button('上一页',()=>dashboard(Math.max(0,skip-20))):el('span'),
    skip+20<data.total?button('下一页',()=>dashboard(skip+20)):null));
}
function deadlineDialog(survey,skip){
  const input=dateInput(survey.closesAt);
  root.replaceChildren(heading('设置截止时间',survey.title),el('section',{class:'panel'},field('截止时间（留空表示不限时）',input),
    el('p',{class:'muted'},'已关闭或已截止的问卷不能重新开放。'),el('div',{class:'actions'},button('保存',async()=>{
      await api('/surveys/'+survey.id+'/deadline','PATCH',{revision:survey.revision,closesAt:input.value?new Date(input.value).toISOString():null});notice('截止时间已保存');await dashboard(skip);
    },'primary'),button('返回',()=>dashboard(skip)))));
}
async function route(){
  const match=location.pathname.match(/^\/survey\/([^/]+)$/);
  if(match)await filler(match[1]);else await dashboard();
}
try{const session=await api('/auth/me');state.user=session.user;state.csrf=session.csrfToken;nav();await route();}
catch(error){nav();if(state.user){root.replaceChildren(heading('暂时无法打开',error.message),el('a',{href:'/',class:'button'},'返回首页'));}else auth();}
