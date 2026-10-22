export const state = { user: null, csrf: '' };
export const root = document.querySelector('#app');
export function el(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith('on')) element.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'class') element.className = value;
    else if (key === 'checked') element.checked = value;
    else if (key === 'value') element.value = value;
    else if (key === 'hidden') element.hidden = value;
    else element.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) if (child !== null && child !== undefined) element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return element;
}
export function notice(message) {
  const box = document.querySelector('#notice'); box.textContent = message; box.hidden = false;
  clearTimeout(notice.timer); notice.timer = setTimeout(() => { box.hidden = true; }, 5500);
}
export async function api(path, method = 'GET', data) {
  const response = await fetch('/api' + path, { method, credentials: 'same-origin', headers: {
    'Content-Type': 'application/json', ...(state.csrf ? {'X-CSRF-Token': state.csrf} : {})
  }, ...(data === undefined ? {} : {body: JSON.stringify(data)}) });
  const body = await response.json();
  if (!response.ok) {
    const error = body.error || {}; const first = error.fields?.[0];
    throw new Error((error.message || '请求失败') + (error.field ? `（${error.field}）` : '') + (first ? `：${first.field} ${first.message}` : ''));
  }
  return body;
}
export function button(text, fn, cls = '') {
  return el('button', {type: 'button', class: cls, onClick: async event => {
    const b = event.currentTarget; b.disabled = true;
    try { await fn(event); } catch (error) { notice(error.message); }
    finally { b.disabled = false; }
  }}, text);
}
export function field(label, input, hint) { return el('label', {}, label, input, hint ? el('small', {}, hint) : null); }
export function select(values, value, changed) {
  const input = el('select', {onChange: event => changed(event.target.value)}, ...values.map(([v, label]) => el('option', {value:v}, label)));
  input.value = value; return input;
}
export const statuses = {DRAFT:'草稿', PUBLISHED:'收集中', CLOSED:'已关闭', EXPIRED:'已截止'};
export const types = {SINGLE:'单选题', MULTI:'多选题', TEXT:'文本填空', NUMBER:'数字填空'};
export const time = value => value ? new Date(value).toLocaleString('zh-CN', {hour12:false}) : '未设置';
export function dateInput(value) {
  const input = el('input', {type:'datetime-local'});
  if (value) { const d = new Date(value); input.value = new Date(d.getTime() - d.getTimezoneOffset()*60000).toISOString().slice(0,16); }
  return input;
}
export function check(text, checked, fn) { return el('label', {class:'check'}, el('input', {type:'checkbox', checked, onChange:e=>fn(e.target.checked)}), text); }
export function heading(title, subtitle, eyebrow = '问卷工作台') { return el('div', {}, el('p', {class:'eyebrow'}, eyebrow), el('h1', {}, title), el('p', {class:'muted'}, subtitle)); }
