'use strict';
// 运维人员在独立浏览器中正常登录后生成只含 France Galop 的会话文件。
// 不读取个人Chrome配置、不记录密码、不导出身份提供方的Cookie。
const fs=require('node:fs/promises');
const path=require('node:path');
const readline=require('node:readline/promises');
const {chromium}=require('playwright');
async function main(){
 const target=process.argv[2];
 if(!target||!path.isAbsolute(target))throw Error('必须提供仓库外的绝对输出路径');
 const root=path.resolve(__dirname,'../..');
 if(target===root||target.startsWith(root+path.sep))throw Error('会话文件不得写入仓库');
 const browser=await chromium.launch({headless:false});
 const input=readline.createInterface({input:process.stdin,output:process.stdout});
 try{
  const context=await browser.newContext({timezoneId:'Europe/Paris',locale:'fr-FR'});
  const page=await context.newPage();
  await page.goto('https://www.france-galop.com/fr/courses/pattern-listed');
  await input.question('请在独立浏览器内完成正常登录，确认分级赛目录已可见后按回车保存：');
  if(new URL(page.url()).hostname!=='www.france-galop.com'||!(await page.locator('a[href*="/fr/course/detail/"]').count()))throw Error('尚未进入可用赛事目录');
  const raw=await context.storageState();
  const state={cookies:raw.cookies.filter(c=>['france-galop.com','www.france-galop.com'].includes(c.domain.replace(/^\./,''))),
   origins:raw.origins.filter(o=>o.origin==='https://www.france-galop.com')};
  if(!state.cookies.length)throw Error('未取得法国站点会话Cookie');
  await fs.mkdir(path.dirname(target),{recursive:true,mode:0o700});
  const handle=await fs.open(target,'wx',0o600);
  try{await handle.writeFile(JSON.stringify(state));}finally{await handle.close();}
  process.stdout.write('独立法国会话已保存；请按发布包受控安装并验证，不提交到Git。\n');
 }finally{input.close();await browser.close();}
}
main().catch(error=>{process.stderr.write(error.message+'\n');process.exitCode=1;});
