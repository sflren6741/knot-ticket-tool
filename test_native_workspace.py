"""Native Windows/Edge folder-selection integration test.

Uses a fresh browser profile and an isolated folder under ../knot-native-tests.
It interacts only with the test browser and its native folder picker. Test files
are retained for inspection; no existing workspace or user browser profile is used.
Run explicitly; a short-lived visible Edge window is needed for the native picker.
"""
import ctypes as c
from ctypes import wintypes as w
import json
from pathlib import Path
import subprocess
import tempfile

from playwright.sync_api import sync_playwright

u=c.windll.user32
callback=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)


def window_info(hwnd):
    text=c.create_unicode_buffer(512)
    cls=c.create_unicode_buffer(128)
    pid=w.DWORD()
    u.GetWindowTextW(hwnd,text,512)
    u.GetClassNameW(hwnd,cls,128)
    u.GetWindowThreadProcessId(hwnd,c.byref(pid))
    return {'hwnd':int(hwnd),'class':cls.value,'text':text.value,'id':u.GetDlgCtrlID(hwnd),'pid':pid.value}


def windows():
    result=[]
    @callback
    def collect(hwnd,_):
        result.append(window_info(hwnd))
        return True
    u.EnumWindows(collect,0)
    return result


def select_test_folder(page,path):
    previous={item['hwnd'] for item in windows()}
    page.locator('#workspace-menu').evaluate('(el)=>el.open=true')
    page.click('#open-workspace')
    dialog=None
    for _ in range(40):
        dialog=next((item for item in windows() if item['hwnd'] not in previous and item['class']=='#32770' and u.IsWindowVisible(w.HWND(item['hwnd']))),None)
        if dialog:
            break
        page.wait_for_timeout(100)
    assert dialog, 'The native folder picker did not appear'
    children=[]
    @callback
    def collect(hwnd,_):
        children.append(window_info(hwnd))
        return True
    u.EnumChildWindows(w.HWND(dialog['hwnd']),collect,0)
    edit=next(x['hwnd'] for x in children if x['class']=='Edit' and x['id']==1152)
    select=next(x['hwnd'] for x in children if x['class']=='Button' and x['id']==1)
    u.SendMessageW(w.HWND(edit),0xC,0,c.c_wchar_p(str(path)))
    u.PostMessageW(w.HWND(select),0xF5,0,0)
    page.wait_for_timeout(600)
    if u.IsWindowVisible(w.HWND(dialog['hwnd'])):
        u.PostMessageW(w.HWND(select),0xF5,0,0)
        page.wait_for_timeout(500)


def allow_test_browser(browser,page):
    session=browser.new_browser_cdp_session()
    pid=next(p['id'] for p in session.send('SystemInfo.getProcessInfo')['processInfo'] if p['type']=='browser')
    root=next(item for item in windows() if item['pid']==pid and item['class']=='Chrome_WidgetWin_1' and u.IsWindowVisible(w.HWND(item['hwnd'])))
    command="""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]HWND)
$condition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Button)
$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition) | ForEach-Object {
 if($_.Current.Name -eq '許可' -or $_.Current.Name -eq 'Allow') {
  $pattern=$_.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
  $pattern.Invoke()
 }
}
""".replace('HWND',str(root['hwnd']))
    result=subprocess.run(['powershell','-NoProfile','-Command',command],capture_output=True,timeout=10)
    assert result.returncode==0, 'Could not operate the test browser permission control'


def main():
    parent=Path(__file__).resolve().parent.parent/'knot-native-tests'
    parent.mkdir(exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='workspace-',dir=str(parent)))
    assert root.resolve().parent==parent.resolve()
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=False,args=['--window-position=60,60','--window-size=1200,900'])
        page=browser.new_page(viewport={'width':1600,'height':1000})
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(Path(__file__).with_name('index.html').as_uri())
        select_test_folder(page,root)
        allow_test_browser(browser,page)
        page.locator('#edit-dialog').wait_for(state='visible',timeout=10000)
        page.click('#edit-apply')
        page.locator('#edit-dialog').wait_for(state='hidden',timeout=15000)
        page.wait_for_function("()=>Workspace.phase==='saved'")
        data=json.loads((root/'workspace.json').read_text(encoding='utf-8'))
        assert data['version']==3 and len(data['tickets'])==10
        assert len(list((root/'tickets').glob('*.md')))==10
        assert len(list((root/'attachments').rglob('*.*')))==2
        assert all('description' not in t for t in data['tickets'])
        page.locator('#board [data-ticket="WEB-002"]').click()
        page.fill('#detail-description','## Native folder check\n\nActual Markdown disk write.\n')
        page.locator('#detail-description').press('Tab')
        page.wait_for_function("()=>Workspace.phase==='saved' && Workspace.saved===snapshot()")
        assert 'Actual Markdown disk write.' in (root/'tickets'/'WEB-002.md').read_text(encoding='utf-8')
        page.reload()
        page.locator('#workspace-menu').evaluate('(el)=>el.open=true')
        page.locator('#reopen-workspace').wait_for(state='visible')
        page.locator('#workspace-menu').evaluate('(el)=>el.open=true')
        page.click('#reopen-workspace')
        page.wait_for_function("()=>Workspace.phase==='saved'")
        page.locator('#board [data-ticket="WEB-002"]').click()
        assert 'Actual Markdown disk write.' in page.input_value('#detail-description')
        (root/'tickets'/'WEB-002.md').write_text('External Markdown edit.\n',encoding='utf-8')
        page.fill('#detail-assignee','Pending local edit')
        page.locator('#detail-assignee').press('Tab')
        page.wait_for_function("()=>Workspace.phase==='conflict'")
        assert (root/'tickets'/'WEB-002.md').read_text(encoding='utf-8')=='External Markdown edit.\n'
        page.locator('#workspace-menu').evaluate('(el)=>el.open=true')
        page.click('#reopen-workspace')
        page.locator('#use-disk-version').wait_for(state='visible')
        page.click('#use-disk-version')
        page.locator('#edit-dialog').wait_for(state='hidden')
        page.locator('#board [data-ticket="WEB-002"]').click()
        assert page.input_value('#detail-description')=='External Markdown edit.\n'
        page.screenshot(path=str(root/'verified-workspace.png'))
        assert not errors, errors
        browser.close()
    print('PASS: native picker, permission, JSON + Markdown + attachments, autosave, reload, reopen, external-change protection.')
    print('Verified test workspace:',root)


if __name__=='__main__':
    main()
