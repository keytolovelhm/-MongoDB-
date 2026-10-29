// Automated DOM integration against real HTTP/MongoDB; not student manual acceptance.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {webcrypto} from 'node:crypto';
import assert from 'node:assert/strict';
const {JSDOM}=await import(process.env.JSDOM_MODULE||'jsdom');
const base=process.argv[2],output=process.argv[3],project=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
let cookie='',dom;const windows=[],checks=[];
function record(name){checks.push(name);console.log('PASS',name);}
async function request(url,options={}){
  const result=await fetch(new URL(url,base),{...options,headers:{...options.headers,...(cookie?{Cookie:cookie}:{}),Origin:base}});
  for(const value of result.headers.getSetCookie())if(value.startsWith('survey_session='))cookie=value.split(';')[0];
  return result;
}
async function json(url,method='GET',body){
  const me=method==='GET'||url.startsWith('/api/auth/')?null:await(await request('/api/auth/me')).json();
  const response=await request(url,{method,headers:{'Content-Type':'application/json',...(me?{'X-CSRF-Token':me.csrfToken}:{})},...(body?{body:JSON.stringify(body)}:{})});
  assert.ok(response.ok,await response.clone().text());return response.json();
}
async function screen(){
  dom=new JSDOM(await(await request('/')).text(),{url:base+'/',runScripts:'outside-only',pretendToBeVisual:true});windows.push(dom.window);
  const context=dom.getInternalVMContext();context.fetch=request;context.structuredClone=structuredClone;context.confirm=()=>true;
  context.scrollTo=()=>{}; // jsdom has no layout/scrolling; real-browser layout is recorded separately.
  Object.defineProperty(context,'crypto',{value:webcrypto,configurable:true});const modules=new Map();
  async function load(filename){
    if(modules.has(filename))return modules.get(filename);
    const module=new vm.SourceTextModule(fs.readFileSync(filename,'utf8'),{context,identifier:pathToFileURL(filename).href});modules.set(filename,module);
    await module.link((specifier,parent)=>load(path.resolve(path.dirname(fileURLToPath(parent.identifier)),specifier)));return module;
  }
  await(await load(path.join(project,'app/static/app.js'))).evaluate();
}
const doc=()=>dom.window.document,main=()=>doc().querySelector('#app'),text=()=>main().textContent;
function click(label,scope=doc()){const button=[...scope.querySelectorAll('button')].find(b=>b.textContent===label);assert.ok(button,'button '+label);button.click();}
function input(node,value){assert.ok(node);node.value=value;node.dispatchEvent(new dom.window.Event('input',{bubbles:true}));}
function labelled(label){return [...doc().querySelectorAll('label')].find(x=>[...x.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent).join('').trim()===label)?.querySelector('input,textarea,select');}
function choose(node,value){assert.ok(node);node.value=value;node.dispatchEvent(new dom.window.Event('change',{bubbles:true}));}
function accept(){const box=labelled('我已阅读并确认上述可见范围');assert.ok(box);box.checked=true;box.dispatchEvent(new dom.window.Event('change',{bubbles:true}));}
async function until(test){const end=Date.now()+10000;while(Date.now()<end){if(test())return;await new Promise(r=>setTimeout(r,20));}throw new Error('DOM timeout: '+text()+' / '+doc().querySelector('#notice').textContent);}
const tick=()=>new Promise(r=>setTimeout(r,80));
const a='ui_author_'+Date.now(),b='ui_borrow_'+Date.now(),password='DOM-test-password-123';
try{
  await screen();click('没有账号，去注册');input(doc().querySelector('[name=username]'),a);input(doc().querySelector('[name=password]'),password);
  doc().querySelector('form').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));await until(()=>text().includes('我的问卷'));
  await json('/api/auth/register','POST',{username:b,password});
  click('我的题目');await until(()=>text().includes('新建题目'));click('新建题目');await until(()=>labelled('管理名称'));
  input(labelled('管理名称'),'UI年龄');input(labelled('题干'),'UI年龄题');choose(labelled('题型'),'NUMBER');input(labelled('最小值'),'0');input(labelled('最大值'),'120');
  click('保存');await until(()=>text().includes('默认版本'));record('网页创建数字库题与固定分组');
  const roots=await json('/api/library/questions'),rootId=roots.items[0].id;
  let history=await json(`/api/library/questions/${rootId}/versions`);const v1=history.items[0];
  click('从此版本修改');await until(()=>text().includes('编辑工作稿'));input(labelled('题干'),'UI新版年龄题');click('保存');await until(()=>text().includes('未发布工作稿'));
  click('保存工作稿为新版本');await until(()=>text().includes('UI新版年龄题')&&main().querySelectorAll('.panel').length===2);record('网页工作稿保存为新版本');
  let oldPanel=[...main().querySelectorAll('.panel')].find(p=>p.querySelector('h3')?.textContent==='UI年龄题');
  click('恢复为新版本',oldPanel);await until(()=>main().querySelectorAll('.panel').length===3);record('网页恢复历史内容生成新版本');
  oldPanel=[...main().querySelectorAll('.panel')].find(p=>p.textContent.includes('CREATE'));
  click('版本详情与共享',oldPanel);await until(()=>labelled('账号名称'));input(labelled('账号名称'),b);click('授予复用权限');await until(()=>text().includes(b+' · 有效'));record('网页指定账号共享确切版本');
  await json('/api/auth/login','POST',{username:b,password});await screen();click('＋ 新建问卷');await until(()=>labelled('问卷标题'));input(labelled('问卷标题'),'UI借用问卷');
  click('从题目库选题');await until(()=>text().includes('选择题目版本'));click('收到的共享');await until(()=>text().includes('选择此版本'));click('选择此版本');await until(()=>text().includes('确认复用范围'));
  click('确认使用此版本');await until(()=>doc().querySelector('#notice').textContent.includes('请先确认'));record('网页未确认告知时拒绝导入');
  accept();click('确认使用此版本');await until(()=>text().includes('库题固定快照'));assert.ok(doc().querySelector('fieldset[disabled]'));record('网页导入后库题正文只读，仍有本卷跳转控件');
  click('保存草稿');await until(()=>doc().querySelector('#notice').textContent==='草稿已保存');click('返回列表');await until(()=>text().includes('UI借用问卷'));click('发布');await until(()=>text().includes('收集中'));record('含库题草稿可保存并发布');
  click('我的题库');await until(()=>labelled('题库名称'));input(labelled('题库名称'),'UI题库');click('创建题库');await until(()=>text().includes('UI题库'));click('管理成员');await until(()=>text().includes('添加题目版本'));
  click('添加题目版本');await until(()=>text().includes('选择题目版本'));click('收到的共享');await until(()=>text().includes('选择此版本'));click('选择此版本');await until(()=>text().includes('更新成员版本'));record('网页题库添加固定版本');
  click('移除成员');await until(()=>!text().includes('更新成员版本'));record('网页移除题库成员');
  // A real schema=1 frozen survey is set up over HTTP, then linked via the shipped UI.
  let old=await json('/api/surveys','POST',{title:'UI旧卷',questions:[{questionId:'old','order':0,title:'UI旧题',type:'SINGLE',options:[{optionId:'a',label:'有'},{optionId:'b',label:'没有'}]}]});
  old=await json(`/api/surveys/${old.id}/publish`,'POST',{revision:old.revision});await screen();
  const card=[...main().querySelectorAll('.survey-card')].find(c=>c.querySelector('h2').textContent==='UI旧卷');click('题目与历史关联',card);await until(()=>text().includes('尚未关联'));
  click('保存为我的题目');await until(()=>text().includes('确认保存为题目'));click('确认保存为题目');await until(()=>text().includes('尚未关联'));record('网页从旧卷保存库题，不自动绑定历史回答');
  click('选择版本并关联');await until(()=>text().includes('选择题目版本')&&text().includes('选择具体版本'));click('选择具体版本');await until(()=>text().includes('选择此版本'));click('选择此版本');await until(()=>text().includes('确认复用范围'));accept();click('确认使用此版本');await until(()=>text().includes('已关联：'));record('网页显式关联旧题并确认披露范围');
  click('暂停关联');await until(()=>labelled('原因'));input(labelled('原因'),'UI核对');click('确认操作');await until(()=>text().includes('已暂停：'));click('恢复关联');await until(()=>labelled('原因'));input(labelled('原因'),'UI核实一致');click('确认操作');await until(()=>text().includes('确认复用范围'));accept();click('确认使用此版本');await until(()=>text().includes('已关联：'));record('网页暂停和恢复历史关联');
  await json('/api/auth/login','POST',{username:a,password});await screen();click('我的题目');await until(()=>text().includes('UI年龄'));click('查看题目');await until(()=>text().includes('使用情况'));click('使用情况');await until(()=>text().includes('题目使用情况'));assert.ok(text().includes('问卷 '));assert.ok(!text().includes('UI借用问卷'));record('原作者网页查看他人最小使用标识，无整卷内容');
  click('返回');await until(()=>text().includes('跨问卷统计'));oldPanel=[...main().querySelectorAll('.panel')].find(p=>p.textContent.includes('CREATE'));click('跨问卷统计',oldPanel);await until(()=>text().includes('单题跨问卷统计'));assert.ok(text().includes('样本不足，已隐藏'));record('网页跨卷统计分区展示和低样本提示');
  await screen();click('我的题目');await until(()=>text().includes('查看题目'));click('查看题目');await until(()=>text().includes('版本详情与共享'));oldPanel=[...main().querySelectorAll('.panel')].find(p=>p.textContent.includes('CREATE'));click('版本详情与共享',oldPanel);await until(()=>text().includes('撤销共享'));click('撤销共享');await until(()=>text().includes('已撤销'));record('网页撤销指定版本共享');
  await json('/api/auth/login','POST',{username:b,password});await screen();const owned=await json('/api/surveys');assert.ok(owned.items.find(s=>s.title==='UI借用问卷').status==='PUBLISHED');record('撤销后既有发布问卷保持可用');
  fs.writeFileSync(output,JSON.stringify({passed:checks.length,failed:0,kind:'automated DOM, not manual browser',checks},null,2));
}catch(error){fs.writeFileSync(output,JSON.stringify({passed:checks.length,failed:1,checks,error:error.stack},null,2));throw error;}
finally{for(const window of windows)window.close();}
