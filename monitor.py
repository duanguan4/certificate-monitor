"""Check once, email on positively verified issuance, then stop the workflow.

Never save page content, cookies, screenshots, passwords or personal data.
"""
import base64
import json
import os
import re
import smtplib
import ssl
import sys
import urllib.request
import urllib.error
from email.message import EmailMessage

URL = 'https://stu-ucc.fltrp.com/uchallenge/certificate.html'
TARGETS = ('综合能力', '笔译')
STATE = '.notification-sent.json'
COUNTER = '.monitor-counter.json'


def load_counter():
    try:
        item = api('contents/' + COUNTER)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        return {'runs': 0, 'reported_batch': 0}, None
    value = json.loads(base64.b64decode(item['content']))
    if not all(type(value.get(k)) is int and value[k] >= 0 for k in ('runs', 'reported_batch')):
        raise RuntimeError('Invalid monitor counter')
    return value, item['sha']


def save_counter(value, sha):
    body = {'message': 'Update automatic monitoring count',
            'content': base64.b64encode((json.dumps(value) + '\n').encode()).decode()}
    if sha:
        body['sha'] = sha
    saved = api('contents/' + COUNTER, 'PUT', body)
    return saved['content']['sha']


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
        print('Stage: open certificate page', flush=True)
        page.goto(URL, wait_until='domcontentloaded')
        page.get_by_role('textbox').nth(0).or_(page.get_by_role('link', name='退出', exact=True)).first.wait_for()
        if 'sso.unipus.cn' in page.url:
            print('Stage: fill login form', flush=True)
            fields = page.get_by_role('textbox')
            fields.nth(0).fill(os.environ['SITE_USERNAME'])
            fields.nth(1).fill(os.environ['SITE_PASSWORD'])
            print('Stage: login options', flush=True)
            page.get_by_role('checkbox', name='记住我', exact=True).uncheck()
            page.get_by_role('checkbox', name='我已阅读并同意', exact=False).check()
            page.get_by_role('button', name='登录', exact=True).click()
            print('Stage: wait for certificate page', flush=True)
        page.wait_for_url('https://stu-ucc.fltrp.com/uchallenge/certificate.html', timeout=45000)
        print('Stage: verify year tab', flush=True)
        page.get_by_role('link', name='2026证书查看', exact=False).wait_for()
        print('Stage: wait for certificate data', flush=True)
        for target in TARGETS:
            page.locator('p').filter(has_text=re.compile('2026.*' + target + '.*校赛')).first.wait_for()
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


def deliver(subject, content):
    msg = EmailMessage()
    msg['From'] = os.environ['SMTP_USER']
    msg['To'] = os.environ['MAIL_TO']
    msg['Subject'] = subject
    msg.set_content(content)
    with smtplib.SMTP_SSL('smtp.qq.com', 465, context=ssl.create_default_context(), timeout=30) as smtp:
        smtp.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
        smtp.send_message(msg)


def send(issued, test=False):
    subject = '证书监测测试：云端检查与邮件已连通' if test else '外研社证书已可下载'
    content = ('这是一封测试邮件。GitHub 云端已成功登录并检查证书页面。\n'
               '此邮件不代表证书已发放。自动监测将继续运行。\n' + URL) if test else (
                    '检测到以下 2026 年英语组校赛证书已出现下载入口：\n'
                    + '\n'.join(issued) + '\n\n请登录官网确认并下载：\n' + URL
                    + '\n\n本次提醒发送后，自动监测将停止。')
    deliver(subject, content)


def report(value, result, failed):
    labels = {'pending': '尚未发放', 'issued': '发现下载入口', 'unknown': '无法确认'}
    status = ('本次检查失败，暂时无法确认发放状态。请查看 GitHub Actions 运行记录。'
              if failed else '\n'.join(k + '：' + labels[v] for k, v in result.items()))
    deliver('证书监测定期汇报：累计自动运行 ' + str(value['runs']) + ' 次',
            '这是每累计 20 次自动运行的状态汇报。\n\n' + status
            + '\n\n' + URL + '\n\n手动测试不计数；GitHub 调度可能延迟。')


def main():
    if os.path.exists(STATE):
        stop()
        print('Previously notified; monitor disabled.')
        return
    value, sha = None, None
    if os.environ.get('GITHUB_EVENT_NAME') == 'schedule':
        value, sha = load_counter()
        value['runs'] += 1
        sha = save_counter(value, sha)
        print('Automatic run count: ' + str(value['runs']), flush=True)
    due = value is not None and value['runs'] // 20 > value['reported_batch']
    try:
        result = check()
        if 'unknown' in result.values():
            raise RuntimeError('Certificate status could not be verified.')
    except Exception:
        if due:
            report(value, {}, failed=True)
            value['reported_batch'] = value['runs'] // 20
            save_counter(value, sha)
            print('Periodic failure report sent.', flush=True)
        raise
    print('Check status: ' + ', '.join(f'{k}={v}' for k, v in result.items()))
    issued = [key for key, status in result.items() if status == 'issued']
    if not issued:
        if due:
            report(value, result, failed=False)
            value['reported_batch'] = value['runs'] // 20
            save_counter(value, sha)
            print('Periodic status report sent.', flush=True)
        if os.environ.get('TEST_EMAIL') == 'true':
            send([], test=True)
            print('Test email sent; monitoring remains enabled.')
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
