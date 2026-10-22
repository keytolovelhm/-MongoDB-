// DOM integration test, not a browser rendering test. Uses the shipped JS and a live HTTP backend.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {webcrypto} from 'node:crypto';
import assert from 'node:assert/strict';
const {JSDOM} = await import(process.env.JSDOM_MODULE || 'jsdom');
const base=process.argv[2], output=process.argv[3];
const project=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
let cookie='', dom, windows=[];
const checks=[];
function record(name){checks.push(name);console.log('PASS',name);}
async function request(url,options={}){
  const headers={...options.headers,...(cookie?{'Cookie':cookie}:{}),'Origin':base};
  const result=await fetch(new URL(url,base),{...options,headers});
  for(const value of result.headers.getSetCookie())if(value.startsWith('survey_session='))cookie=value.split(';')[0];
  return result;
}
async function screen(url='/'){
  const response=await request(url);assert.equal(response.status,200);
  dom=new JSDOM(await response.text(),{url:base+url,runScripts:'outside-only',pretendToBeVisual:true});windows.push(dom.window);
  const context=dom.getInternalVMContext();context.fetch=request;context.structuredClone=structuredClone;context.confirm=()=>true;
  Object.defineProperty(context,'crypto',{value:webcrypto,configurable:true});
  const modules=new Map();
  async function load(filename){
    if(modules.has(filename))return modules.get(filename);
    const module=new vm.SourceTextModule(fs.readFileSync(filename,'utf8'),{context,identifier:pathToFileURL(filename).href});
    modules.set(filename,module);
    await module.link((specifier,parent)=>load(path.resolve(path.dirname(fileURLToPath(parent.identifier)),specifier)));
    return module;
  }
  const entry=await load(path.join(project,'app/static/app.js'));await entry.evaluate();
}
const doc=()=>dom.window.document;
function click(text,scope=doc()){
  const b=[...scope.querySelectorAll('button')].find(b=>b.textContent===text);assert.ok(b,'button '+text);b.click();
}
function input(element,value){assert.ok(element);element.value=value;element.dispatchEvent(new dom.window.Event('input',{bubbles:true}));}
function select(element,value){element.value=value;element.dispatchEvent(new dom.window.Event('change',{bubbles:true}));}
async function until(predicate){const end=Date.now()+8000;while(Date.now()<end){if(predicate())return;await new Promise(r=>setTimeout(r,20));}throw new Error('DOM wait timeout: '+doc().querySelector('#app').textContent);}
const mainText=()=>doc().querySelector('#app').textContent;
try{
  await screen();assert.ok(mainText().includes('欢迎回来'));record('页面及正式JS模块可加载');
  click('没有账号，去注册');input(doc().querySelector('[name=username]'),'dom_'+Date.now());input(doc().querySelector('[name=password]'),'DOM-test-password-123');
  doc().querySelector('form').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));
  await until(()=>mainText().includes('我的问卷'));record('注册登录并进入工作台');
  click('创建演示问卷');await until(()=>mainText().includes('编辑问卷'));assert.equal(doc().querySelectorAll('.question-editor').length,5);record('创建并展示五题演示问卷');
  let numeric=doc().querySelectorAll('.question-editor')[3];click('添加跳转规则',numeric);
  numeric=doc().querySelectorAll('.question-editor')[3];select(numeric.querySelector('.rule-fields select'),'gte');
  numeric=doc().querySelectorAll('.question-editor')[3];input(numeric.querySelectorAll('.rule-fields input')[1],'18');
  const targets=numeric.querySelectorAll('.rule-fields select')[1];select(targets,targets.options[1].value);
  click('保存草稿');await until(()=>doc().querySelector('#notice').textContent==='草稿已保存');record('通过规则配置控件保存数字跳转');
  click('返回列表');await until(()=>mainText().includes('我的问卷'));click('发布');await until(()=>mainText().includes('收集中'));record('发布并生成填写入口');
  const share=new URL([...doc().querySelectorAll('a')].find(a=>a.textContent==='填写入口').href).pathname;
  await screen(share);select(doc().querySelector('main select'),'ANONYMOUS');click('新建一次填写');
  await until(()=>mainText().includes('请选择填写路径'));record('以登录后匿名方式创建填写会话');
  doc().querySelectorAll('.answer-option input')[1].checked=true;click('保存并继续');await until(()=>mainText().includes('喜欢的水果'));
  assert.equal(doc().querySelector('[aria-label="已清除答案提示"]'),null,'未清除答案时不显示清理提示');record('单选规则跳过必答题进入多选');
  click('保存并继续');await until(()=>doc().querySelector('#notice').textContent.includes('必须回答'));record('多选必答错误提示');
  doc().querySelectorAll('.answer-option input').forEach(i=>i.checked=true);click('保存并继续');await until(()=>mainText().includes('年龄（'));record('多选保存并进入数字题');
  input(doc().querySelector('main input[type=text]'),'1.5');click('保存并继续');await until(()=>doc().querySelector('#notice').textContent.includes('整数'));record('数字整数限制错误提示');
  input(doc().querySelector('main input[type=text]'),'20');click('保存并继续');await until(()=>mainText().includes('还有什么想补充'));record('数字规则执行到目标题');
  input(doc().querySelector('textarea'),'DOM验证 <script>alert(1)</script>');click('保存并继续');await until(()=>mainText().includes('填写完成'));record('文本保存与提交前核对');
  click('1',doc().querySelector('.question-nav'));doc().querySelector('.answer-option input').checked=true;click('保存并继续');
  await until(()=>doc().querySelector('#notice').textContent.includes('清理2题'));
  const summaryRows=[...doc().querySelectorAll('.summary-line')];
  assert.equal(summaryRows.some(row=>row.textContent.includes('年龄（')),false);record('修改上游后清理两个失效分支答案');
  const cleared=doc().querySelector('[aria-label="已清除答案提示"]');
  assert.ok(cleared,'清理结果应在页面内显示，不只依赖短暂通知');
  assert.equal(cleared.getAttribute('role'),'status');
  assert.ok(cleared.textContent.includes('第3题')&&cleared.textContent.includes('喜欢的水果'));
  assert.ok(cleared.textContent.includes('第4题')&&cleared.textContent.includes('年龄（'));
  assert.ok(cleared.textContent.includes('不会自动恢复'));
  record('页面内明确列出被清除答案的题号、题干及重新填写提示');
  await new Promise(resolve=>setTimeout(resolve,5700));
  assert.ok(doc().querySelector('#notice').hidden,'短暂通知应已消失');
  assert.ok(cleared.isConnected&&!cleared.hidden,'页面内清理提示应继续保留');
  record('短暂通知消失后页面内清理提示仍可查看');
  click('提交问卷');await until(()=>mainText().includes('提交成功'));record('正式提交并显示回执');
  await screen('/');click('查看统计');await until(()=>mainText().includes('有效答卷数'));
  const metrics=[...doc().querySelectorAll('.metric strong')].map(e=>e.textContent);assert.deepEqual(metrics,['1','1']);record('工作台统计答卷数与独立账号数');
  const panels=doc().querySelectorAll('.panel');const last=panels[panels.length-1];click('查看全部回答（分页）',last);await until(()=>last.textContent.includes('DOM验证'));
  assert.equal(last.querySelectorAll('script').length,0);assert.ok(last.textContent.includes('<script>alert(1)</script>'));record('分页显示原始文本，按文本节点展示HTML内容');
  fs.writeFileSync(output,JSON.stringify({kind:'jsdom-dom-integration-not-browser-visual',passed:checks.length,failed:0,checks},null,2));
}catch(error){
  fs.writeFileSync(output,JSON.stringify({kind:'jsdom-dom-integration-not-browser-visual',passed:checks.length,failed:1,checks,error:error.stack,dom:doc()?.querySelector('#app')?.textContent},null,2));
  throw error;
}finally{for(const win of windows)win.close();}
