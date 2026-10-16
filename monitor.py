"""Check once, email on positively verified issuance, then stop the workflow.

Never save page content, cookies, screenshots, passwords or personal data.
"""
import base64
import json
import os
import smtplib
import ssl
import sys
import urllib.request
from email.message import EmailMessage

URL = 'https://stu-ucc.fltrp.com/uchallenge/certificate.html'
TARGETS = ('综合能力', '笔译')
STATE = '.notification-sent.json'


def api(path, method='GET', body=None):
    repo = os.environ['GITHUB_REPOSITORY']
    req = urllib.request.Request(
        f'https://api.github.com/repos/{repo}/{path}',
        data=None if body is None else json.dumps(body).encode(), method=method,
        headers={'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN'],
                 'Accept': 'application/vnd.github+json',
                 'X-GitHub-Api-Version': '2022-11-28',
                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def stop():
    api('actions/workflows/monitor.yml/disable', 'PUT')


def check():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(30000)
        page.goto(URL, wait_until='domcontentloaded')
        if 'sso.unipus.cn' in page.url:
            fields = page.get_by_role('textbox')
            fields.nth(0).fill(os.environ['SITE_USERNAME'])
            fields.nth(1).fill(os.environ['SITE_PASSWORD'])
            page.get_by_role('checkbox', name='记住我', exact=True).uncheck()
            page.get_by_role('checkbox', name='我已阅读并同意', exact=False).check()
            page.get_by_role('button', name='登录', exact=True).click()
        page.wait_for_url('https://stu-ucc.fltrp.com/uchallenge/certificate.html', timeout=45000)
        page.get_by_role('link', name='2026证书查看', exact=False).wait_for()
        # Require a download control in the same smallest course card. Merely
        # losing the "not issued" text never constitutes evidence of issuance.
        result = page.evaluate('''(targets) => {
          const visible = el => !!(el.getClientRects().length);
          const found = {};
          for (const target of targets) {
            const ps = [...document.querySelectorAll('p')].filter(p =>
              visible(p) && p.innerText.includes('2026') &&
              p.innerText.includes(target) && p.innerText.includes('校赛'));
            if (ps.length !== 1) { found[target] = 'unknown'; continue; }
            const p = ps[0];
            if (/尚未发放|未发放|敬请期待/.test(p.innerText)) {
              found[target] = 'pending'; continue;
            }
            if (p.innerText.includes('未报名')) { found[target] = 'unknown'; continue; }
            let card = p, issued = false;
            for (let i=0; card && i<4; i++, card=card.parentElement) {
              if (targets.some(t => t !== target && card.innerText.includes(t))) break;
              const controls = [...card.querySelectorAll('a,button,input[type="button"]')];
              issued = controls.some(el => visible(el) && !el.disabled &&
                el.getAttribute('aria-disabled') !== 'true' &&
                /下载/.test(el.innerText || el.value || el.getAttribute('title') || ''));
              if (issued) break;
            }
            found[target] = issued ? 'issued' : 'unknown';
          }
          return found;
        }''', list(TARGETS))
        browser.close()
        return result


def send(issued):
    msg = EmailMessage()
    msg['From'] = os.environ['SMTP_USER']
    msg['To'] = os.environ['MAIL_TO']
    msg['Subject'] = '外研社证书已可下载'
    msg.set_content('检测到以下 2026 年英语组校赛证书已出现下载入口：\n'
                    + '\n'.join(issued) + '\n\n请登录官网确认并下载：\n' + URL
                    + '\n\n本次提醒发送后，自动监测将停止。')
    with smtplib.SMTP_SSL('smtp.qq.com', 465, context=ssl.create_default_context(), timeout=30) as smtp:
        smtp.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
        smtp.send_message(msg)


def main():
    if os.path.exists(STATE):
        stop()
        print('Previously notified; monitor disabled.')
        return
    result = check()
    print('Check status: ' + ', '.join(f'{k}={v}' for k, v in result.items()))
    if 'unknown' in result.values():
        raise RuntimeError('Page format changed or certificate status could not be verified.')
    issued = [key for key, status in result.items() if status == 'issued']
    if not issued:
        return
    send(issued)
    # Public marker contains no identity, page content, course results or secrets.
    api('contents/' + STATE, 'PUT', {
        'message': 'Record completed certificate notification',
        'content': base64.b64encode(b'{"sent": true}\n').decode()})
    stop()
    print('Notification sent; monitor disabled.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Browser exceptions can include form contents: never print traceback.
        print('Monitor failed (' + type(exc).__name__ + '). Check login, mail authorization or site availability.', file=sys.stderr)
        sys.exit(1)
